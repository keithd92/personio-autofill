"""Dump a Personio page (screenshot + accessibility tree) for building selectors.

Usage: uv run explore.py <path> [name]
  e.g. uv run explore.py /attendance/employee/123 attendance
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import ROOT, base_url, open_context


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "/"
    name = sys.argv[2] if len(sys.argv) > 2 else "page"
    out = ROOT / "dumps"
    out.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        ctx = open_context(pw, headless=True)
        page = ctx.new_page()
        page.goto(base_url() + path)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=out / f"{name}.png", full_page=True)
        (out / f"{name}.aria.yaml").write_text(page.locator("body").aria_snapshot())
        (out / f"{name}.html").write_text(page.content())
        print("final url:", page.url)
        ctx.close()


if __name__ == "__main__":
    main()
