"""
Debug script: Dump the exact DOM structure of a bet365 market pod
to understand how player names map to odds columns.
"""
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = await context.new_page()
        await page.goto(
            "https://www.bet365.com/#/AC/B1/C1/D8/E197138029/F3/I15/",
            wait_until="networkidle",
        )
        await asyncio.sleep(5)

        # Click the first shots header to expand
        try:
            btn = page.locator(".srb-ButtonWithBetBuilderIcon").filter(
                has_text="Shots on Target"
            ).first
            await btn.click(timeout=3000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Could not click header: {e}")

        # Click show more
        try:
            sm = page.locator("text=/Show more|Afficher plus/i")
            for i in range(await sm.count()):
                await sm.nth(i).click(timeout=2000)
                await asyncio.sleep(1)
        except:
            pass

        await asyncio.sleep(2)

        # Now dump the full structure of the FIRST open pod
        result = await page.evaluate(r"""() => {
            const pods = document.querySelectorAll('.gl-MarketGroupPod');
            const output = [];

            for (const pod of pods) {
                const titleEl = pod.querySelector(
                    '.srb-ButtonWithBetBuilderIcon_Text, .cm-MarketGroupWithIconsButton_Text'
                );
                if (!titleEl) continue;
                const title = titleEl.textContent.trim();
                if (!title.toLowerCase().includes('shot')) continue;

                // Check if pod is closed
                if (pod.classList.contains('srb-HScrollFixtureSubGroupWithShowMore_Closed')) {
                    output.push({title, status: 'CLOSED'});
                    continue;
                }

                // ---- LEFT COLUMN: player names ----
                const nameEls = pod.querySelectorAll('.srb-ParticipantLabelWithTeam_Name');
                const names = Array.from(nameEls).map((el, idx) => ({
                    idx,
                    name: el.textContent.trim(),
                    // walk up to find the row container class
                    parentClasses: el.parentElement ? el.parentElement.className : '',
                    grandparentClasses: el.parentElement && el.parentElement.parentElement
                        ? el.parentElement.parentElement.className : '',
                }));

                // ---- RIGHT COLUMNS: odds ----
                const colContainers = pod.querySelectorAll('.srb-HScrollPlaceColumnMarket');
                const columns = [];
                for (const col of colContainers) {
                    const headerEl = col.querySelector('.srb-HScrollPlaceHeader');
                    const header = headerEl ? headerEl.textContent.trim() : '';

                    // Dump ALL direct children of the column
                    const children = [];
                    for (let i = 0; i < col.children.length; i++) {
                        const child = col.children[i];
                        const oddsEl = child.querySelector('.gl-ParticipantOddsOnly_Odds');
                        children.push({
                            idx: i,
                            tagName: child.tagName,
                            className: child.className.substring(0, 120),
                            oddsText: oddsEl ? oddsEl.textContent.trim() : null,
                            childCount: child.children.length,
                            innerText: child.textContent.trim().substring(0, 50),
                        });
                    }

                    columns.push({ header, childrenCount: children.length, children });
                }

                // ---- Also look for participant containers at pod level ----
                const participantContainers = pod.querySelectorAll('[class*="Participant"]');
                const uniqueClasses = [...new Set(
                    Array.from(participantContainers).map(el => el.className.split(' ')[0])
                )];

                output.push({
                    title,
                    status: 'OPEN',
                    nameCount: names.length,
                    firstNames: names.slice(0, 3),
                    columnCount: columns.length,
                    columns: columns.map(c => ({
                        header: c.header,
                        childrenCount: c.childrenCount,
                        first5Children: c.children.slice(0, 5),
                    })),
                    participantClassNames: uniqueClasses.slice(0, 15),
                });

                // Only dump the first open pod for clarity
                break;
            }

            return output;
        }""")

        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
        await page.close()

asyncio.run(run())
