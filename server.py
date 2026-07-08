"""
Bet365 Player Stats Scraper API
================================
FastAPI app that fetches live player statistics (tackles & shots) from Bet365
by navigating a real headless browser (Playwright) to the fixture page and
intercepting the API responses. Uses BeautifulSoup + regex for parsing.

Strategy:
  1. Playwright navigates to the bet365 fixture page (same URL you see in browser)
  2. Intercepts all XHR/Fetch responses from splashcontentapi
  3. Extracts the pipe-delimited player data from intercepted responses
  4. Parses with BeautifulSoup + regex to extract tackles/shots
"""

import re
import json
import random
import time
import logging
import asyncio
import traceback
from typing import Optional
from urllib.parse import quote, unquote
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bet365_scraper")

# ─────────────────────────────────────────────────────────────────────
# Proxy Configuration
# ─────────────────────────────────────────────────────────────────────

PW_PROXY = {
    "server": "http://res.geonix.com:10000",
    "username": "9614f20deabaca1c",
    "password": "2FUfRGWAl6Sq4CMu",
}

# ─────────────────────────────────────────────────────────────────────
# Anti-detection script injected into every Playwright browser context
# ─────────────────────────────────────────────────────────────────────

STEALTH_SCRIPT = """
    // Override navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    // Override chrome runtime
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
    };

    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // Override plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Override languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // Override platform
    Object.defineProperty(navigator, 'platform', {
        get: () => 'Win32',
    });

    // Override hardware concurrency
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
    });
"""


# ─────────────────────────────────────────────────────────────────────
# Helper: Clean fixture ID (strip leading 'E' if user passes it)
# ─────────────────────────────────────────────────────────────────────

def clean_fixture_id(fixture_id: str) -> str:
    """
    Strip the 'E' prefix if user passes it.
    bet365 URL format: #/AC/B1/C1/D8/E197033650/...
    The 'E' is a key prefix, not part of the ID.
    """
    fid = fixture_id.strip()
    if fid.upper().startswith("E") and fid[1:].isdigit():
        fid = fid[1:]
    return fid


# ─────────────────────────────────────────────────────────────────────
# Browser-based data fetcher
# ─────────────────────────────────────────────────────────────────────

