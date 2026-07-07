import asyncio
import time
import logging
import json
from app.database import AsyncSessionLocal
from app.services.redis_client import get_redis
from app.services.odds_updater import process_updates
from app.models.event import Event
from app.models.player import Player
from app.models.odds import PlayerShotOdds, PlayerTackleOdds
from sqlalchemy.future import select
from sqlalchemy import delete
from datetime import datetime

logger = logging.getLogger(__name__)

async def initialize_baseline(redis_client, db):
    # This imports the existing parser to get the initial state
    import server
    
    logger.info("Purging old monitoring data from PostgreSQL...")
    await db.execute(delete(Event))
    await db.flush()
    
    logger.info("Purging old monitoring data from Redis...")
    monitored = await redis_client.smembers("monitored_events")
    for eid in monitored:
        await redis_client.delete(f"event:{eid}:player_shots")
        await redis_client.delete(f"event:{eid}:player_tackles")
    await redis_client.delete("monitored_events")
    
    logger.info("Fetching completely fresh baseline data...")
    
    odds_data = await asyncio.to_thread(server.get_upcoming_odds)
    matches_with_odds = odds_data.get("matches_with_odds", [])
    
    matches = []
    for match_obj in matches_with_odds:
        match_info = match_obj.get("match", {})
        odds_payload = match_obj.get("odds")
        parsed_players = []
        parsed_tackles = []
        if odds_payload:
            bookmakers = odds_payload.get("bookmakers", {})
            bet365_markets = bookmakers.get("Bet365", [])
            
            shots_market = next((m for m in bet365_markets if m.get("name") == "Player Shots"), None)
            if shots_market:
                parsed_players = server.parse_player_shots_market(shots_market)
                
            tackles_market = next((m for m in bet365_markets if m.get("name") == "Player Tackles"), None)
            if tackles_market:
                parsed_tackles = server.parse_player_tackles_market(tackles_market)
                
        matches.append({
            "match": match_info,
            "player_shots": parsed_players,
            "player_tackles": parsed_tackles
        })
    
    for match_obj in matches:
        match_info = match_obj.get("match", {})
        event_id = match_info.get("id")
        if not event_id:
            continue
            
        await redis_client.sadd("monitored_events", str(event_id))
        
        # Save to Redis
        shots_obj = {"match": match_info, "player_shots": match_obj.get("player_shots", [])}
        await redis_client.set(f"event:{event_id}:player_shots", json.dumps(shots_obj))
        
        tackles_obj = {"match": match_info, "player_tackles": match_obj.get("player_tackles", [])}
        await redis_client.set(f"event:{event_id}:player_tackles", json.dumps(tackles_obj))
        
        # Save to PostgreSQL
        stmt = select(Event).where(Event.id == event_id)
        res = await db.execute(stmt)
        ev = res.scalars().first()
        
        if not ev:
            ev = Event(
                id=event_id, 
                home=match_info.get("home", ""), 
                away=match_info.get("away", ""),
                date=datetime.strptime(match_info.get("date", "").replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
            )
            db.add(ev)
            await db.flush()
            
            all_players = set([p["player"] for p in match_obj.get("player_shots", [])] + [p["player"] for p in match_obj.get("player_tackles", [])])
            
            for p_name in all_players:
                player_obj = Player(event_id=ev.id, name=p_name)
                db.add(player_obj)
                await db.flush()
                
                s_data = next((p for p in match_obj.get("player_shots", []) if p["player"] == p_name), None)
                if s_data:
                    for shot_line, val in s_data["odds"].items():
                        db.add(PlayerShotOdds(player_id=player_obj.id, shot_line=shot_line, odds_value=val))
                        
                t_data = next((p for p in match_obj.get("player_tackles", []) if p["player"] == p_name), None)
                if t_data:
                    for tackle_line, val in t_data["odds"].items():
                        db.add(PlayerTackleOdds(player_id=player_obj.id, tackle_line=tackle_line, odds_value=val))
                    
    await db.commit()
    logger.info("Baseline data initialized successfully.")

async def monitor_loop():
    logger.info("Starting Odds Monitor Loop...")
    redis_client = await get_redis()
    
    async with AsyncSessionLocal() as db:
        await initialize_baseline(redis_client, db)
    
    # 60 seconds max for since parameter to prevent clock drift 400 errors (API strictly limits to 90s)
    since = int(time.time()) - 60
    
    while True:
        try:
            # Distributed lock to prevent duplicate runs
            lock_acquired = await redis_client.set("monitor_lock", "locked", nx=True, ex=10)
            if lock_acquired:
                async with AsyncSessionLocal() as db:
                    new_since = await process_updates(redis_client, db, since)
                    max_past = int(time.time()) - 60
                    since = max(new_since, max_past)
                    
                    # Cleanup: Delete matches that have started
                    now = datetime.utcnow()
                    stmt = select(Event).where(Event.date <= now)
                    res = await db.execute(stmt)
                    expired_events = res.scalars().all()
                    for ev in expired_events:
                        # Remove from Redis
                        await redis_client.srem("monitored_events", str(ev.id))
                        await redis_client.delete(f"event:{ev.id}:player_shots")
                        await redis_client.delete(f"event:{ev.id}:player_tackles")
                        # Remove from DB (cascade deletes players and odds)
                        await db.delete(ev)
                        logger.info(f"Cleaned up expired event {ev.id}")
                    if expired_events:
                        await db.commit()
            else:
                pass
        except asyncio.CancelledError:
            logger.info("Monitor loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
            
        await asyncio.sleep(5)
