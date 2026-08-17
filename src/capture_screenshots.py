"""capture_screenshots.py — Drive the Streamlit app with Playwright.

Captures the screens needed for the Q2 documentation:
  1. Sign-in page (top of the file, also surfaces registration tab if needed)
  2. Search & rate page (signed in as alice)
  3. User dashboard (signed in as alice)
  4. Admin console (gated -> key prompt)
  5. Admin console (unlocked via demo key)
  6. Admin catalogue CRUD view
  7. Admin engagement analytics view
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path("C:/Users/keypather/OneDrive - Keypath Education Australia Pty. Ltd/Desktop/WorkBuddy/A3_MRS")
OUT = ROOT / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

URL = "http://127.0.0.1:8765/"
ADMIN_KEY = "demo-admin-key"


async def shot(page, name: str) -> None:
    """Take a full-page screenshot."""
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"[ok] {name} -> {path}")


async def fill_by_label(page, label: str, value: str) -> None:
    """Streamlit renders every tab's input into the DOM at once, so a label
    lookup can match multiple inputs. We use ``.first`` to grab the sign-in
    form's field (rendered above the registration tab)."""
    await page.get_by_label(label).first.fill(value)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 980})
        page = await context.new_page()

        # ---- 1. Sign in ----
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_selector("text=Sign in", timeout=30_000)
        await page.wait_for_timeout(1500)
        await shot(page, "01_signin")

        # ---- 2. Sign in as alice ----
        await fill_by_label(page, "Username", "alice")
        await fill_by_label(page, "Password", "Demo1234!")
        # capture pre-click screenshot for debugging
        await shot(page, "01b_signin_filled")
        await page.get_by_role("button", name="Sign in").first.click()
        # wait briefly and dump the page's text for diagnostics
        await page.wait_for_timeout(4000)
        html = await page.content()
        Path("C:/Users/keypather/after_click.html").write_text(html, encoding="utf-8")
        # wait for the destination page to render; content load can take a while
        # because the recommender engine builds similarity matrices on first call.
        await page.wait_for_selector("h1:has-text('Search & rate')", timeout=60_000)
        await page.wait_for_timeout(2500)
        await shot(page, "02_search_and_rate_signed_in")

        # ---- 3. User dashboard ----
        await page.get_by_text("User dashboard", exact=True).first.click()
        await page.wait_for_selector("text=Top picks for you", timeout=30_000)
        await page.wait_for_timeout(2500)
        await shot(page, "03_user_dashboard")
        await page.evaluate("window.scrollBy(0, 900)")
        await page.wait_for_timeout(700)
        await shot(page, "03b_user_dashboard_scrolled")

        # ---- 4. Sign out, sign in as admin ----
        await page.evaluate("window.scrollTo(0, 0)")
        await page.get_by_text("Sign out").click()
        await page.wait_for_selector("text=Sign in", timeout=30_000)

        await fill_by_label(page, "Username", "admin")
        await fill_by_label(page, "Password", "AdminPass!23")
        await page.get_by_role("button", name="Sign in").first.click()
        await page.wait_for_selector("text=Admin console", timeout=30_000)
        await page.get_by_text("Admin console", exact=True).first.click()
        await page.wait_for_selector("text=Engagement", timeout=30_000)
        await page.wait_for_timeout(2000)
        await shot(page, "04_admin_analytics")

        # ---- 5. Admin catalogue ----
        await page.get_by_text("Manage catalogue").click()
        await page.wait_for_timeout(1500)
        await shot(page, "05_admin_catalogue")

        # ---- 6. Admin users ----
        await page.get_by_text("Users", exact=True).click()
        await page.wait_for_timeout(1000)
        await shot(page, "06_admin_users")

        # ---- 7. Admin key prompt ----
        await page.get_by_text("Sign out").click()
        await page.wait_for_selector("text=Sign in")
        # Click the Admin console radio (sidebar), even though not signed in
        await page.get_by_text("Admin console", exact=True).first.click()
        await page.wait_for_selector("text=Admin access required", timeout=30_000)
        await page.wait_for_timeout(800)
        await shot(page, "07_admin_key_prompt")

        await browser.close()
        print("[done]")


if __name__ == "__main__":
    asyncio.run(main())
