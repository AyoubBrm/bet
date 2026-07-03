import asyncio
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_screenshot")

async def main():
    fixture_url = "https://www.bet365.com/#/AC/B1/C1/D8/E197033653/F3/I17/P33891/H1/"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        logger.info(f"Navigating to {fixture_url}...")
        await page.goto(fixture_url, wait_until="networkidle", timeout=60000)
        
        logger.info("Waiting 10 seconds...")
        await asyncio.sleep(10)
        
        await page.screenshot(path="screenshot_P33891.png")
        logger.info("Screenshot saved to screenshot_P33891.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
