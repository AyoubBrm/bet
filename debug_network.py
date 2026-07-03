"""
Debug script: Test URL without P parameter.
"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug")

STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
"""

async def main():
    from playwright.async_api import async_playwright

    # URL without P parameter
    fixture_url = "https://www.bet365.com/#/AC/B1/C1/D8/E197138029/F3/I17/"

    http_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--window-size=1920,1080"]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        await context.add_init_script(STEALTH_SCRIPT)

        page = await context.new_page()

        async def on_response(response):
            try:
                body = await response.text()
                # Check for |PA; in body
                if "|PA;ID=" in body or "|CO;NA=" in body:
                    http_responses.append({
                        "url": response.url[:200],
                        "length": len(body),
                    })
                    logger.info(f"🎯 PLAYER DATA IN HTTP! len={len(body)}")
            except Exception:
                pass

        page.on("response", on_response)

        def on_ws(ws):
            def on_frame_received(payload):
                payload_str = str(payload)
                if "|PA;ID=" in payload_str or "|CO;NA=" in payload_str:
                    logger.info(f"🎯 PLAYER DATA IN WS! len={len(payload_str)}")
            ws.on("framereceived", on_frame_received)

        page.on("websocket", on_ws)

        logger.info(f"Navigating to {fixture_url}...")
        await page.goto(fixture_url, wait_until="domcontentloaded", timeout=60000)
        
        logger.info("Waiting 15 seconds...")
        await asyncio.sleep(15)
        
        # Take a screenshot to see what page actually loaded
        await page.screenshot(path="screenshot.png")
        logger.info("Saved screenshot to screenshot.png")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
