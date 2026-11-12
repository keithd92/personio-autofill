"""Open a visible browser so you can sign in to Personio once.

Sign in as normal (SSO, 2FA, whatever), wait until your Personio dashboard
has loaded, then close the browser window. The session is kept in .profile/
and the company URL is remembered for the other scripts.
"""

from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from common import LOGIN_URL, URL_FILE, open_context


def main() -> None:
    last_personio = None
    with sync_playwright() as pw:
        ctx = open_context(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def remember(frame):
            nonlocal last_personio
            if frame != page.main_frame:
                return
            u = urlparse(frame.url)
            if u.hostname and u.hostname.endswith("personio.com") and not u.hostname.startswith("login."):
                last_personio = f"{u.scheme}://{u.hostname}"

        page.on("framenavigated", remember)
        page.goto(LOGIN_URL)
        print("Sign in in the browser window, then close it when your dashboard shows.")
        page.wait_for_event("close", timeout=0)
        ctx.close()

    if last_personio:
        URL_FILE.write_text(last_personio + "\n")
        print(f"Saved session for {last_personio}")
    else:
        print("Didn't see a Personio company page load, so nothing was saved. Try again.")


if __name__ == "__main__":
    main()
