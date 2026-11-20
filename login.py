"""Open a visible browser so you can sign in to Personio.

Run by hand: sign in as normal (SSO, 2FA, whatever), wait until your Personio home
page has loaded, then close the window. fill.py also calls interactive_login()
itself when the saved session has expired; that window closes on its own once
you're signed in.

The session is kept in .profile/ and the company URL is remembered for the other
scripts.
"""

from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright, sync_playwright

from common import LOGIN_URL, URL_FILE, open_context


def start_url() -> str:
    """Your company's Personio address once known: it goes straight to your
    company's sign-in page. The generic login page is only for the first time."""
    if URL_FILE.exists() and personio_app(URL_FILE.read_text().strip()):
        return URL_FILE.read_text().strip() + "/"
    return LOGIN_URL


def personio_app(url: str) -> str | None:
    """'https://acme.app.personio.com/...' -> 'https://acme.app.personio.com', else None.

    Only a company's own app counts: login.personio.com and the public site
    www.personio.com don't.
    """
    u = urlparse(url)
    if u.hostname and u.hostname.endswith(".app.personio.com"):
        return f"{u.scheme}://{u.hostname}"
    return None


def interactive_login(pw: Playwright, close_when_done: bool, timeout_s: int = 600) -> bool:
    """Show the Personio sign-in page; return True once a signed-in page has loaded.

    close_when_done=False waits for you to close the window (manual use);
    True closes it as soon as you're signed in (automatic use from fill.py).
    """
    seen = None
    ctx = open_context(pw, headless=False)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(start_url())
        if close_when_done:
            page.wait_for_url(lambda url: personio_app(url) is not None, timeout=timeout_s * 1000)
            page.wait_for_load_state("load")
            seen = personio_app(page.url)
        else:
            def remember(frame):
                nonlocal seen
                if frame == page.main_frame and personio_app(frame.url):
                    seen = personio_app(frame.url)

            page.on("framenavigated", remember)
            page.wait_for_event("close", timeout=0)
    except PlaywrightError:
        pass  # window closed or timed out
    finally:
        try:
            ctx.close()
        except PlaywrightError:
            pass
    if seen:
        URL_FILE.write_text(seen + "\n")
    return seen is not None


def main() -> None:
    print("Sign in in the browser window, then close it when your home page shows.")
    with sync_playwright() as pw:
        ok = interactive_login(pw, close_when_done=False)
    print("Saved your Personio session." if ok else
          "Didn't see a Personio company page load, so nothing was saved. Try again.")


if __name__ == "__main__":
    main()
