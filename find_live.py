import asyncio
import logging
import json
import re
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_live")

async def find_live_fixture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Go to soccer in-play or upcoming
        logger.info("Finding a live/upcoming soccer fixture...")
        await page.goto("https://www.bet365.com/#/IP/B1", wait_until="networkidle")
        
        # Wait a moment for data to populate
        await asyncio.sleep(5)
        
        # Extract a fixture ID from the page
        content = await page.content()
        match = re.search(r'E(\d{8,10})', content)
        if match:
            fixture_id = match.group(1)
            logger.info(f"🎯 FOUND LIVE FIXTURE ID: {fixture_id}")
            print(f"FOUND: {fixture_id}")
        else:
            logger.error("Could not find any fixture IDs on the page!")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(find_live_fixture())
