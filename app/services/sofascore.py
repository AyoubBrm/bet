import asyncio
import logging
import random
import time
import unicodedata
from typing import Any, Dict, List, Optional
import httpx
from curl_cffi.requests import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.models.sofascore import SofascoreCache
from app.services.proxy_list import PROXY_LIST

# --- Configuration ---
SOFASCORE_BASE_URL = "https://api.sofascore.com"
HTTP_PROXIES = [
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10000",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10001",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10002",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10003",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10004",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10005",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10006",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10007",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10008",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10009",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10010",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10011",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10012",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10013",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10014",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10015",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10016",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10017",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10018",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10019",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10020",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10021",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10022",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10023",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10024",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10025",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10026",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10027",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10028",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10029",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10030",
    "http://becbb1b87101e920:NzXRCLbaivoTysKn@res.geonix.com:10031",
]
_SESSION_MAX_REQUESTS = 500
_TIMEOUT = 30
_MAX_RETRIES = 3
_DELAY_MIN = 0.0
_DELAY_MAX = 0.0

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8,"
              "application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "X-Requested-With": "XMLHttpRequest",
}

logger = logging.getLogger("sofascore_extractor")

# --- Services ---
class SofaScoreService:
    def __init__(self):
        self._base_url = SOFASCORE_BASE_URL.rstrip("/")
        self._proxies = HTTP_PROXIES
        # We will keep a pool of sessions equal to the number of proxies
        self._sessions: List[Optional[AsyncSession]] = [None] * len(self._proxies)
        self._request_counts: List[int] = [0] * len(self._proxies)
        self._warmed_up: List[bool] = [False] * len(self._proxies)
        self._session_locks = [asyncio.Lock() for _ in range(len(self._proxies))]
        
    async def _create_session_for_index(self, index: int) -> AsyncSession:
        kwargs = {
            "impersonate": "chrome",
            "headers": _BROWSER_HEADERS,
            "timeout": _TIMEOUT,
        }
        proxy = self._proxies[index]
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        
        session = AsyncSession(**kwargs)
        self._request_counts[index] = 0
        self._warmed_up[index] = False
        logger.info(f"curl_cffi AsyncSession created for proxy {index}")
        return session
        
    async def _ensure_session(self, index: int) -> AsyncSession:
        async with self._session_locks[index]:
            if self._sessions[index] is None:
                self._sessions[index] = await self._create_session_for_index(index)
            if self._request_counts[index] >= _SESSION_MAX_REQUESTS:
                await self._rotate_session_internal(index)
        return self._sessions[index]
        
    async def _warmup(self, session: AsyncSession, index: int) -> None:
        if self._warmed_up[index]:
            return
        async with self._session_locks[index]:
            if self._warmed_up[index] or session is not self._sessions[index]:
                return
            try:
                logger.info(f"Warming up session for proxy {index} — visiting sofascore.com …")
                await session.get("https://www.sofascore.com/", headers=_BROWSER_HEADERS)
                self._warmed_up[index] = True
            except Exception as exc:
                logger.warning(f"Session warmup failed (non-fatal) for proxy {index}: {exc}")
                self._warmed_up[index] = True
                
    async def _rotate_session_internal(self, index: int) -> None:
        if self._sessions[index] is not None:
            try:
                await self._sessions[index].close()
            except Exception:
                pass
        self._sessions[index] = await self._create_session_for_index(index)
        
    async def _rotate_session(self, old_session: Optional[AsyncSession], index: int) -> None:
        async with self._session_locks[index]:
            if old_session is not None and old_session is not self._sessions[index]:
                return
            await self._rotate_session_internal(index)
            
    async def close(self) -> None:
        for i in range(len(self._proxies)):
            async with self._session_locks[i]:
                if self._sessions[i] is not None:
                    await self._sessions[i].close()
                    self._sessions[i] = None

    async def _get(self, path: str, **params: Any) -> Any:
        index = random.randint(0, len(self._proxies) - 1)
        session = await self._ensure_session(index)
        await self._warmup(session, index)
        url = f"{self._base_url}{path}"
        if _DELAY_MAX > 0:
            await asyncio.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))
        last_exc: Optional[Exception] = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await session.get(url, params=params or None, headers=_API_HEADERS)
                if response.status_code >= 400:
                    if response.status_code == 403 and attempt < _MAX_RETRIES:
                        await self._rotate_session(session, index)
                        session = await self._ensure_session(index)
                        await self._warmup(session, index)
                        continue
                    mock_request = httpx.Request("GET", url)
                    mock_response = httpx.Response(status_code=response.status_code, request=mock_request, content=response.content)
                    error = httpx.HTTPStatusError(message=f"Upstream returned {response.status_code}", request=mock_request, response=mock_response)
                    
                    if response.status_code < 500 or attempt == _MAX_RETRIES:
                        raise error
                    else:
                        raise Exception(f"Upstream {response.status_code} error")
                self._request_counts[index] += 1
                return response.json()
            except httpx.HTTPStatusError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    backoff = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(backoff)
                    await self._rotate_session(session, index)
                    session = await self._ensure_session(index)
                    await self._warmup(session, index)
        raise httpx.HTTPError(f"Failed after {_MAX_RETRIES} retries: {last_exc}")
        
    async def get_unique_tournament_scheduled_events(self, unique_tournament_id: int, date: str) -> List[Dict[str, Any]]:
        try:
            data = await self._get(f"/api/v1/unique-tournament/{unique_tournament_id}/scheduled-events/{date}")
            return data if isinstance(data, list) else data.get("events", [data])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise
            
    async def get_match_lineups(self, match_id: int) -> Dict[str, Any]:
        data = await self._get(f"/api/v1/event/{match_id}/lineups")
        return data if isinstance(data, dict) else data
        
    async def get_team_players(self, team_id: int) -> Dict[str, Any]:
        data = await self._get(f"/api/v1/team/{team_id}/players")
        return data if isinstance(data, dict) else data
        
    async def get_player_events(self, player_id: int, page: int = 0) -> Dict[str, Any]:
        data = await self._get(f"/api/v1/player/{player_id}/events/last/{page}")
        return data if isinstance(data, dict) else data
        
    async def get_event_player_statistics(self, match_id: int, player_id: int) -> Dict[str, Any]:
        data = await self._get(f"/api/v1/event/{match_id}/player/{player_id}/statistics")
        return data if isinstance(data, dict) else data

