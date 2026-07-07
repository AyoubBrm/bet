import httpx
import json
import time
import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.event import Event
from app.models.player import Player
from app.models.odds import PlayerShotOdds, PlayerTackleOdds

logger = logging.getLogger(__name__)

API_KEY = "164f27b032add66aa5dd77ae0f252443eae8b9136493a57b39f6385937771b0f"

def parse_player_shots_market(market: dict):
    if not market or market.get("name") != "Player Shots":
        return []
    players = {}
    for entry in market.get("odds", []):
        label = entry.get("label", "")
        hdp = entry.get("hdp")
        over_val = entry.get("over")
        if not label or hdp is None or over_val is None:
            continue
        player_name = re.sub(r'\s*\(\d+\)\s*$', '', label).strip()
        try:
            shots = int(float(hdp) + 0.5)
            shot_line = f"shot {shots}+"
            odds_float = float(over_val)
            if player_name not in players:
                players[player_name] = {}
            players[player_name][shot_line] = odds_float
        except ValueError:
            continue
    output = []
    for player, odds_dict in players.items():
        output.append({"player": player, "odds": odds_dict})
    return output

def parse_player_tackles_market(market: dict):
    if not market or market.get("name") != "Player Tackles":
        return []
    players = {}
    for entry in market.get("odds", []):
        label = entry.get("label", "")
        hdp = entry.get("hdp")
        over_val = entry.get("over")
        if not label or hdp is None or over_val is None:
            continue
        player_name = re.sub(r'\s*\(\d+\)\s*$', '', label).strip()
        try:
            tackles = int(float(hdp) + 0.5)
            tackle_line = f"Tackle {tackles}+"
            odds_float = float(over_val)
            if player_name not in players:
                players[player_name] = {}
            players[player_name][tackle_line] = odds_float
        except ValueError:
            continue
    output = []
    for player, odds_dict in players.items():
        output.append({"player": player, "odds": odds_dict})
    return output

async def fetch_updated_odds(since: int):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            'https://api.odds-api.io/v3/odds/updated',
            params={
                'apiKey': API_KEY,
                'bookmaker': 'Bet365',
                'sport': 'Football',
                'since': since
            },
            timeout=15.0
        )
        resp.raise_for_status()
        return resp.json()

async def process_updates(redis_client, db: AsyncSession, since: int):
    request_time = int(time.time())
    try:
        data = await fetch_updated_odds(since)
    except Exception as e:
        logger.error(f"Failed to fetch updated odds: {e}")
        return since
        
    events = data if isinstance(data, list) else data.get("data", [])
    if not events:
        return request_time
        
    for event_data in events:
        event_id = event_data.get("id")
        if not event_id:
            continue
            
        is_monitored = await redis_client.sismember("monitored_events", str(event_id))
        if not is_monitored:
            continue
            
        bookmakers = event_data.get("bookmakers", {}).get("Bet365", [])
        shots_market = next((m for m in bookmakers if m.get("name") == "Player Shots"), None)
        
        if shots_market:
            parsed_players = parse_player_shots_market(shots_market)
            
            for p_data in parsed_players:
                p_name = p_data["player"]
                new_odds = p_data["odds"]
                
                stmt = select(Player).where(Player.event_id == int(event_id), Player.name == p_name)
                result = await db.execute(stmt)
                player_obj = result.scalars().first()
                
                if not player_obj:
                    player_obj = Player(event_id=int(event_id), name=p_name)
                    db.add(player_obj)
                    await db.flush()
                    
                stmt_odds = select(PlayerShotOdds).where(PlayerShotOdds.player_id == player_obj.id)
                odds_res = await db.execute(stmt_odds)
                existing_odds = {o.shot_line: o for o in odds_res.scalars().all()}
                
                changed = False
                for shot_line, new_val in new_odds.items():
                    if shot_line in existing_odds:
                        if existing_odds[shot_line].odds_value != new_val:
                            existing_odds[shot_line].odds_value = new_val
                            changed = True
                    else:
                        new_odd_obj = PlayerShotOdds(player_id=player_obj.id, shot_line=shot_line, odds_value=new_val)
                        db.add(new_odd_obj)
                        changed = True
                
                if changed:
                    cache_key = f"event:{event_id}:player_shots"
                    cached_data_str = await redis_client.get(cache_key)
                    cached_obj = json.loads(cached_data_str) if cached_data_str else {"match": {}, "player_shots": []}
                    
                    cached_players = cached_obj.get("player_shots", [])
                    
                    found = False
                    for c_p in cached_players:
                        if c_p["player"] == p_name:
                            c_p["odds"].update(new_odds)
                            found = True
                            break
                    if not found:
                        cached_players.append({"player": p_name, "odds": new_odds})
                        
                    cached_obj["player_shots"] = cached_players
                    await redis_client.set(cache_key, json.dumps(cached_obj))
                
        tackles_market = next((m for m in bookmakers if m.get("name") == "Player Tackles"), None)
        if tackles_market:
            parsed_tackles = parse_player_tackles_market(tackles_market)
            for p_data in parsed_tackles:
                p_name = p_data["player"]
                new_odds = p_data["odds"]
                
                stmt = select(Player).where(Player.event_id == int(event_id), Player.name == p_name)
                result = await db.execute(stmt)
                player_obj = result.scalars().first()
                
                if not player_obj:
                    player_obj = Player(event_id=int(event_id), name=p_name)
                    db.add(player_obj)
                    await db.flush()
                    
                stmt_odds = select(PlayerTackleOdds).where(PlayerTackleOdds.player_id == player_obj.id)
                odds_res = await db.execute(stmt_odds)
                existing_odds = {o.tackle_line: o for o in odds_res.scalars().all()}
                
                changed = False
                for tackle_line, new_val in new_odds.items():
                    if tackle_line in existing_odds:
                        if existing_odds[tackle_line].odds_value != new_val:
                            existing_odds[tackle_line].odds_value = new_val
                            changed = True
                    else:
                        new_odd_obj = PlayerTackleOdds(player_id=player_obj.id, tackle_line=tackle_line, odds_value=new_val)
                        db.add(new_odd_obj)
                        changed = True
                
                if changed:
                    cache_key = f"event:{event_id}:player_tackles"
                    cached_data_str = await redis_client.get(cache_key)
                    cached_obj = json.loads(cached_data_str) if cached_data_str else {"match": {}, "player_tackles": []}
                    
                    cached_players = cached_obj.get("player_tackles", [])
                    found = False
                    for c_p in cached_players:
                        if c_p["player"] == p_name:
                            c_p["odds"].update(new_odds)
                            found = True
                            break
                    if not found:
                        cached_players.append({"player": p_name, "odds": new_odds})
                        
                    cached_obj["player_tackles"] = cached_players
                    await redis_client.set(cache_key, json.dumps(cached_obj))
                
    try:
        await db.commit()
    except Exception as e:
        logger.error(f"Database commit failed: {e}")
        await db.rollback()
        return since
        
    return request_time
