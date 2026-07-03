import asyncio
import logging
import json
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_locator_click")

async def main():
    fixture_url = "https://www.bet365.com/#/AC/B1/C1/D8/E197033653/F3/I17/P33891/H1/"

    api_responses = []

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

        async def on_response(response):
            try:
                url = response.url
                if any(x in url for x in ["changefixture", "websiteroutingdatacontentapi", "splashcontentapi"]):
                    body = await response.text()
                    logger.info(f"Intercepted API: {url}")
                    api_responses.append({
                        "url": url,
                        "status": response.status,
                        "body": body
                    })
            except Exception as e:
                pass

        page.on("response", on_response)

        logger.info(f"Navigating to {fixture_url}...")
        await page.goto(fixture_url, wait_until="networkidle", timeout=60000)
        
        logger.info("Waiting for cookie consent banner...")
        try:
            accept_cookies = page.locator("text=Accepter tous")
            await accept_cookies.wait_for(timeout=5000)
            logger.info("Clicking Accept Cookies...")
            await accept_cookies.click()
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Could not find or click cookie banner: {e}")

        logger.info("Setting up locators for headers...")
        tackles_btn = page.locator(".srb-ButtonWithBetBuilderIcon").first
        passes_btn = page.locator(".cm-MarketGroupWithIconsButton").nth(1)

        logger.info("Waiting for headers to be visible...")
        await tackles_btn.wait_for(timeout=10000)

        # Periodically click to ensure JavaScript registers it
        for i in range(5):
            try:
                logger.info(f"Attempt {i+1}: Clicking tackles and passes...")
                await tackles_btn.click(timeout=1000)
                await passes_btn.click(timeout=1000)
            except Exception as e:
                logger.warning(f"Click attempt {i+1} failed: {e}")
            await asyncio.sleep(2)

        logger.info("Waiting final 5 seconds...")
        await asyncio.sleep(5)
        
        await page.screenshot(path="screenshot_locator.png")
        logger.info("Screenshot saved to screenshot_locator.png")
        
        with open("intercepted_payloads_locator.json", "w", encoding="utf-8") as f:
            json.dump(api_responses, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Saved {len(api_responses)} API payloads")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
