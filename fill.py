"""Fill today's Personio attendance from config.toml using the dashboard widget.

Usage:
  uv run fill.py                  dry run: fills the form, screenshots it, does NOT submit
  uv run fill.py --submit         fills and submits
  uv run fill.py --submit --once  what the login/timer units run: at most one real
                                  attempt per day, recorded in state/

It skips the day (and says why) when:
  - today has no entry in config.toml (weekends)
  - Personio has no target hours today, checked in BOTH the home-page widget and
    the attendance grid (holidays, public holidays, full-day absences)
  - the configured hours don't match Personio's target (e.g. half-day absence)
  - something is already tracked today (use --overwrite to replace it)
"""

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

from common import ROOT, base_url, open_context

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SHOTS = ROOT / "dumps"
STATE = ROOT / "state"
TARGET_RE = re.compile(r"(\d+h(?:\s*\d+m)?)\s*/\s*(\d+h(?:\s*\d+m)?)")


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse_duration(text: str) -> int:
    """'8h 30m' -> 510, '6h' -> 360, '0h' -> 0. Raises on anything else.

    Personio's English labels only; raising (rather than reading 0) keeps an
    unreadable label from looking like "no target hours today".
    """
    if not re.fullmatch(r"\s*(\d+h)?\s*(\d+m)?\s*", text) or not re.search(r"\d", text):
        raise ValueError(f"can't read duration {text!r} (is Personio set to English?)")
    h = re.search(r"(\d+)h", text)
    m = re.search(r"(\d+)m", text)
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def notify(msg: str) -> None:
    print(msg)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "Personio attendance", msg], check=False)


def goto(page: Page, url: str, attempts: int = 10) -> None:
    """At login the network may not be up yet, so keep trying for ~5 minutes."""
    for i in range(attempts):
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle")
            return
        except Exception as e:  # noqa: BLE001 - any network/navigation failure
            if i == attempts - 1:
                raise
            print(f"couldn't load {url} ({type(e).__name__}), retrying in 30s")
            page.wait_for_timeout(30_000)


def grid_target(page: Page, attendance_path: str, today: dt.date) -> int | None:
    """Today's target minutes from the attendance grid, None when there's no target.

    Each day row holds <time datetime="YYYY-MM-DD">. Working days also have a
    tracked-vs-target area reading like "0h/8h 30m"; holidays, public holidays
    and full-day absences don't.
    """
    goto(page, base_url() + attendance_path)
    row = page.get_by_test_id("timesheet-timecard").filter(
        has=page.locator(f'time[datetime="{today.isoformat()}"]'))
    row.first.wait_for(timeout=15000)
    if row.count() != 1:
        raise RuntimeError(f"expected one grid row for {today}, found {row.count()}")
    area = row.get_by_test_id("tracked-vs-target-area")
    if area.count() == 0:
        return None
    text = " ".join(area.inner_text().split())
    m = TARGET_RE.search(text)
    if not m:
        raise RuntimeError(f"can't read target from {text!r} (is Personio set to English?)")
    return parse_duration(m.group(2))


def set_segment(page: Page, test_id: str, target: int) -> None:
    """Set one hours/minutes segment.

    Typing digits into a filled segment passes through in-between values ("13"
    goes 01 -> 13), and a break starting at 01:00 makes Personio's widget throw
    and vanish. So when the segment has a value, step to the target with arrow
    keys; only type into empty segments.
    """
    seg = page.get_by_test_id(test_id)
    seg.click()
    for _ in range(80):
        cur = seg.get_attribute("aria-valuenow")
        if cur is None:
            page.keyboard.type(f"{target:02d}")
            break
        cur = int(cur)
        if cur == target:
            break
        page.keyboard.press("ArrowUp" if cur < target else "ArrowDown")
    got = seg.get_attribute("aria-valuenow")
    if got is None or int(got) != target:
        raise RuntimeError(f"{test_id}: wanted {target:02d}, field shows {got}")


def current(page: Page, test_id: str) -> int | None:
    vals = [page.get_by_test_id(f"{test_id}-{p}").get_attribute("aria-valuenow") for p in ("hours", "minutes")]
    return None if None in vals else int(vals[0]) * 60 + int(vals[1])


def set_time(page: Page, test_id: str, hhmm: str) -> None:
    h, m = (int(x) for x in hhmm.split(":"))
    set_segment(page, f"{test_id}-hours", h)
    set_segment(page, f"{test_id}-minutes", m)


def set_interval(page: Page, start_id: str, end_id: str, start: str, end: str) -> None:
    """Moving an interval later: set the end first so start never passes end."""
    cur_end = current(page, end_id)
    if cur_end is not None and minutes(start) >= cur_end:
        set_time(page, end_id, end)
        set_time(page, start_id, start)
    else:
        set_time(page, start_id, start)
        set_time(page, end_id, end)


def label(widget: Locator) -> tuple[int, int | None]:
    """Return (tracked, target) minutes from the 'Xh Ym/Xh Ym' label."""
    title = widget.get_by_test_id("work-time-label").get_attribute("title") or ""
    tracked, _, target = title.partition("/")
    # An empty tracked part just means nothing logged yet; the target is what matters.
    return (parse_duration(tracked) if tracked.strip() else 0), (parse_duration(target) if target.strip() else None)


def fmt(mins: int | None) -> str:
    return "none" if mins is None else f"{mins // 60}h {mins % 60:02d}m"


