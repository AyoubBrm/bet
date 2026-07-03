import asyncio
import logging
from playwright.async_api import async_playwright
import json
import re

logging.basicConfig(level=logging.INFO)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = await context.new_page()
        
        captured = []
        async def on_response(response):
            try:
                body = await response.text()
                if body and ("|PA;" in body or "|CO;" in body) and "footerapi" not in response.url:
                    captured.append(body)
            except:
                pass
        page.on("response", on_response)
        
        url = "https://www.bet365.com/#/AC/B1/C1/D8/E197033653/F3/I17/P33891/H1/"
        await page.goto(url, wait_until="load", timeout=60000)
        
        # Click header
        await page.wait_for_selector(".srb-ButtonWithBetBuilderIcon", timeout=12000)
        await page.locator(".srb-ButtonWithBetBuilderIcon").first.click()
        await asyncio.sleep(2)
        
        # Click show more
        show_more = page.locator("text=/Afficher plus|Show more/i")
        if await show_more.count() > 0:
            await show_more.first.click()
            await asyncio.sleep(2)
            
        merged = "\n".join(captured)
        print(f"Captured {len(captured)} responses. Merged len={len(merged)}")
        
        with open("merged_debug.txt", "w", encoding="utf-8") as f:
            f.write(merged)
            
        # Find all |MG; blocks and their players
        mg_blocks = merged.split("|MG;")
        print(f"MG blocks count: {len(mg_blocks)}")
        for idx, block in enumerate(mg_blocks):
            header = block.split("|")[0]
            print(f"Block {idx} Header: {header}")
            
            # Find players
            pas = re.findall(r'\|PA;ID=(?:PC)?(\d+);NA=([^;]+);', block)
            print(f"  Players: {len(pas)}")
            if pas:
                print(f"    Sample: {pas[:3]}")
                
        await page.close()

if __name__ == "__main__":
    asyncio.run(main())
