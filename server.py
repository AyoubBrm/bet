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
    "username": "19d5d5ecee19c4e2",
    "password": "MUSRJBNjWVZAmzfd",
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
        # Try without proxy first (since the provided proxy is US-based and redirects to /usa)
        for proxy_config in [None, PW_PROXY]:
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

            try:
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context, _ = await self._create_context(browser)

                page = await context.new_page()
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


# Global browser instance
bet365 = Bet365Browser()


# ─────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Bet365 Player Stats Scraper",
    description="Fetches player tackles & shots from Bet365 using a real browser.",
    version="4.0.0",
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

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Bet365 Player Stats Scraper v4",
        "description": "Uses a real browser + DOM scraping to extract player stats.",
        "endpoints": {
            "/stats/tackles?fixture_id=XXX": "Player tackles",
            "/stats/shots?fixture_id=XXX": "Player shots",
            "/stats/page?url=FULL_URL": "Navigate to any bet365 URL and extract stats",
        }
    }


@app.get("/stats/tackles")
async def get_tackles(
    fixture_id: str = Query(
        default="197033650",
        description="Bet365 fixture/event ID (e.g. 197033650, not E197033650)",
    ),
):
    """Fetch player tackles statistics."""
    fid = clean_fixture_id(fixture_id)
    hash_path = f"#/AC/B1/C1/D8/E{fid}/F3/I17/P33891/H1/"
    try:
        players = await bet365.fetch_page_with_hash(hash_path, stat_name="tackles")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Browser fetch failed: {str(e)}")
    return {"number of player": len(players), "players": players}


@app.get("/stats/shots")
async def get_shots(
    fixture_id: str = Query(
        default="197033650",
        description="Bet365 fixture/event ID (e.g. 197033650, not E197033650)",
    ),
):
    """
    Fetch player shots statistics grouped by market:
      - Player Shots on Target
      - Player Headed Shots on Target
      - Player Shots on Target Outside Box
    """
    fid = clean_fixture_id(fixture_id)
    # Correct URL: D8 (not D7) and I15 (not I17) — matches the live bet365 shots page
    hash_path = f"#/AC/B1/C1/D8/E{fid}/F3/I15/"
    exact_markets = [
        "Player Shots on Target",
        "Player Headed Shots on Target",
        "Player Shots on Target Outside Box",
        "Player Shots",
    ]
    try:
        markets = await bet365.fetch_page_with_hash(
            hash_path,
            stat_name="shots",
            exact_markets=exact_markets,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Browser fetch failed: {str(e)}")
    return {
        "number of markets": len(markets),
        "markets": markets,
    }


@app.get("/stats/page")
async def get_from_url(
    url: str = Query(
        ...,
        description="Full bet365 URL, e.g. https://www.bet365.com/#/AC/B1/C1/D8/E197033650/F3/I17/P33588/H1/",
    ),
    stat_name: str = Query(default="tackles", description="Stat type name"),
    wait: int = Query(default=10, description="Seconds to wait for data to load"),
):
    """
    Navigate to any bet365 URL and extract player stats via DOM scraping.
    """
    if "#" in url:
        hash_path = "#" + url.split("#", 1)[1]
    else:
        hash_path = url

    try:
        players = await bet365.fetch_page_with_hash(hash_path, stat_name=stat_name, wait_seconds=wait)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Browser fetch failed: {str(e)}")

    return {"number of player": len(players), "players": players}


@app.get("/stats/raw")
async def get_raw(
    fixture_id: str = Query(default="197033650"),
    wait: int = Query(default=10, description="Seconds to wait for data to load"),
):
    """
    Fetch raw intercepted API responses for debugging.
    Shows exactly what bet365 returns.
    """
    fid = clean_fixture_id(fixture_id)

    try:
        responses = await bet365.fetch_fixture_data(fid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "fixture_id": fid,
        "responses_captured": len(responses),
        "responses": [
            {
                "index": i,
                "length": len(r),
                "preview": r[:2000],
                "has_player_data": "|PA;" in r,
                "has_columns": "|CO;" in r,
            }
            for i, r in enumerate(responses)
        ],
    }


# ─────────────────────────────────────────────────────────────────────
# Run: python server.py
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