def run(args: argparse.Namespace) -> int:
    today = dt.date.today()
    done_file = STATE / f"{today}.done"
    login_nagged = STATE / f"{today}.login-notified"

    def finish(code: int, msg: str, alert: bool = False) -> int:
        """A final outcome for today: record it so --once runs don't repeat it."""
        notify(f"{today}: {msg}") if alert else print(f"{today}: {msg}")
        if args.once and args.submit:
            STATE.mkdir(exist_ok=True)
            done_file.write_text(msg + "\n")
        return code

    if args.once and done_file.exists():
        print(f"{today}: already handled today ({done_file.read_text().strip()})")
        return 0

    config = Path(args.config)
    if not config.exists():
        notify(f"No {config.name}: copy config.example.toml to {config} and set your hours.")
        return 1
    cfg = tomllib.loads(config.read_text())
    day = cfg.get("days", {}).get(DAYS[today.weekday()])
    if not day:
        print(f"{today}: no hours configured for {DAYS[today.weekday()]}, nothing to do.")
        return 0

    work_start, work_end = day["work"]
    breaks = day.get("breaks", [])
    planned = minutes(work_end) - minutes(work_start) - sum(minutes(e) - minutes(s) for s, e in breaks)

    with sync_playwright() as pw:
        pw.selectors.set_test_id_attribute("data-test-id")
        ctx = open_context(pw, headless=not args.headed)
        page = ctx.new_page()
        goto(page, base_url() + "/")

        if "login." in page.url:
            msg = f"Personio session expired. Run `uv run login.py` in {ROOT}."
            if not login_nagged.exists():
                notify(msg)
                STATE.mkdir(exist_ok=True)
                login_nagged.touch()
            else:
                print(msg)
            return 2

        lang = page.evaluate("document.documentElement.dataset.languagePreference || document.documentElement.lang")
        if not (lang or "").startswith("en"):
            return finish(1, f"Personio is set to '{lang}'. This script reads English labels: switch your "
                             "Personio language to English. Not logged.", alert=True)

        # Check 1: the attendance grid.
        attendance_path = page.locator('a[href*="/attendance/employee/"]').first.get_attribute("href")
        from_grid = grid_target(page, attendance_path, today)
        if from_grid is None:
            return finish(0, "Personio shows no target hours today (holiday/absence). Not logging.")

        # Check 2: the home-page widget we fill in.
        goto(page, base_url() + "/")
        widget = page.get_by_test_id("manual-tracking-widget")
        try:
            widget.wait_for(timeout=15000)
        except Exception:
            SHOTS.mkdir(exist_ok=True)
            page.screenshot(path=SHOTS / "no-widget.png", full_page=True)
            return finish(1, "time tracking widget not on the home page (layout change?). Not logged.", alert=True)

        tracked, from_widget = label(widget)
        if not from_widget:
            return finish(0, "widget shows no target hours today (holiday/absence). Not logging.")
        if from_widget != from_grid:
            return finish(1, f"widget target {fmt(from_widget)} vs grid target {fmt(from_grid)}. "
                             "Not logged, check it by hand.", alert=True)
        if planned != from_widget:
            return finish(1, f"config gives {fmt(planned)} but Personio expects {fmt(from_widget)} "
                             "(half-day absence?). Not logged, fill it in by hand.", alert=True)
        if tracked and not args.overwrite:
            return finish(0, f"already tracked {fmt(tracked)}. Nothing to do.")

        set_interval(page, "manual-work-start", "manual-work-end", work_start, work_end)
        for i, (s, e) in enumerate(breaks):
            set_interval(page, f"break-period-start-{i}", f"break-period-end-{i}", s, e)
        if page.get_by_test_id("manual-tracking-widget").count() == 0:
            return finish(1, "Personio's time widget crashed while filling. Not logged, fill it in by hand.",
                          alert=True)

        new_tracked, _ = label(widget)
        SHOTS.mkdir(exist_ok=True)
        widget.screenshot(path=SHOTS / f"{today}-filled.png")
        if new_tracked != from_widget:
            return finish(1, f"form shows {fmt(new_tracked)} after filling, expected {fmt(from_widget)}. "
                             "Not logged.", alert=True)

        button = page.locator('[data-action-name="time-tracking-widget-submit-button"]')
        if not args.submit:
            print(f"{today}: DRY RUN filled {work_start}-{work_end}, breaks {breaks}; "
                  f"would click '{button.inner_text().strip()}'. Screenshot: {SHOTS / f'{today}-filled.png'}")
            return 0

        button.click()
        page.wait_for_load_state("networkidle")
        goto(page, base_url() + "/")
        page.get_by_test_id("manual-tracking-widget").wait_for(timeout=15000)
        after, _ = label(page.get_by_test_id("manual-tracking-widget"))
        if after != from_widget:
            page.screenshot(path=SHOTS / f"{today}-after-submit.png", full_page=True)
            return finish(1, f"submitted but Personio shows {fmt(after)} tracked. Check it by hand.", alert=True)
        ctx.close()
    return finish(0, f"logged {work_start}-{work_end}, breaks {breaks}.", alert=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="actually submit (default is a dry run)")
    ap.add_argument("--overwrite", action="store_true", help="replace an entry already tracked today")
    ap.add_argument("--once", action="store_true", help="stop if today already has a final outcome in state/")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--config", default=str(ROOT / "config.toml"), help="config file (default config.toml)")
    args = ap.parse_args()
    try:
        return run(args)
    except Exception as e:
        # Unexpected failure (Personio changed its page, network down for 5 min...).
        # Nothing is marked done, so the timer tries again; notify only once a day.
        flag = STATE / f"{dt.date.today()}.error-notified"
        msg = f"Personio attendance script failed: {type(e).__name__}: {e}"
        if args.once and not flag.exists():
            STATE.mkdir(exist_ok=True)
            flag.touch()
            notify(msg + " Check `journalctl --user -u personio-autofill`.")
        raise


if __name__ == "__main__":
    sys.exit(main())
