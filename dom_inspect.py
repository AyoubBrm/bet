import asyncio
import logging
from playwright.async_api import async_playwright
import json

logging.basicConfig(level=logging.INFO)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        
        target = None
        for page in context.pages:
            if "bet365.com" in page.url and "P33891" in page.url:
                target = page
                break
        if not target:
            print("No page found!")
            return
            
        # Use JavaScript to extract everything
        result = await target.evaluate("""() => {
            // Find the Player Tackles pod
            const pods = document.querySelectorAll('.gl-MarketGroupPod');
            let tacklesPod = null;
            for (const pod of pods) {
                const textEl = pod.querySelector('.srb-ButtonWithBetBuilderIcon_Text, .cm-MarketGroupWithIconsButton_Text');
                if (textEl && (textEl.textContent.includes('Tackle') || textEl.textContent.includes('Tacle'))) {
                    tacklesPod = pod;
                    break;
                }
            }
            if (!tacklesPod) return {error: 'No tackles pod found'};
            
            // Get player names
            const nameEls = tacklesPod.querySelectorAll('.srb-ParticipantLabelWithTeam_Name');
            const names = Array.from(nameEls).map(el => el.textContent.trim());
            
            // Get column containers
            const colContainers = tacklesPod.querySelectorAll('.srb-HScrollPlaceColumnMarket');
            
            // For each column, get the header and odds
            const columns = [];
            for (const col of colContainers) {
                // The header is in a srb-HScrollParticipantHeader_Count or similar
                const headerEl = col.querySelector('.srb-HScrollParticipantHeader_Count');
                const header = headerEl ? headerEl.textContent.trim() : '';
                
                // Get all odds elements - they are gl-ParticipantOddsOnly_Odds
                const oddsEls = col.querySelectorAll('.gl-ParticipantOddsOnly_Odds');
                const odds = Array.from(oddsEls).map(el => el.textContent.trim());
                
                columns.push({header, oddsCount: odds.length, odds: odds.slice(0, 5)});
            }
            
            // Also dump the inner HTML of the first column's first few children
            const firstCol = colContainers[0];
            const children = [];
            if (firstCol) {
                for (let i = 0; i < Math.min(5, firstCol.children.length); i++) {
                    const child = firstCol.children[i];
                    children.push({
                        tag: child.tagName,
                        className: child.className,
                        text: child.textContent.trim().substring(0, 100),
                        childCount: child.children.length
                    });
                }
            }
            
            return {names: names.slice(0, 5), nameCount: names.length, columns, firstColChildren: children};
        }""")
        
        print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