class DataExtractionService:
    def __init__(self, sofascore_service: SofaScoreService, db=None):
        self._sofascore = sofascore_service
        self._semaphore = asyncio.Semaphore(30)
        self.db = db
        
    async def _safe_api_call(self, coro, default_return: Any = None) -> Any:
        async with self._semaphore:
            try:
                return await coro
            except httpx.HTTPStatusError as e:
                return default_return
            except Exception as e:
                return default_return
                
    async def run_pipeline(self, tournament_id: int, date: str) -> Dict[str, Any]:
        logger.info(f"Starting pipeline for tournament {tournament_id} on {date}")
        
        # 1. Match Discovery
        matches = await self._safe_api_call(self._sofascore.get_unique_tournament_scheduled_events(tournament_id, date), [])
        
        # Filter matches strictly to the requested date (UTC)
        from datetime import datetime, timezone
        strict_matches = []
        for m in matches:
            ts = m.get("startTimestamp")
            if ts:
                m_date = datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')
                if m_date == date:
                    strict_matches.append(m)
                    
        valid_matches = [m for m in strict_matches if m.get("id") and m.get("status", {}).get("type") in ["notstarted", "delayed"]]
        match_map = {m["id"]: m for m in valid_matches}
        match_ids = list(match_map.keys())
        
        # 2. Player Identification (Full Roster via Teams)
        matches_result = []
        async def fetch_team_players(team_id: int):
            if not team_id: return team_id, {}
            return team_id, await self._safe_api_call(self._sofascore.get_team_players(team_id), {})
            
        # Collect all unique team IDs from valid matches to avoid duplicate requests
        team_ids = set()
        for m in valid_matches:
            if m.get("homeTeam", {}).get("id"): team_ids.add(m["homeTeam"]["id"])
            if m.get("awayTeam", {}).get("id"): team_ids.add(m["awayTeam"]["id"])
            
        team_results = await asyncio.gather(*[fetch_team_players(t_id) for t_id in team_ids])
        team_data_map = {t_id: data for t_id, data in team_results}
        
        for m_id, match_info in match_map.items():
            match_players = {}
            home_team_id = match_info.get("homeTeam", {}).get("id")
            away_team_id = match_info.get("awayTeam", {}).get("id")
            
            for t_id in [home_team_id, away_team_id]:
                if not t_id or t_id not in team_data_map:
                    continue
                team_data = team_data_map[t_id]
                for player_entry in team_data.get("players", []):
                    player = player_entry.get("player")
                    if player and isinstance(player, dict) and player.get('id'):
                        raw_name = player.get('name', 'Unknown')
                        clean_name = unicodedata.normalize('NFKD', raw_name).encode('ASCII', 'ignore').decode('utf-8')
                        match_players[player['id']] = {"player_id": player['id'], "name": clean_name}
            
            home_team = match_info.get("homeTeam", {}).get("name", "Unknown")
            away_team = match_info.get("awayTeam", {}).get("name", "Unknown")
            matches_result.append({"match_id": m_id, "teams": f"{home_team} v {away_team}", "players": list(match_players.values())})
            
        # 3. History Mining & DB Check
        unique_players = {p["player_id"]: p for m in matches_result for p in m["players"]}
        
        player_stats = {}
        players_to_fetch = []
        
        if self.db:
            from app.models.sofascore import PlayerHistory
            from sqlalchemy.future import select
            
            # Fetch permanent history from DB
            stmt = select(PlayerHistory).where(PlayerHistory.player_id.in_([str(p) for p in unique_players.keys()]))
            result = await self.db.execute(stmt)
            for history_entry in result.scalars().all():
                player_stats[int(history_entry.player_id)] = history_entry.history
                
        for p_id in unique_players.keys():
            if p_id not in player_stats:
                players_to_fetch.append(p_id)
                
        newly_fetched_stats = {}
                
        if players_to_fetch:
            async def fetch_history(p_id: int):
                p0 = await self._safe_api_call(self._sofascore.get_player_events(p_id, 0), {})
                p1 = await self._safe_api_call(self._sofascore.get_player_events(p_id, 1), {})
                p_match_ids = []
                for pd in filter(None, [p0, p1]):
                    for e in pd.get("events", []):
                        if e.get("id"):
                            p_match_ids.append(e["id"])
                seen = set()
                return p_id, [m for m in p_match_ids if not (m in seen or seen.add(m))][:40]
                
            history_results = await asyncio.gather(*[fetch_history(p) for p in players_to_fetch])
            player_histories = dict(history_results)
            
            # 4. Statistical Extraction
            for p_id in players_to_fetch:
                newly_fetched_stats[p_id] = []
                
            async def fetch_stats(p_id: int, m_id: int):
                stats_data = await self._safe_api_call(self._sofascore.get_event_player_statistics(m_id, p_id), {})
                filtered_stats = None
                if stats_data and "statistics" in stats_data:
                    rs = stats_data["statistics"]
                    filtered_stats = {
                        "totalTackle": rs.get("totalTackle", 0),
                        "totalShots": rs.get("totalShots", 0),
                        "minutesPlayed": rs.get("minutesPlayed", 0)
                    }
                return p_id, {"played": bool(stats_data), "statistics": filtered_stats}
                
            stats_tasks = [fetch_stats(p_id, m_id) for p_id, m_ids in player_histories.items() for m_id in m_ids]
            stats_results = await asyncio.gather(*stats_tasks)
            
            for p_id, match_stat in stats_results:
                if match_stat["played"]:
                    newly_fetched_stats[p_id].append(match_stat)
            
            # Save newly fetched stats permanently to DB
            if self.db:
                from sqlalchemy.exc import IntegrityError
                try:
                    for p_id, stats in newly_fetched_stats.items():
                        self.db.add(PlayerHistory(player_id=str(p_id), history=stats))
                    await self.db.commit()
                    logger.info(f"Permanently saved history for {len(newly_fetched_stats)} new players.")
                except IntegrityError:
                    await self.db.rollback()
                    
            # Merge new stats into player_stats
            for p_id, stats in newly_fetched_stats.items():
                player_stats[p_id] = stats

        
        # Format Final Payload
        for m in matches_result:
            m["number_of_player's"] = len(m["players"])
            for p in m["players"]:
                p_id = p["player_id"]
                h_match_stats = player_stats.get(p_id, [])
                
                valid_stats = [st for st in h_match_stats if st.get("statistics") is not None]
                
                sum_tackles = sum(st["statistics"].get("totalTackle", 0) for st in valid_stats)
                sum_shots = sum(st["statistics"].get("totalShots", 0) for st in valid_stats)
                sum_minutes = sum(st["statistics"].get("minutesPlayed", 0) for st in valid_stats)
                
                if sum_minutes > 0:
                    x = sum_minutes / 90.0
                    tackles_per_90 = round(sum_tackles / x, 2)
                    shots_per_90 = round(sum_shots / x, 2)
                else:
                    x = tackles_per_90 = shots_per_90 = 0.0
                
                p["number_of_match's"] = len(h_match_stats)
                p["matchs"] = [{
                    "statistics": {
                        "totalTackle_in_number_of_match's": sum_tackles,
                        "totalShots_in_number_of_match's": sum_shots,
                        "minutesPlayed_in_number_of_match's": sum_minutes,
                        "minutesPlayed_per_90_minutes": round(x, 2),
                        "tackles_per_90_minutes": tackles_per_90,
                        "shots_per_90_minutes": shots_per_90
                    }
                }]
                
        return {"date": date, "matches": matches_result}

    async def sync_finished_matches_for_date(self, tournament_id: int, date: str):
        if not self.db:
            return
            
        from app.models.sofascore import SyncedMatch, PlayerHistory
        from sqlalchemy.future import select
        
        matches = await self._safe_api_call(self._sofascore.get_unique_tournament_scheduled_events(tournament_id, date), [])
        
        for match_info in matches:
            status = match_info.get("status", {}).get("type")
            if status != "finished":
                continue
                
            m_id = match_info.get("id")
            if not m_id:
                continue
                
            # Check if already synced
            stmt = select(SyncedMatch).where(SyncedMatch.match_id == str(m_id))
            result = await self.db.execute(stmt)
            if result.scalars().first():
                continue
                
            logger.info(f"Syncing finished match {m_id}")
            
            # Fetch lineups to get all players
            lineups = await self._safe_api_call(self._sofascore.get_match_lineups(m_id), {})
            if not lineups:
                continue
                
            players_to_sync = []
            for team_key in ["home", "away"]:
                for p_entry in lineups.get(team_key, {}).get("players", []):
                    p_id = p_entry.get("player", {}).get("id")
                    if p_id:
                        players_to_sync.append(p_id)
                        
            # Fetch stats for each player
            async def fetch_stats_for_sync(p_id: int):
                stats_data = await self._safe_api_call(self._sofascore.get_event_player_statistics(m_id, p_id), {})
                if not stats_data or "statistics" not in stats_data:
                    return p_id, None
                rs = stats_data["statistics"]
                minutes = rs.get("minutesPlayed", 0)
                if minutes == 0:
                    return p_id, None
                return p_id, {
                    "played": True,
                    "statistics": {
                        "totalTackle": rs.get("totalTackle", 0),
                        "totalShots": rs.get("totalShots", 0),
                        "minutesPlayed": minutes
                    }
                }
                
            sync_results = await asyncio.gather(*[fetch_stats_for_sync(p_id) for p_id in players_to_sync])
            
            # Append to DB
            for p_id, stats in sync_results:
                if not stats:
                    continue
                # Get current history
                stmt = select(PlayerHistory).where(PlayerHistory.player_id == str(p_id))
                result = await self.db.execute(stmt)
                history_entry = result.scalars().first()
                if history_entry:
                    # Append and mark as modified for JSON column
                    current_history = list(history_entry.history)
                    current_history.append(stats)
                    history_entry.history = current_history
                    self.db.add(history_entry)
            
            # Mark match as synced
            self.db.add(SyncedMatch(match_id=str(m_id)))
            await self.db.commit()
            logger.info(f"Successfully synced match {m_id} to persistent database.")


# Global service instance
sofascore_service = SofaScoreService()

async def get_sofascore_extraction(date: str, db) -> Dict[str, Any]:
    """
    Check the database cache first. If not present, run the heavy extraction pipeline,
    save it to the database, and return it.
    """
    # Check cache
    stmt = select(SofascoreCache).where(SofascoreCache.date == date)
    result = await db.execute(stmt)
    cache_entry = result.scalars().first()
    
    if cache_entry:
        logger.info(f"Returning cached sofascore extraction for {date}")
        return cache_entry.data
        
    # Not cached, run pipeline
    logger.info(f"No cache found for {date}. Running full extraction pipeline...")
    extraction_service = DataExtractionService(sofascore_service, db=db)
    data = await extraction_service.run_pipeline(16, date)
    
    # Save to cache
    try:
        new_cache = SofascoreCache(date=date, data=data)
        db.add(new_cache)
        await db.commit()
        logger.info(f"Saved new extraction for {date} to database cache.")
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Cache for {date} already exists, skipping insert.")
        
    return data