class Bet365Browser:
    """
    Uses Playwright to navigate to the actual bet365 fixture page
    and intercept API responses containing player data.
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    async def _create_context(self, browser):
        """Create a new browser context with stealth settings."""
        # Get storage state from the default context (where the user's cookies are)
        storage_state = None
        if len(browser.contexts) > 0:
            try:
                storage_state = await browser.contexts[0].storage_state()
                logger.info("Successfully extracted session and cookies from default browser context.")
            except Exception as e:
                logger.warning(f"Could not extract storage state: {e}")

        # Force using the provided proxy because the local IP is blocked
        for proxy_config in [PW_PROXY]:
            proxy_label = "with proxy" if proxy_config else "without proxy"
            try:
                kwargs = {
                    "viewport": {"width": 1920, "height": 1080},
                    "locale": "en-US",
                    "timezone_id": "Europe/London",
                    "extra_http_headers": {
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                }
                if proxy_config:
                    kwargs["proxy"] = proxy_config
                
                if storage_state:
                    kwargs["storage_state"] = storage_state

                context = await browser.new_context(**kwargs)
                await context.add_init_script(STEALTH_SCRIPT)
                logger.info(f"Created browser context {proxy_label}")
                return context, proxy_label
            except Exception as e:
                logger.warning(f"Failed to create context {proxy_label}: {e}")
                continue

        raise RuntimeError("Failed to create browser context with any proxy config")

    async def _expand_market_headers(self, page, stat_name: str = "tackles"):
        """Automatically dismiss cookie consent, expand the target market header, and click 'Show more' to load all player data."""
        # 1. Accept cookies to make sure the popup doesn't block clicks
        try:
            accept_cookies = page.locator("text=/Accepter tous|Accept all/i")
            if await accept_cookies.is_visible():
                logger.info("🍪 Clicking Accept Cookies banner...")
                await accept_cookies.click(timeout=3000)
                await asyncio.sleep(1.5)
        except Exception:
            pass

        # 2. Expand the specific market group header if collapsed
        try:
            header_selector = ".srb-ButtonWithBetBuilderIcon, .cm-MarketGroupWithIconsButton"
            logger.info("Waiting for market headers to load...")
            await page.wait_for_selector(header_selector, timeout=12000)
            
            header_map = {
                "tackles": ["Player Tackles", "Joueur - Tacles", "Tacles du joueur", "Tackles", "Tacles"],
                "shots": [
                    "Player Shots on Target",
                    "Player Headed Shots on Target",
                    "Player Shots on Target Outside Box",
                    "Player Shots", "Joueur - Tirs", "Tirs du joueur", "Shots", "Tirs"
                ],
                "passes": ["Player Passes", "Joueur - Passes", "Passes du joueur", "Passes"],
                "saves": ["Goalkeeper Saves", "Joueur - Arrêts", "Arrêts du gardien", "Saves", "Arrêts"]
            }
            target_texts = header_map.get(stat_name.lower(), [stat_name])
            
            header_btns = []
            for text in target_texts:
                locator = page.locator(header_selector).filter(has_text=re.compile(text, re.IGNORECASE))
                count = await locator.count()
                for i in range(count):
                    header_btns.append(locator.nth(i))
                    
            if header_btns:
                logger.info(f"🖱️ Found {len(header_btns)} headers matching '{stat_name}'. Checking if they need expansion...")
                for btn in header_btns:
                    try:
                        container = page.locator("div.gl-MarketGroupPod, div.gl-MarketGroup").filter(has=btn).first
                        is_closed = False
                        if await container.count() > 0:
                            container_class = await container.get_attribute("class") or ""
                            if "Closed" in container_class:
                                is_closed = True
                                    
                        if is_closed:
                            logger.info(f"🖱️ Clicking a closed header to expand it...")
                            await btn.click(timeout=3000)
                            await asyncio.sleep(1.5)
                    except Exception as e:
                        logger.warning(f"Error clicking a specific header: {e}")
            else:
                logger.warning(f"Could not find any header buttons for '{stat_name}'")
        except Exception as e:
            logger.error(f"Error expanding market header: {e}")

        # 3. Click all "Afficher plus" or "Show more" buttons to expand player lists
        try:
            show_more = page.locator("text=/Afficher plus|Show more/i")
            await page.wait_for_timeout(2000)
            
            count = await show_more.count()
            logger.info(f"🖱️ Found {count} 'Show more' buttons. Clicking them...")
            # Iterate backwards because clicking a button removes it from the DOM, shifting indices
            for i in range(count - 1, -1, -1):
                btn = show_more.nth(i)
                try:
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=2000)
                    await asyncio.sleep(1)
                except Exception:
                    pass
        except Exception as e:
            logger.info(f"No 'Show more' buttons found or clicked: {e}")

    async def fetch_fixture_data(self, fixture_id: str, stat_name: str = "tackles") -> list[str]:
        """
        Navigate to the bet365 fixture page and intercept ALL API responses
        that contain player data (pipe-delimited format with |PA; or |CO;).

        Returns a list of raw response bodies that contain player data.
        """
        from playwright.async_api import async_playwright

        fixture_id = clean_fixture_id(fixture_id)
        # We drop the hardcoded P parameter so the default player stats market loads
        fixture_url = f"https://www.bet365.com/#/AC/B1/C1/D8/E{fixture_id}/F3/I17/"

        logger.info(f"Navigating to fixture page: {fixture_url}")

        captured_responses = []

        async with async_playwright() as p:
            try:
                # Try to connect to user's real browser first
                logger.info("Attempting to connect to real Chrome via CDP on port 9222...")
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                logger.info("✅ Successfully connected to your real Chrome browser!")
            except Exception as e:
                logger.warning(f"Could not connect to CDP: {e}. Fallback to launching new browser.")
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
                if browser.contexts:
                    context = browser.contexts[0]
                    proxy_label = "existing CDP context"
                else:
                    context, proxy_label = await self._create_context(browser)

                # Set up HTTP response interceptor
                async def on_response(response):
                    """Capture API responses that contain player data."""
                    url = response.url
                    try:
                        body = await response.text()
                        if body and ("|PA;" in body or "|CO;" in body) and "footerapi" not in url:
                            # Wait for match blocks to load
                            await page.wait_for_selector('.rrc-02', timeout=20000)
                            await asyncio.sleep(2) # Give it time to fully render the list
                            
                            # Scroll a bit to load lazy elements
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                            await asyncio.sleep(1)
                            
                            # Get the HTML and parse
                            html = await page.content()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Matches in Player Shots on Target usually use rrc-02 container
                            matches = []
                            events = soup.find_all('div', class_=lambda c: c and ('rrc-02' in c or 'rrc-55' in c))
                            
                            for event in events:
                                try:
                                    # Extract from Player Shots style block (rrc-02)
                                    header_el = event.find('div', class_=lambda c: c and 'rrc-55d' in c)
                                    date_el = event.find('span', class_=lambda c: c and 'rrc-9a6' in c)
                                    
                                    if header_el:
                                        teams = header_el.text.strip().split(' v ')
                                        if len(teams) == 2:
                                            home_team, away_team = teams
                                        else:
                                            home_team = header_el.text.strip()
                                            away_team = ""
                                            
                                        date_str, time_str = "", ""
                                        if date_el:
                                            full_date = date_el.text.strip()
                                            # e.g., 'Fri 3 Jul 18:00'
                                            parts = full_date.rsplit(' ', 1)
                                            if len(parts) == 2:
                                                date_str, time_str = parts
                                            else:
                                                date_str = full_date

                                        matches.append({
                                            "date": date_str,
                                            "time": time_str,
                                            "home_team": home_team,
                                            "away_team": away_team,
                                            "link": ""
                                        })
                                        continue
                                except Exception as e:
                                    logger.error(f"Error parsing event: {e}")
                                    
                            logger.info(f"DOM scraped {len(matches)} matches from Player Shots page")
                            logger.info(f"📦 Captured HTTP API response: {url[:100]}... (length={len(body)})")
                            captured_responses.append(body)
                    except Exception:
                        pass

                page = await context.new_page()
                page.on("response", on_response)

                # Set up WebSocket interceptor
                def on_ws(ws):
                    logger.info(f"🔌 WebSocket opened: {ws.url[:100]}")
                    def on_frame_received(payload):
                        ps = str(payload)
                        if "|PA;" in ps or "|CO;" in ps:
                            logger.info(f"🎯 PLAYER DATA IN WEBSOCKET! (length={len(ps)})")
                            captured_responses.append(ps)
                    ws.on("framereceived", on_frame_received)

                page.on("websocket", on_ws)

                # Navigate to the fixture page
                logger.info("Loading fixture page...")
                await page.goto(
                    fixture_url,
                    wait_until="load",
                    timeout=60000,
                )

                # Automatically accept cookies and expand collapsed headers
                await self._expand_market_headers(page, stat_name=stat_name)

                # Wait for the page's JavaScript/WebSockets to stream the API data
                logger.info("Waiting for data to populate...")
                await asyncio.sleep(8)

                # Check if data is embedded directly in the HTML (inline scripts)
                html = await page.content()
                if "|PA;" in html or "|CO;" in html:
                    logger.info("🎯 Found player data embedded in the HTML DOM!")
                    captured_responses.append(html)

                # Log what we captured
                logger.info(f"Captured {len(captured_responses)} API responses with player data")

            except Exception as e:
                logger.error(f"Browser fetch failed: {e}")
                logger.error(traceback.format_exc())
                raise
            finally:
                await browser.close()

        return captured_responses

    async def fetch_page_with_hash(
        self,
        hash_path: str,
        stat_name: str = "tackles",
        wait_seconds: int = 10,
        exact_markets: list[str] | None = None,
    ) -> list[dict]:
        """
        Navigate to any bet365 hash URL, expand the target market,
        and scrape player stats directly from the DOM.
        Returns a list of player dicts ready to return as JSON.

        Pass `exact_markets` to scrape multiple specific market pods (e.g.
        for shots: Player Shots on Target, Player Headed Shots on Target, etc.).
        """
        from playwright.async_api import async_playwright

        full_url = f"https://www.bet365.com/{hash_path}"
        logger.info(f"Navigating to: {full_url}")

        async with async_playwright() as p:
            try:
                logger.info("Attempting to connect to real Chrome via CDP on port 9222...")
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                logger.info("✅ Successfully connected to your real Chrome browser!")
            except Exception as e:
                logger.warning(f"Could not connect to CDP: {e}. Fallback to launching new browser.")
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

            page = None
            try:
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context, _ = await self._create_context(browser)

                page = await context.new_page()
                
                # Cleanup: close all other tabs in this context to prevent accumulation
                for p in context.pages:
                    if p != page:
                        try:
                            await p.close()
                        except Exception:
                            pass
                            
                await page.goto(full_url, wait_until="load", timeout=60000)

                # Expand the target market header and click "Show more"
                await self._expand_market_headers(page, stat_name=stat_name)

                logger.info(f"Waiting {wait_seconds}s for data to load...")
                await asyncio.sleep(wait_seconds)

                # Scrape the DOM directly
                result = await self._scrape_stats_from_dom(
                    page, stat_name, exact_markets=exact_markets
                )
                return result

            except Exception as e:
                logger.error(f"Page fetch failed: {e}")
                raise
            finally:
                await browser.close()

    async def _scrape_stats_from_dom(
        self,
        page,
        stat_name: str,
        exact_markets: list[str] | None = None,
    ) -> list[dict]:
        """
        Scrape player stats directly from the rendered DOM.

        When `exact_markets` is provided the function finds EACH pod whose
        title matches one of those strings and returns one entry per market
        group, keyed by the pod title.  This lets the shots endpoint return
        separate sections for:
          - Player Shots on Target
          - Player Headed Shots on Target
          - Player Shots on Target Outside Box

        When `exact_markets` is None the old behaviour (first matching pod)
        is used, so tackles / passes / saves are unaffected.
        """
        header_map = {
            "tackles": ["Tackle", "Tacle"],
            "shots": ["Shot", "Tir"],
            "passes": ["Pass"],
            "saves": ["Save", "Arrêt", "Gardien"],
        }
        keywords = header_map.get(stat_name.lower(), [stat_name])
        keywords_js = json.dumps(keywords)

        # ── Multi-market mode (e.g. shots with several sub-markets) ──────────
        if exact_markets:
            exact_markets_js = json.dumps(exact_markets)
            js_code = f"""() => {{
                const exactMarkets = {exact_markets_js};
                const pods = document.querySelectorAll('.gl-MarketGroupPod');
                const results = [];

                for (const pod of pods) {{
                    const textEl = pod.querySelector(
                        '.srb-ButtonWithBetBuilderIcon_Text, .cm-MarketGroupWithIconsButton_Text'
                    );
                    if (!textEl) continue;
                    const title = textEl.textContent.trim();
                    const matched = exactMarkets.find(
                        m => title.toLowerCase() === m.toLowerCase()
                    );
                    if (!matched) continue;

                    // Left column: player names (direct children of srb-HScrollParticipantMarket)
                    const leftCol = pod.querySelector('.srb-HScrollParticipantMarket');
                    if (!leftCol) continue;

                    // Right columns: odds (direct children of srb-HScrollPlaceColumnMarket)
                    const rightCols = pod.querySelectorAll('.srb-HScrollPlaceColumnMarket');
                    const columnHeaders = [];
                    for (const rc of rightCols) {{
                        const hdr = rc.querySelector('.srb-HScrollPlaceHeader');
                        if (hdr) columnHeaders.push({{ header: hdr.textContent.trim(), col: rc }});
                    }}

                    // Both left and right columns have the same number of children.
                    // Child [0] is the header row, children [1..N] are player rows.
                    // We iterate from index 1 and read name + odds at each index.
                    const totalRows = leftCol.children.length;
                    const players = [];

                    for (let i = 1; i < totalRows; i++) {{
                        const leftChild = leftCol.children[i];
                        const nameEl = leftChild.querySelector('.srb-ParticipantLabelWithTeam_Name');
                        if (!nameEl) continue;
                        const name = nameEl.textContent.trim();
                        if (!name) continue;

                        const odds = {{}};
                        for (const {{ header, col }} of columnHeaders) {{
                            if (i < col.children.length) {{
                                const oddsEl = col.children[i].querySelector('.gl-ParticipantOddsOnly_Odds');
                                odds[header] = oddsEl ? oddsEl.textContent.trim() : '';
                            }} else {{
                                odds[header] = '';
                            }}
                        }}
                        players.push({{ name, odds }});
                    }}

                    results.push({{ market: title, players }});
                }}

                return {{ multi: true, results }};
            }}"""

            data = await page.evaluate(js_code)
            multi_results = data.get("results", [])

            if not multi_results:
                logger.warning("DOM scrape (multi-market): no matching pods found.")
                return []

            stat_singular = stat_name[:-1] if stat_name.endswith('s') else stat_name
            all_markets = []

            for market_data in multi_results:
                market_title = market_data["market"]
                raw_players = market_data["players"]

                logger.info(
                    f"DOM scraped market '{market_title}': {len(raw_players)} players"
                )

                players_list = []
                for p in raw_players:
                    name = p["name"]
                    raw_odds = p["odds"]  # {"1+": "5.50", ...}
                    player_entry = {
                        "name of player": name,
                        "odds": {},
                    }
                    # Sort headers by numeric value to ensure 1+, 2+, 3+ order
                    sorted_headers = sorted(
                        raw_odds.keys(), 
                        key=lambda x: int(x.replace('+', '').strip()) if x.replace('+', '').strip().isdigit() else 999
                    )
                    for header in sorted_headers:
                        odds_value = raw_odds[header]
                        number = header.replace("+", "").strip()
                        formatted_key = f"{stat_singular} +{number}"
                        player_entry["odds"][formatted_key] = (
                            f"{odds_value} odds" if odds_value else "N/A"
                        )
                    players_list.append(player_entry)

                all_markets.append({
                    "market": market_title,
                    "number of players": len(players_list),
                    "players": players_list,
                })

            # Sort the all_markets list to exactly match the order of exact_markets
            def get_market_index(market_title):
                for idx, m in enumerate(exact_markets):
                    if m.lower() == market_title.lower():
                        return idx
                return 999

            all_markets.sort(key=lambda x: get_market_index(x["market"]))

            return all_markets

        # ── Single-market mode (tackles / passes / saves) ─────────────────────
        js_code = f"""() => {{
            const keywords = {keywords_js};

            // Find the correct Market Group pod
            const pods = document.querySelectorAll('.gl-MarketGroupPod');
            let targetPod = null;
            for (const pod of pods) {{
                const textEl = pod.querySelector(
                    '.srb-ButtonWithBetBuilderIcon_Text, .cm-MarketGroupWithIconsButton_Text'
                );
                if (textEl) {{
                    const t = textEl.textContent;
                    if (keywords.some(k => t.toLowerCase().includes(k.toLowerCase()))) {{
                        targetPod = pod;
                        break;
                    }}
                }}
            }}
            if (!targetPod) return {{ error: 'Market group not found' }};

            // Left column: player names
            const leftCol = targetPod.querySelector('.srb-HScrollParticipantMarket');
            if (!leftCol) return {{ error: 'Left column not found' }};

            // Right columns: odds
            const rightCols = targetPod.querySelectorAll('.srb-HScrollPlaceColumnMarket');
            const columnHeaders = [];
            for (const rc of rightCols) {{
                const hdr = rc.querySelector('.srb-HScrollPlaceHeader');
                if (hdr) columnHeaders.push({{ header: hdr.textContent.trim(), col: rc }});
            }}

            // Both left and right columns have the same number of children.
            // Child [0] is the header row, children [1..N] are player rows.
            const totalRows = leftCol.children.length;
            const players = [];

            for (let i = 1; i < totalRows; i++) {{
                const leftChild = leftCol.children[i];
                const nameEl = leftChild.querySelector('.srb-ParticipantLabelWithTeam_Name');
                if (!nameEl) continue;
                const name = nameEl.textContent.trim();
                if (!name) continue;

                const odds = {{}};
                for (const {{ header, col }} of columnHeaders) {{
                    if (i < col.children.length) {{
                        const oddsEl = col.children[i].querySelector('.gl-ParticipantOddsOnly_Odds');
                        odds[header] = oddsEl ? oddsEl.textContent.trim() : '';
                    }} else {{
                        odds[header] = '';
                    }}
                }}
                players.push({{ name, odds }});
            }}

            return {{ players }};
        }}"""

        data = await page.evaluate(js_code)

        if "error" in data:
            logger.warning(f"DOM scrape error: {data['error']}")
            return []

        raw_players = data.get("players", [])

        if not raw_players:
            logger.warning("DOM scrape returned no players.")
            return []

        logger.info(f"DOM scraped {len(raw_players)} players (index-aligned)")

        stat_singular = stat_name[:-1] if stat_name.endswith('s') else stat_name

        players_list = []
        for p in raw_players:
            name = p["name"]
            raw_odds = p["odds"]  # {"1+": "2.50", ...}
            player_entry = {
                "name": name,
                stat_name: {},
            }
            for header, odds_value in raw_odds.items():
                number = header.replace("+", "").strip()
                formatted_key = f"{stat_singular} +{number}"
                player_entry[stat_name][formatted_key] = (
                    f"{odds_value} odds" if odds_value else "N/A"
                )
            players_list.append(player_entry)

        return players_list

    async def fetch_upcoming_player_shots(self, url: str, wait_seconds: int = 5) -> list:
        """
        Navigates to the upcoming matches page and extracts match data directly from the DOM.
        """
        from playwright.async_api import async_playwright

        logger.info(f"Navigating to upcoming matches: {url}")

        async with async_playwright() as p:
            try:
                logger.info("Attempting to connect to real Chrome via CDP on port 9222...")
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                logger.info("✅ Successfully connected to your real Chrome browser!")
            except Exception as e:
                logger.warning(f"Could not connect to CDP: {e}. Fallback to launching new browser.")
                browser = await p.chromium.launch(
                    headless=False,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )

            if browser.contexts:
                context = browser.contexts[0]
            else:
                context, _ = await self._create_context(browser)
            page = None
            try:
                page = await context.new_page()
                
                # Cleanup: close all other tabs in this context to prevent accumulation
                for p in context.pages:
                    if p != page:
                        try:
                            await p.close()
                        except Exception:
                            pass
                            
                await page.goto(url, wait_until="load", timeout=60000)
                await asyncio.sleep(wait_seconds)

            except Exception as e:
                logger.warning(f"Timeout or error navigating: {e}")

            # Extract the coupon data on the final page
            js_code = """() => {
                const matches = [];
                // Search for blocks that look like the Player Shots layout (rrc-02)
                const matchEls = document.querySelectorAll('.rrc-02');

                for (const matchEl of matchEls) {
                    const headerEl = matchEl.querySelector('.rrc-55d');
                    const dateEl = matchEl.querySelector('.rrc-9a6');

                    if (headerEl) {
                        const headerText = headerEl.textContent.trim();
                        const teams = headerText.split(' v ');
                        const home_team = teams.length === 2 ? teams[0] : headerText;
                        const away_team = teams.length === 2 ? teams[1] : '';

                        let date_str = '';
                        let time_str = '';
                        if (dateEl) {
                            const full_date = dateEl.textContent.trim();
                            const parts = full_date.split(' ');
                            if (parts.length > 1) {
                                time_str = parts.pop();
                                date_str = parts.join(' ');
                            } else {
                                date_str = full_date;
                            }
                        }

                        let link = '';
                        const linkEl = matchEl.querySelector('a[href]');
                        if (linkEl) {
                            link = linkEl.getAttribute('href');
                        } else {
                            try {
                                const key = Object.keys(matchEl).find(k => k.startsWith('__reactFiber$'));
                                if (key) {
                                    let curr = matchEl[key];
                                    let depth = 0;
                                    let foundFixtureId = null;
                                    const searchObj = (obj, d = 0) => {
                                        if (d > 5 || !obj || typeof obj !== 'object') return null;
                                        for (const k in obj) {
                                            try {
                                                const val = obj[k];
                                                if (typeof val === 'string' && val.length >= 8 && /^\\d+$/.test(val)) return val;
                                                if (typeof val === 'object') {
                                                    const res = searchObj(val, d + 1);
                                                    if (res) return res;
                                                }
                                            } catch (e) {}
                                        }
                                        return null;
                                    };
                                    while (curr && depth < 20) {
                                        if (curr.memoizedProps) {
                                            if (curr.memoizedProps.fixtureId) foundFixtureId = curr.memoizedProps.fixtureId;
                                            if (curr.memoizedProps.fixture && curr.memoizedProps.fixture.id) foundFixtureId = curr.memoizedProps.fixture.id;
                                            if (!foundFixtureId) foundFixtureId = searchObj(curr.memoizedProps);
                                        }
                                        if (foundFixtureId) {
                                            const cleanId = foundFixtureId.endsWith('0') ? foundFixtureId.slice(0, -1) : foundFixtureId;
                                            link = `https://www.bet365.com/#/AC/B1/C1/D8/E${cleanId}/F3/`;
                                            break;
                                        }
                                        curr = curr.return;
                                        depth++;
                                    }
                                }
                            } catch (e) {}
                        }

                        matches.push({
                            date: date_str,
                            time: time_str,
                            home_team: home_team,
                            away_team: away_team,
                            link: link
                        });
                    }
                }

                // Fallback generic participant market extraction if no matches found
                if (matches.length === 0) {
                    const fallbackEls = document.querySelectorAll('.umr-70');
                    for (const event of fallbackEls) {
                        const dateHeader = event.querySelector('header');
                        const date = dateHeader ? dateHeader.textContent.trim() : "Unknown Date";

                        const timeDiv = event.querySelector('.umr-74');
                        const time = timeDiv ? timeDiv.textContent.trim() : "Unknown Time";

                        const teams = Array.from(event.querySelectorAll('.umr-71c'));
                        const home_team = teams.length > 0 ? teams[0].textContent.trim() : "Unknown Home Team";
                        const away_team = teams.length > 1 ? teams[1].textContent.trim() : "Unknown Away Team";

                        matches.push({
                            date: date,
                            time: time,
                            home_team: home_team,
                            away_team: away_team,
                            link: ""
                        });
                    }
                }

                if (matches.length === 0) {
                    const bodyHtml = document.body ? document.body.innerHTML : "No body";
                    return [{ error: "No matches found.", html: bodyHtml }];
                }

                // Backfill empty dates from previous matches
                let lastDate = 'Unknown Date';
                for (const m of matches) {
                    if (m.date) {
                        lastDate = m.date;
                    } else {
                        m.date = lastDate;
                    }
                }

                // Format the JSON exactly as requested by user in their original prompt
                const finalMatches = [];
                for (const m of matches) {
                    if (m.error) return matches;
                    finalMatches.push({
                        date: m.date,
                        time: m.time,
                        home_team: m.home_team,
                        away_team: m.away_team,
                        odds: m.odds,
                        link: m.link
                    });
                }
                return finalMatches;
            }"""
        
            try:
                html_dump = await page.evaluate("() => document.body.innerHTML")
                with open("C:/Users/bmayo/OneDrive/Desktop/SOFA/debug_player_shots.html", "w", encoding="utf-8") as f:
                    f.write(html_dump)
                logger.info("Saved HTML to debug_player_shots.html")
            
                matches = await page.evaluate(js_code)
                logger.info(f"DOM scraped {len(matches)} upcoming matches")
            
                return matches
            
            finally:
                await browser.close()

# Global browser instance
bet365 = Bet365Browser()


# ─────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager
import asyncio
import json
from app.services.monitor import monitor_loop
from app.database import engine, Base
import redis

monitor_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor_task
    # Create tables safely with retry for docker
    max_retries = 5
    for i in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            if i == max_retries - 1:
                raise e
            logger.warning(f"Database not ready yet, retrying in 3 seconds... ({e})")
            await asyncio.sleep(3)
        
    # Start the odds monitoring loop
    monitor_task = asyncio.create_task(monitor_loop())
    yield
    
    # Clean up on shutdown
    if monitor_task:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    lifespan=lifespan,
    title="Bet365 Player Stats Scraper",
    description="Fetches player tackles & shots from Bet365 using a real browser.",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────
# Data Parsing (BeautifulSoup + Regex)
# ─────────────────────────────────────────────────────────────────────

def parse_with_beautifulsoup(raw_html: str) -> str:
    """
    Use BeautifulSoup to extract the data payload from any HTML wrapper.
    """
    # If it looks like raw pipe-delimited data, return as-is
    if "|PA;" in raw_html or "|CO;" in raw_html:
        # Check if it's wrapped in HTML
        if "<html" in raw_html.lower():
            soup = BeautifulSoup(raw_html, "lxml")

            scripts = soup.find_all("script")
            for script in scripts:
                if script.string and ("|PA;" in script.string or "|CO;" in script.string):
                    return script.string

            pre = soup.find("pre")
            if pre:
                return pre.get_text()

            body = soup.find("body")
            if body:
                return body.get_text()

        return raw_html

    # Pure HTML with no pipe data
    soup = BeautifulSoup(raw_html, "lxml")
    body = soup.find("body")
    return body.get_text() if body else raw_html


def extract_player_stats(raw_data: str, stat_type: str = "tackles") -> dict:
    """
    Parse bet365 proprietary pipe-delimited format for player stats.
    """
    # 1. Split by Market Group (|MG;) to find the block corresponding to the requested stat
    mg_blocks = raw_data.split("|MG;")
    keywords = {
        "tackles": ["tackle", "tacle"],
        "shots": ["shot", "tir"],
        "passes": ["pass"],
        "saves": ["save", "arrêt", "gardien"]
    }.get(stat_type.lower(), [stat_type])
    
    matching_blocks = []
    for block in mg_blocks:
        header = block.split("|")[0]
        na_match = re.search(r'NA=([^;]+)', header)
        if na_match:
            name = na_match.group(1).lower()
            if any(k in name for k in keywords):
                logger.info(f"🎯 Found specific Market Group block: {na_match.group(1)} (len={len(block)})")
                matching_blocks.append(block)
                
    if matching_blocks:
        target_block = "\n".join(matching_blocks)
    else:
        logger.warning(f"No specific Market Group found for {stat_type}! Parsing all data.")
        target_block = raw_data

    # --- Build player ID → Name map from the target block ---
    player_map = {}
    player_matches = re.finditer(
        r'\|PA;ID=(?:PC)?(\d+);NA=([^;]+);', target_block
    )
    for match in player_matches:
        player_id = match.group(1)
        player_name = match.group(2).strip()
        if player_id not in player_map or player_name.strip() != "":
            player_map[player_id] = player_name

    logger.info(f"Found {len(player_map)} players in data")

    # --- Parse columns (lines like 1+, 2+, 3+, etc.) ---
    columns = target_block.split('|CO;')
    results = {}
    all_lines = []

    for col in columns[1:]:
        parts = col.split('|')
        co_header = parts[0]
        line_match = re.search(r'NA=([^;]+);', co_header)
        if not line_match:
            continue
        line = line_match.group(1)
        if line not in all_lines:
            all_lines.append(line)

        for part in parts[1:]:
            if part.startswith('PA;'):
                p_id_match = re.search(r'ID=(?:PC)?(\d+);', part)
                odds_match = re.search(r'OD=([^;]+);', part)

                if p_id_match and odds_match:
                    p_id = p_id_match.group(1)
                    odds = odds_match.group(1)

                    if p_id in player_map:
                        player_name = player_map[p_id]
                        if player_name not in results:
                            results[player_name] = {}
                        results[player_name][line] = odds

    logger.info(f"Parsed {len(results)} players with stats, lines: {all_lines}")

    return {
        "stat_type": stat_type,
        "players": results,
        "lines": all_lines,
        "total_players": len(results),
    }


def format_player_stats(parsed: dict) -> list[dict]:
    """Convert parsed data into a clean list of player stat objects."""
    players_list = []
    stat_key = parsed["stat_type"]
    stat_singular = stat_key[:-1] if stat_key.endswith('s') else stat_key
    global_lines = parsed["lines"]
    
    for player_name, lines in parsed["players"].items():
        player_entry = {
            "name of player": player_name,
            stat_key: {}
        }
        for line in global_lines:
            number = line.replace('+', '').strip()
            formatted_key = f"{stat_singular} +{number}" if '+' in line else f"{stat_singular} {line}"
            if line in lines:
                odds = lines[line]
                player_entry[stat_key][formatted_key] = f"{odds} odds"
            else:
                player_entry[stat_key][formatted_key] = "N/A"
        players_list.append(player_entry)
    return players_list


def merge_captured_data(responses: list[str], stat_type: str) -> dict:
    """
    Merge multiple captured API responses into one parsed result.
    Sometimes bet365 splits data across multiple responses.
    """
    merged_data = "\n".join(responses)
    return extract_player_stats(merged_data, stat_type)


# ─────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────

@app.get("/upcoming/matches")
def get_upcoming_matches():
    """
    Fetch upcoming football matches from Odds-API
    """
    import requests
    
    api_key = "164f27b032add66aa5dd77ae0f252443eae8b9136493a57b39f6385937771b0f"
    try:
        response = requests.get(
            'https://api.odds-api.io/v3/events?sport=football&apiKey=164f27b032add66aa5dd77ae0f252443eae8b9136493a57b39f6385937771b0f'
        )
        response.raise_for_status()
        data = response.json()
        
        # Determine if the response is a direct list or nested inside a key like 'data'
        events = data if isinstance(data, list) else data.get("data", [])
        
        import re
        filtered_events = []
        for event in events:
            if isinstance(event, dict):
                league = event.get("league", {})
                status = event.get("status")
                
                if league.get("slug") == "international-fifa-world-cup" and status == "pending":
                    home_team = str(event.get("home", ""))
                    away_team = str(event.get("away", ""))
                    
                    # Exclude placeholders like "W99", "L100", "RU101", or "TBC"
                    is_placeholder = (
                        re.match(r"^(?:W|L|RU)\d+$", home_team) or 
                        re.match(r"^(?:W|L|RU)\d+$", away_team) or 
                        "TBC" in home_team or 
                        "TBC" in away_team
                    )
                    
                    if not is_placeholder:
                        filtered_events.append(event)
                    
        return {
            "num_of_matches": len(filtered_events),
            "matches": filtered_events
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"API fetch failed: {str(e)}")


@app.get("/upcoming/odds")
def get_upcoming_odds():
    """
    Fetch upcoming football matches, then iterate through their IDs to fetch Bet365 odds.
    """
    import requests
    
    api_key = "164f27b032add66aa5dd77ae0f252443eae8b9136493a57b39f6385937771b0f"
    
    # 1. Reuse existing logic to get the filtered matches
    try:
        upcoming_data = get_upcoming_matches()
        matches = upcoming_data.get("matches", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch base matches: {str(e)}")
        
    # 2. Loop through each match ID and fetch odds
    results = []
    for match in matches:
        event_id = match.get("id")
        if not event_id:
            continue
            
        try:
            odds_response = requests.get(
                'https://api.odds-api.io/v3/odds',
                params={
                    'apiKey': api_key,
                    'eventId': event_id,
                    'bookmakers': 'Bet365'
                },
                timeout=10
            )
            
            odds_data = None
            if odds_response.ok:
                raw_odds = odds_response.json()
                
                # Filter to only "Player Shots" and "Player Tackles"
                bookmakers = raw_odds.get('bookmakers', {})
                bet365_markets = bookmakers.get('Bet365', [])
                
                filtered_markets = [
                    m for m in bet365_markets
                    if m.get('name') in ["Player Shots", "Player Tackles"]
                ]
                
                # Assign back the filtered markets
                if 'Bet365' in bookmakers:
                    raw_odds['bookmakers']['Bet365'] = filtered_markets
                    
                odds_data = raw_odds
            else:
                logger.warning(f"Failed to fetch odds for event {event_id}: HTTP {odds_response.status_code}")
                
            results.append({
                "match": match,
                "odds": odds_data
            })
        except Exception as e:
            logger.warning(f"Failed to fetch odds for event {event_id}: {str(e)}")
            results.append({
                "match": match,
                "odds": None
            })
            
    return {
        "num_of_matches": len(results),
        "matches_with_odds": results
    }


def parse_player_shots_market(market: dict):
    """
    Process ONLY the "Player Shots" market payload.
    Groups entries by player name, converts hdp to shot lines, and extracts the over odds.
    """
    import re
    
    if not market or market.get("name") != "Player Shots":
        return []
        
    players = {}
    
    for entry in market.get("odds", []):
        label = entry.get("label", "")
        hdp = entry.get("hdp")
        over_val = entry.get("over")
        
        if not label or hdp is None or over_val is None:
            continue
            
        # Remove the team identifier in parentheses
        player_name = re.sub(r'\s*\(\d+\)\s*$', '', label).strip()
        
        # Convert hdp into a shot line (e.g. 0.5 -> "shot 1+")
        try:
            hdp_float = float(hdp)
            shots = int(hdp_float + 0.5)
            shot_line = f"shot {shots}+"
        except ValueError:
            continue
            
        # Preserve the odds exactly
        try:
            odds_float = float(over_val)
        except ValueError:
            odds_float = over_val
            
        if player_name not in players:
            players[player_name] = {}
            
        players[player_name][shot_line] = odds_float
        
    # Format to expected output
    output = []
    for player, odds_dict in players.items():
        output.append({
            "player": player,
            "odds": odds_dict
        })
        
    return output

def parse_player_tackles_market(market_data: dict) -> list:
    """
    Parses the 'Player Tackles' market data according to the same rules as shots.
    """
    odds_list = market_data.get("odds", [])
    players = {}
    
    for entry in odds_list:
        label = entry.get("label", "")
        hdp = entry.get("hdp")
        over_val = entry.get("over")
        
        if not label or hdp is None or over_val is None:
            continue
            
        player_name = re.sub(r'\s*\(\d+\)\s*$', '', label).strip()
        
        try:
            hdp_float = float(hdp)
            tackles = int(hdp_float + 0.5)
            tackle_line = f"Tackle {tackles}+"
        except ValueError:
            continue
            
        try:
            odds_float = float(over_val)
        except ValueError:
            odds_float = over_val
            
        if player_name not in players:
            players[player_name] = {}
            
        players[player_name][tackle_line] = odds_float
        
    output = []
    for player, odds_dict in players.items():
        output.append({
            "player": player,
            "odds": odds_dict
        })
        
    return output


@app.get("/upcoming/player_shots")
async def get_parsed_player_shots():
    """
    Fetch the parsed Player Shots market from the Redis cache instantly.
    """
    try:
        import redis.asyncio as aioredis
        import os
        redis_host = os.getenv("REDIS_HOST", "localhost")
        rc = aioredis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)
        monitored = await rc.smembers("monitored_events")
        
        if monitored:
            parsed_results = []
            for eid in monitored:
                cache_key = f"event:{eid}:player_shots"
                data_str = await rc.get(cache_key)
                if data_str:
                    data = json.loads(data_str)
                    if "player_shots" in data:
                        data["player_shots"].sort(key=lambda p: len(p.get("odds", {})), reverse=True)
                    parsed_results.append(data)
                    
            if parsed_results:
                # Sort matches by date (earliest first)
                parsed_results.sort(key=lambda x: x.get("match", {}).get("date", ""))
                return {
                    "num_of_matches": len(parsed_results),
                    "matches": parsed_results
                }
    except Exception as e:
        logger.warning(f"Failed to read from Redis cache: {e}")
        
    # Fallback to fetching live
    try:
        odds_data = await asyncio.to_thread(get_upcoming_odds)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch base odds: {str(e)}")
        
    parsed_results = []
    
    for match_obj in odds_data.get("matches_with_odds", []):
        match_info = match_obj.get("match", {})
        odds_payload = match_obj.get("odds")
        
        parsed_players = []
        if odds_payload:
            bookmakers = odds_payload.get('bookmakers', {})
            bet365_markets = bookmakers.get('Bet365', [])
            
            shots_market = next((m for m in bet365_markets if m.get("name") == "Player Shots"), None)
            
            if shots_market:
                parsed_players = parse_player_shots_market(shots_market)
                
        parsed_results.append({
            "match": match_info,
            "player_shots": parsed_players
        })
        
    return {
        "num_of_matches": len(parsed_results),
        "matches": parsed_results
    }

@app.get("/upcoming/player_tackles")
async def get_parsed_player_tackles():
    """
    Fetch the parsed Player Tackles market from the Redis cache instantly.
    """
    try:
        import redis.asyncio as aioredis
        import os
        redis_host = os.getenv("REDIS_HOST", "localhost")
        rc = aioredis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)
        monitored = await rc.smembers("monitored_events")
        
        if monitored:
            parsed_results = []
            for eid in monitored:
                cache_key = f"event:{eid}:player_tackles"
                data_str = await rc.get(cache_key)
                if data_str:
                    data = json.loads(data_str)
                    if "player_tackles" in data:
                        data["player_tackles"].sort(key=lambda p: len(p.get("odds", {})), reverse=True)
                    parsed_results.append(data)
                    
            if parsed_results:
                # Sort matches by date (earliest first)
                parsed_results.sort(key=lambda x: x.get("match", {}).get("date", ""))
                return {
                    "num_of_matches": len(parsed_results),
                    "matches": parsed_results
                }
    except Exception as e:
        logger.warning(f"Failed to read from Redis cache: {e}")

    return {"num_of_matches": 0, "matches": []}


# ─────────────────────────────────────────────────────────────────────
# Sofascore Extraction Pipeline
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# Append-Only Sync Background Worker
# ─────────────────────────────────────────────────────────────────────

async def sync_worker_loop():
    logger.info("Started Background Worker for Append-Only Sync...")
    while True:
        try:
            from datetime import datetime
            import pytz
            
            from app.database import AsyncSessionLocal
            from app.services.sofascore import DataExtractionService, SofaScoreService
            
            today = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
            
            async with AsyncSessionLocal() as db:
                service = SofaScoreService()
                extractor = DataExtractionService(service, db=db)
                await extractor.sync_finished_matches_for_date(16, today)
                
        except Exception as e:
            logger.error(f"Error in background sync worker: {e}")
            
        await asyncio.sleep(900) # Check every 15 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(sync_worker_loop())

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.sofascore import get_sofascore_extraction

@app.get("/api/extraction/date/{date}")
async def run_extraction_pipeline(date: str, db: AsyncSession = Depends(get_db)):
    return await get_sofascore_extraction(date, db)

@app.get("/api/extraction/stream/{date}")
async def stream_extraction_pipeline(date: str):
    """SSE endpoint — streams one match at a time. Uses DB cache for instant loading."""
    from fastapi.responses import StreamingResponse
    from app.services.sofascore import DataExtractionService, SofaScoreService
    from app.models.sofascore import SofascoreCache
    from app.database import AsyncSessionLocal
    from sqlalchemy.future import select
    from sqlalchemy.exc import IntegrityError
    import json

    async def event_generator():
        # Open DB session inside the generator so it stays alive for the whole stream
        async with AsyncSessionLocal() as db:
            try:
                # 1. Check Cache First
                stmt = select(SofascoreCache).where(SofascoreCache.date == date)
                result = await db.execute(stmt)
                cache_entry = result.scalars().first()
                
                if cache_entry and "matches" in cache_entry.data:
                    logger.info(f"[STREAM] Found cached data for {date}, streaming instantly.")
                    for match in cache_entry.data["matches"]:
                        yield f"data: {json.dumps(match)}\n\n"
                else:
                    # 2. Not cached -> Stream live and aggregate for caching
                    logger.info(f"[STREAM] No cache found for {date}, running live stream.")
                    service = SofaScoreService()
                    extractor = DataExtractionService(service, db=db)
                    
                    aggregated_matches = []
                    async for match_data in extractor.run_pipeline_stream(16, date):
                        aggregated_matches.append(match_data)
                        yield f"data: {json.dumps(match_data)}\n\n"
                        
                    # 3. Save to cache once done
                    if aggregated_matches:
                        try:
                            new_cache = SofascoreCache(
                                date=date, 
                                data={"date": date, "matches": aggregated_matches}
                            )
                            db.add(new_cache)
                            await db.commit()
                            logger.info(f"[STREAM] Saved newly streamed data for {date} to cache.")
                        except IntegrityError:
                            await db.rollback()
                            
            except Exception as e:
                logger.error(f"Stream error: {e}")
            finally:
                yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

# ─────────────────────────────────────────────────────────────────────
# Run: python server.py
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
