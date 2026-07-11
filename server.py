"""
Football Odds Analytics API
===========================
FastAPI app that reads upcoming football matches and Bet365 player markets from
Odds API, keeps player shot/tackle odds warm in Redis/PostgreSQL, and enriches
those markets with SofaScore player history for the frontend dashboard.
"""

import re
import json
import logging
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, engine, get_db
from app.services.monitor import monitor_loop
from app.services.sofascore import ascii_fold, get_sofascore_extraction, sofascore_service

# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("football_odds_api")



# ─────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────

monitor_task = None
sync_task = None
sofascore_warmup_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor_task, sync_task, sofascore_warmup_task
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
        
    # Start background workers.
    sofascore_warmup_task = asyncio.create_task(sofascore_service.warmup_sessions())
    monitor_task = asyncio.create_task(monitor_loop())
    if os.getenv("ENABLE_SYNC_WORKER", "true").lower() in {"1", "true", "yes"}:
        sync_task = asyncio.create_task(sync_worker_loop())
    else:
        sync_task = None
    yield
    
    # Clean up on shutdown
    for task in (monitor_task, sync_task, sofascore_warmup_task):
        if not task:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await sofascore_service.close()

app = FastAPI(
    lifespan=lifespan,
    title="Football Odds Analytics API",
    description="Tracks Bet365 player shot and tackle odds from Odds API and enriches them with SofaScore stats.",
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
            'https://api.odds-api.io/v3/events',
            params={
                'sport': 'football',
                'apiKey': api_key,
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        # Determine if the response is a direct list or nested inside a key like 'data'
        events = data if isinstance(data, list) else data.get("data", [])
        
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
            from app.database import AsyncSessionLocal
            from app.services.sofascore import DataExtractionService, SofaScoreService
            
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            async with AsyncSessionLocal() as db:
                service = SofaScoreService()
                try:
                    extractor = DataExtractionService(service, db=db)
                    await extractor.sync_mapped_finished_matches()
                finally:
                    await service.close()
                
        except Exception as e:
            logger.error(f"Error in background sync worker: {e}")
            
        await asyncio.sleep(900) # Check every 15 minutes

@app.get("/api/extraction/date/{date}")
async def run_extraction_pipeline(date: str, db: AsyncSession = Depends(get_db)):
    return await get_sofascore_extraction(date, db)

@app.get("/api/extraction/stream/{date}")
async def stream_extraction_pipeline(date: str):
    """SSE endpoint — streams one match at a time. Uses DB cache for instant loading."""
    from fastapi.responses import StreamingResponse
    from app.services.sofascore import DataExtractionService, sofascore_service
    from app.models.sofascore import Bet365SofascoreMapping, SofascoreCache, SofascoreMatchCache
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
                    cached_matches = sorted(
                        cache_entry.data["matches"],
                        key=lambda m: (m.get("startTimestamp") or 0, m.get("teams", ""))
                    )
                    for match in cached_matches:
                        yield f"data: {json.dumps(match)}\n\n"
                else:
                    # 2. Not cached -> Stream live and aggregate for caching
                    logger.info(f"[STREAM] No cache found for {date}, running live stream.")
                    extractor = DataExtractionService(sofascore_service, db=db)
                    
                    aggregated_matches = []
                    async for match_data in extractor.run_pipeline_stream(16, date):
                        aggregated_matches.append(match_data)
                        yield f"data: {json.dumps(match_data)}\n\n"
                        
                    # 3. Save to cache once done
                    if aggregated_matches:
                        aggregated_matches.sort(
                            key=lambda m: (m.get("startTimestamp") or 0, m.get("teams", ""))
                        )
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
@app.post("/api/extraction/stream/matches")
async def stream_matches_pipeline(payload: dict = Body(...)):
    """Stream a global sorted match queue with a hard limit of 2 live calculations."""
    from datetime import datetime as dt
    from fastapi.responses import StreamingResponse
    from app.database import AsyncSessionLocal
    from app.models.sofascore import Bet365SofascoreMapping, SofascoreCache, SofascoreMatchCache
    from app.services.sofascore import (
        DataExtractionService,
        attach_trusted_bet365_player_names,
        sofascore_service,
    )
    from sqlalchemy.future import select
    from sqlalchemy.exc import IntegrityError
    import json

    requested_matches = payload.get("matches", [])
    if not isinstance(requested_matches, list):
        raise HTTPException(status_code=400, detail="matches must be a list")

    try:
        match_concurrency = max(1, int(os.getenv("SOFASCORE_MATCH_CONCURRENCY", "2")))
    except ValueError:
        match_concurrency = 2

    def normalize_team(name: str) -> str:
        normalized = ascii_fold(name)
        normalized = normalized.lower()
        normalized = re.sub(r"\b(fc|cf|sc|club)\b", "", normalized)
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def parse_time(value: str) -> int:
        if not value:
            return 0
        try:
            clean_value = str(value).replace("Z", "+00:00")
            return int(dt.fromisoformat(clean_value).timestamp() * 1000)
        except ValueError:
            return 0

    def target_date(target: dict) -> str:
        return str(target.get("date") or "")[:10]

    def target_time(target: dict) -> int:
        return parse_time(str(target.get("date") or ""))

    def target_bet365_id(target: dict) -> str:
        return str(target.get("id") or "")

    def event_date(event: dict) -> str:
        start_ts = event.get("startTimestamp")
        if start_ts:
            return datetime.fromtimestamp(start_ts, timezone.utc).strftime("%Y-%m-%d")
        return str(event.get("date") or "")[:10]

    def event_time(event: dict) -> int:
        start_ts = event.get("startTimestamp")
        if start_ts:
            return int(start_ts) * 1000
        return parse_time(str(event.get("date") or ""))

    def event_teams(event: dict) -> tuple[str, str]:
        if event.get("home") and event.get("away"):
            return str(event.get("home") or ""), str(event.get("away") or "")
        return (
            str(event.get("homeTeam", {}).get("name") or ""),
            str(event.get("awayTeam", {}).get("name") or ""),
        )

    def same_teams(target: dict, event: dict) -> bool:
        target_home = normalize_team(target.get("home", ""))
        target_away = normalize_team(target.get("away", ""))
        event_home_raw, event_away_raw = event_teams(event)
        event_home = normalize_team(event_home_raw)
        event_away = normalize_team(event_away_raw)
        return (
            target_home == event_home and target_away == event_away
        ) or (
            target_home == event_away and target_away == event_home
        )

    def find_best_event(target: dict, candidates: list[dict], used_indexes: set[int]):
        matches = []
        for index, candidate in enumerate(candidates):
            if index in used_indexes or not same_teams(target, candidate):
                continue
            matches.append((abs(target_time(target) - event_time(candidate)), index, candidate))
        if not matches:
            return None, None
        matches.sort(key=lambda item: item[0])
        _, index, candidate = matches[0]
        return index, candidate

    def attach_requested_player_names(match_data: dict, requested_player_names: list[str]) -> dict:
        return attach_trusted_bet365_player_names(
            match_data,
            requested_player_names,
            filter_unlinked=False,
        )

    async def event_generator():
        per_date_live: dict[str, dict] = {}
        dates = []
        for target in requested_matches:
            date_key = target_date(target)
            if date_key and date_key not in dates:
                dates.append(date_key)

        try:
            pending_live: list[dict] = []
            active: dict[asyncio.Task, dict] = {}
            progress_queue: asyncio.Queue[dict] = asyncio.Queue()

            async def save_match_cache_background(item: dict, match_data: dict) -> None:
                async with AsyncSessionLocal() as db:
                    try:
                        await db.merge(SofascoreMatchCache(
                            match_id=str(match_data.get("match_id")),
                            bet365_event_id=str(item.get("bet365_event_id") or ""),
                            date=item["date"],
                            home=match_data.get("home"),
                            away=match_data.get("away"),
                            start_timestamp=match_data.get("startTimestamp"),
                            data=match_data,
                        ))
                        await db.commit()
                    except Exception as cache_error:
                        await db.rollback()
                        logger.warning(
                            "Finished match %s but failed to save match cache: %s",
                            match_data.get("match_id"),
                            cache_error,
                        )

            async def save_date_cache_background(date_key: str, sorted_matches: list[dict]) -> None:
                async with AsyncSessionLocal() as db:
                    try:
                        db.add(SofascoreCache(date=date_key, data={"date": date_key, "matches": sorted_matches}))
                        await db.commit()
                        logger.info("[STREAM] Saved global streamed data for %s to cache.", date_key)
                    except IntegrityError:
                        await db.rollback()
                        logger.info("[STREAM] Cache already exists for %s, skipping insert.", date_key)
                    except Exception as cache_error:
                        await db.rollback()
                        logger.warning("[STREAM] Failed to save date cache for %s: %s", date_key, cache_error)

            async def calculate_live_match(item: dict) -> tuple[str, dict, bool]:
                async with AsyncSessionLocal() as db:
                    extractor = DataExtractionService(sofascore_service, db=db)
                    match_data = None
                    cacheable = True
                    async for progress_event in extractor.stream_match_progress(
                        item["event"],
                        item["date"],
                        {},
                        item.get("bet365_event_id"),
                        item.get("player_names") or [],
                    ):
                        if progress_event.get("type") == "match_done":
                            progress_data = progress_event.get("data", {})
                            match_data = progress_data.get("match")
                            cacheable = bool(progress_data.get("cacheable", True))
                            await progress_queue.put(progress_event)
                            continue
                        await progress_queue.put(progress_event)

                    if not match_data:
                        raise RuntimeError("SofaScore match calculation returned no result")

                    if cacheable:
                        asyncio.create_task(save_match_cache_background(item, match_data))
                    return item["date"], match_data, cacheable

            def start_pending_live() -> list[dict]:
                started_items = []
                while pending_live and len(active) < match_concurrency:
                    item = pending_live.pop(0)
                    task = asyncio.create_task(calculate_live_match(item))
                    active[task] = item
                    started_items.append(item)
                return started_items

            async def handle_finished_task(task: asyncio.Task):
                item = active.pop(task, {})
                try:
                    date_key, match_data, cacheable = await task
                except Exception as e:
                    logger.exception(
                        "Global stream match calculation failed for Bet365 %s: %s",
                        item.get("bet365_event_id"),
                        e,
                    )
                    return {
                        "type": "status",
                        "bet365_event_id": item.get("bet365_event_id"),
                        "match_id": item.get("event", {}).get("id"),
                        "status": "failed",
                    }

                date_state = per_date_live.get(date_key)
                if date_state is not None:
                    date_state["completed"] += 1
                    if cacheable:
                        date_state["matches"].append(match_data)
                    else:
                        date_state["cache_full_date"] = False

                if date_state and date_state["completed"] == date_state["expected"] and date_state["cache_full_date"]:
                    sorted_matches = sorted(
                        date_state["matches"],
                        key=lambda match: (match.get("startTimestamp") or 0, match.get("teams", "")),
                    )
                    asyncio.create_task(save_date_cache_background(date_key, sorted_matches))

                return None

            def drain_progress_events() -> list[dict]:
                events = []
                while not progress_queue.empty():
                    events.append(progress_queue.get_nowait())
                return events

            async def completed_now() -> list[dict]:
                ready = [task for task in active if task.done()]
                events = []
                for task in ready:
                    event_payload = await handle_finished_task(task)
                    if event_payload:
                        events.append(event_payload)
                events.extend(drain_progress_events())
                return events

            async def wait_for_progress_or_finished() -> list[dict]:
                queued_events = drain_progress_events()
                if queued_events:
                    return queued_events
                if not active:
                    return []

                progress_task = asyncio.create_task(progress_queue.get())
                wait_targets = set(active.keys())
                wait_targets.add(progress_task)
                done, _ = await asyncio.wait(wait_targets, return_when=asyncio.FIRST_COMPLETED)
                events = []
                if progress_task in done:
                    events.append(progress_task.result())
                else:
                    progress_task.cancel()

                for task in [task for task in done if task in active]:
                    event_payload = await handle_finished_task(task)
                    if event_payload:
                        events.append(event_payload)
                events.extend(drain_progress_events())
                return events

            for date_key in dates:
                targets_for_date = [target for target in requested_matches if target_date(target) == date_key]
                cached_payloads = []
                terminal_statuses = []
                live_items = []
                unresolved_targets = []

                async with AsyncSessionLocal() as db:
                    for target in targets_for_date:
                        bet365_id = target_bet365_id(target)
                        mapping = await db.get(Bet365SofascoreMapping, bet365_id) if bet365_id else None
                        if not mapping:
                            unresolved_targets.append(target)
                            continue

                        match_cache = await db.get(SofascoreMatchCache, str(mapping.sofascore_event_id))
                        if match_cache:
                            cached_match_data = attach_requested_player_names(
                                dict(match_cache.data),
                                target.get("players") or [],
                            )
                            if bet365_id:
                                cached_match_data["bet365_event_id"] = bet365_id
                            cached_payloads.append(cached_match_data)
                            continue

                        live_items.append({
                            "bet365_event_id": bet365_id,
                            "date": mapping.date,
                            "player_names": target.get("players") or [],
                            "sort_time": (mapping.start_timestamp or 0) * 1000 or target_time(target),
                            "event": mapping.event_data,
                        })

                    cache_entry = None
                    if unresolved_targets:
                        stmt = select(SofascoreCache).where(SofascoreCache.date == date_key)
                        result = await db.execute(stmt)
                        cache_entry = result.scalars().first()

                if unresolved_targets and cache_entry and "matches" in cache_entry.data:
                    candidates = sorted(
                        cache_entry.data["matches"],
                        key=lambda match: (match.get("startTimestamp") or 0, match.get("teams", "")),
                    )
                    used_indexes: set[int] = set()
                    mappings_to_save = []
                    for target in unresolved_targets:
                        index, candidate = find_best_event(target, candidates, used_indexes)
                        if candidate is None:
                            logger.warning("[STREAM] No cached SofaScore match found for %s v %s", target.get("home"), target.get("away"))
                            bet365_id = target_bet365_id(target)
                            if bet365_id:
                                terminal_statuses.append({
                                    "type": "status",
                                    "bet365_event_id": bet365_id,
                                    "status": "failed",
                                })
                            continue
                        used_indexes.add(index)
                        bet365_id = target_bet365_id(target)
                        cached_match_data = attach_requested_player_names(
                            dict(candidate),
                            target.get("players") or [],
                        )
                        if bet365_id:
                            cached_match_data["bet365_event_id"] = bet365_id
                        cached_payloads.append(cached_match_data)
                        if bet365_id:
                            mappings_to_save.append(Bet365SofascoreMapping(
                                bet365_event_id=bet365_id,
                                sofascore_event_id=str(candidate.get("match_id")),
                                date=date_key,
                                home=candidate.get("home"),
                                away=candidate.get("away"),
                                start_timestamp=candidate.get("startTimestamp"),
                                sync_status="pending",
                                event_data=candidate,
                            ))
                    if mappings_to_save:
                        async with AsyncSessionLocal() as db:
                            for mapping in mappings_to_save:
                                await db.merge(mapping)
                            for match_data in cached_payloads:
                                await db.merge(SofascoreMatchCache(
                                    match_id=str(match_data.get("match_id")),
                                    bet365_event_id=None,
                                    date=date_key,
                                    home=match_data.get("home"),
                                    away=match_data.get("away"),
                                    start_timestamp=match_data.get("startTimestamp"),
                                    data=match_data,
                                ))
                            await db.commit()
                elif unresolved_targets:
                    events = await sofascore_service.get_unique_tournament_scheduled_events(16, date_key)
                    candidates = [
                        event
                        for event in events
                        if event_date(event) == date_key
                        and event.get("id")
                        and event.get("status", {}).get("type") in ["notstarted", "delayed", "inprogress"]
                    ]
                    candidates.sort(key=lambda event: (event.get("startTimestamp") or 0, event.get("id") or 0))

                    used_indexes = set()
                    matched_events = []
                    mappings_to_save = []
                    cache_checks = []
                    for target in unresolved_targets:
                        index, candidate = find_best_event(target, candidates, used_indexes)
                        if candidate is None:
                            logger.warning("[STREAM] No live SofaScore match found for %s v %s", target.get("home"), target.get("away"))
                            bet365_id = target_bet365_id(target)
                            if bet365_id:
                                terminal_statuses.append({
                                    "type": "status",
                                    "bet365_event_id": bet365_id,
                                    "status": "failed",
                                })
                            continue
                        used_indexes.add(index)
                        matched_events.append(candidate)
                        bet365_id = target_bet365_id(target)
                        sofa_id = str(candidate.get("id"))
                        mappings_to_save.append(Bet365SofascoreMapping(
                            bet365_event_id=bet365_id,
                            sofascore_event_id=sofa_id,
                            date=date_key,
                            home=target.get("home"),
                            away=target.get("away"),
                            start_timestamp=candidate.get("startTimestamp"),
                            sync_status="pending",
                            event_data=candidate,
                        ))
                        cache_checks.append((target, candidate, bet365_id, sofa_id))

                    if mappings_to_save or cache_checks:
                        async with AsyncSessionLocal() as db:
                            for mapping in mappings_to_save:
                                if mapping.bet365_event_id:
                                    await db.merge(mapping)

                            for target, candidate, bet365_id, sofa_id in cache_checks:
                                match_cache = await db.get(SofascoreMatchCache, sofa_id)
                                if match_cache:
                                    cached_match_data = attach_requested_player_names(
                                        dict(match_cache.data),
                                        target.get("players") or [],
                                    )
                                    if bet365_id:
                                        cached_match_data["bet365_event_id"] = bet365_id
                                    cached_payloads.append(cached_match_data)
                                    continue
                                live_items.append({
                                    "bet365_event_id": bet365_id,
                                    "date": date_key,
                                    "player_names": target.get("players") or [],
                                    "sort_time": event_time(candidate) or target_time(target),
                                    "event": candidate,
                                })

                            await db.commit()

                    if matched_events:
                        per_date_live[date_key] = {
                            "expected": len([item for item in live_items if item["date"] == date_key]),
                            "completed": 0,
                            "matches": [],
                            "cache_full_date": len(matched_events) == len(candidates),
                        }

                if live_items:
                    for item in live_items:
                        yield f"data: {json.dumps({'type': 'status', 'bet365_event_id': item.get('bet365_event_id'), 'status': 'queued'})}\n\n"

                for status_payload in terminal_statuses:
                    yield f"data: {json.dumps(status_payload)}\n\n"

                cached_payloads.sort(key=lambda match: (event_time(match), match.get("teams", "")))
                for match_data in cached_payloads:
                    yield f"data: {json.dumps({'type': 'status', 'status': 'cached', 'match_id': match_data.get('match_id')})}\n\n"
                    yield f"data: {json.dumps({'type': 'match', 'data': match_data})}\n\n"

                live_items.sort(key=lambda item: item["sort_time"])
                pending_live.extend(live_items)
                for item in start_pending_live():
                    yield f"data: {json.dumps({'type': 'status', 'bet365_event_id': item.get('bet365_event_id'), 'status': 'calculating'})}\n\n"

                for event_payload in await completed_now():
                    yield f"data: {json.dumps(event_payload)}\n\n"

            while pending_live or active:
                for item in start_pending_live():
                    yield f"data: {json.dumps({'type': 'status', 'bet365_event_id': item.get('bet365_event_id'), 'status': 'calculating'})}\n\n"
                for event_payload in await wait_for_progress_or_finished():
                    yield f"data: {json.dumps(event_payload)}\n\n"

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Global stream error: %s", e)
            for item in list(active.values()) + pending_live:
                bet365_id = item.get("bet365_event_id")
                if bet365_id:
                    yield f"data: {json.dumps({'type': 'status', 'bet365_event_id': bet365_id, 'status': 'failed'})}\n\n"
        finally:
            yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
