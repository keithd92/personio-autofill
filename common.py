"""Shared bits: where the browser profile lives and how to open it."""

from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / ".profile"
URL_FILE = PROFILE_DIR / "personio_url"
LOGIN_URL = "https://login.personio.com/"


def open_context(pw: Playwright, headless: bool) -> BrowserContext:
    PROFILE_DIR.mkdir(mode=0o700, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=headless,
        viewport={"width": 1400, "height": 900},
        locale="en-GB",
    )


def base_url() -> str:
    if not URL_FILE.exists():
        raise SystemExit("Not logged in yet: run `uv run login.py` first.")
    return URL_FILE.read_text().strip()
