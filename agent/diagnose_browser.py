"""Local-only UI diagnostic; does not like posts or modify relationships."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from orbit_instagram_agent import load_config, required
from orbit_browser_actions import browser_context, assert_account, mark_thread_rows, shared_post_ids

config_path = Path(__file__).resolve().parent.parent / ".env.agent"
config = load_config(config_path)
with sync_playwright() as playwright:
    context, browser = browser_context(playwright, config_path, config)
    try:
        assert_account(context, required(config, "ORBIT_INSTAGRAM_USERNAME"))
        page = context.new_page()
        page.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded")
        general = page.get_by_role("tab", name="General", exact=True)
        general.wait_for(timeout=25000)
        general.click()
        page.wait_for_timeout(3000)
        rows = mark_thread_rows(page)
        print("thread_rows=" + str(len(rows)))
        print("roles=" + json.dumps(page.locator("[role]").evaluate_all(
            'nodes => nodes.map(n => n.getAttribute("role")).reduce((a,r)=>(a[r]=(a[r]||0)+1,a),{})')))
        row = page.locator('[data-orbit-thread-row="0"]')
        if row.count():
            row.click()
            page.wait_for_url("**/direct/t/**", timeout=15000)
            page.wait_for_timeout(5000)
            print("post_links=" + str(page.locator('a[href*="/p/"]').count()))
            print("resolved_posts=" + str(len(shared_post_ids(page))))
        page.screenshot(path=str(config_path.parent / ".orbit-agent" / "inbox-diagnostic.png"))
    finally:
        context.close()
        if browser:
            browser.close()
