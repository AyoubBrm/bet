import asyncio
import logging
from playwright.async_api import async_playwright
import traceback

logging.basicConfig(level=logging.INFO)

STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""

async def test_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1920,1080",
            ]
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Europe/London",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            await context.add_init_script(STEALTH_SCRIPT)
            page = await context.new_page()
            
            captured = []
            page.on("response", lambda r: captured.append(r.url))
            
            def on_ws(ws):
                print(f"WS opened: {ws.url}")
                ws.on("framereceived", lambda f: print(f"WS frame (len={len(str(f))}): {str(f)[:100]}"))
            page.on("websocket", on_ws)
            
            print("Navigating...")
            await page.goto("https://www.bet365.com/#/AC/B1/C1/D8/E197033653/F3/I17/P33891/H1/", wait_until="load", timeout=30000)
            print("Waiting 10s...")
            await asyncio.sleep(10)
            
            html = await page.content()
            print(f"HTML length: {len(html)}")
            if "|PA;" in html:
                print("Found |PA; in HTML!")
                
        except Exception as e:
            print("Error:", e)
            traceback.print_exc()
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_page())
