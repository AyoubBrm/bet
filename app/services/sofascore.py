import asyncio
import logging
import os
import random
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional
import httpx
from curl_cffi.requests import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.models.sofascore import SofascoreCache
from app.services.proxy_list import PROXY_LIST

# --- Configuration ---
SOFASCORE_BASE_URL = "https://api.sofascore.com"

def _read_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


_ACTIVE_PROXY_COUNT = _read_positive_int("SOFASCORE_ACTIVE_PROXY_COUNT", 20)
_PROXY_WARMUP_CONCURRENCY = _read_positive_int("SOFASCORE_PROXY_WARMUP_CONCURRENCY", 20)
HTTP_PROXIES = PROXY_LIST[:_ACTIVE_PROXY_COUNT] or [None]
_SESSION_MAX_REQUESTS = 500
_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.25
_RETRY_BACKOFF_MAX = 1.0
_RETRY_JITTER_MAX = 0.15
_DELAY_MIN = 0.0
_DELAY_MAX = 0.0
_PLAYER_HISTORY_TARGET_VALID = _read_positive_int("SOFASCORE_PLAYER_HISTORY_TARGET_VALID", 30)
_PLAYER_HISTORY_MAX_EVENTS = _read_positive_int("SOFASCORE_PLAYER_HISTORY_MAX_EVENTS", 60)
_PLAYER_HISTORY_MAX_PAGES = _read_positive_int("SOFASCORE_PLAYER_HISTORY_MAX_PAGES", 5)
_PLAYER_HISTORY_TIMEOUT_SECONDS = _read_positive_int("SOFASCORE_PLAYER_HISTORY_TIMEOUT_SECONDS", 120)
_MATCH_PLAYER_HISTORY_WAIT_SECONDS = _read_positive_int("SOFASCORE_MATCH_PLAYER_HISTORY_WAIT_SECONDS", 45)
_MATCH_CALCULATION_BATCH_SIZE = _read_positive_int("SOFASCORE_MATCH_BATCH_SIZE", 2)
_PLAYER_REQUEST_CONCURRENCY = _read_positive_int("SOFASCORE_PLAYER_REQUEST_CONCURRENCY", 30)

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

_ASCII_TRANSLITERATION = str.maketrans({
    "\u00f8": "o",
    "\u00d8": "O",
    "\u00e6": "ae",
    "\u00c6": "AE",
    "\u00e5": "a",
    "\u00c5": "A",
    "\u00f0": "d",
    "\u00d0": "D",
    "\u00fe": "th",
    "\u00de": "Th",
    "\u0142": "l",
    "\u0141": "L",
    "\u0111": "d",
    "\u0110": "D",
    "\u0131": "i",
})

_MOJIBAKE_MARKERS = ("\u00c3", "\u00c4", "\u00c5")


def _repair_mojibake(value: str) -> str:
    if not any(marker in value for marker in _MOJIBAKE_MARKERS):
        return value

    for encoding in ("cp1252", "latin1"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        if repaired:
            return repaired
    return value


def _repaired_text(value: Any) -> str:
    if value is None:
        return ""
    return _repair_mojibake(str(value))


def clean_display_name(value: Any) -> str:
    return _repaired_text(value).strip() or "Unknown"


def ascii_fold(value: Any) -> str:
    translated = _repaired_text(value).translate(_ASCII_TRANSLITERATION)
    return unicodedata.normalize("NFKD", translated).encode("ASCII", "ignore").decode("utf-8")


def _normalize_player_name(name: str) -> str:
    normalized = ascii_fold(name)
    normalized = normalized.lower()
    normalized = "".join(ch if ch.isalnum() else " " for ch in normalized)
    return " ".join(normalized.split())


def _player_name_match_details(requested_name: str, sofa_name: str) -> Optional[Dict[str, Any]]:
    requested = _normalize_player_name(requested_name)
    sofa = _normalize_player_name(sofa_name)
    if not requested or not sofa:
        return None

    if requested == sofa:
        return {"confidence": "exact", "score": 100}

    requested_tokens = requested.split()
    sofa_tokens = sofa.split()
    if not requested_tokens or not sofa_tokens:
        return None

    if len(requested) >= 5 and len(sofa) >= 5 and (requested in sofa or sofa in requested):
        return {"confidence": "fuzzy", "score": 88}

    same_last_name = requested_tokens[-1] == sofa_tokens[-1]
    if same_last_name and len(requested_tokens) >= 2 and len(sofa_tokens) >= 2:
        requested_first = requested_tokens[0]
        sofa_first = sofa_tokens[0]
        if requested_first == sofa_first:
            return {"confidence": "exact", "score": 95}
        if (
            len(requested_first) >= 3
            and len(sofa_first) >= 3
            and (requested_first.startswith(sofa_first) or sofa_first.startswith(requested_first))
        ):
            return {"confidence": "fuzzy", "score": 90}

        tokens_match = all(
            any(
                token == sofa_token
                or (len(token) >= 3 and sofa_token.startswith(token))
                or (len(sofa_token) >= 3 and token.startswith(sofa_token))
                for sofa_token in sofa_tokens
            )
            for token in requested_tokens
        )
        if tokens_match:
            return {"confidence": "fuzzy", "score": 84}

    similarity = SequenceMatcher(None, requested, sofa).ratio()
    if similarity >= 0.9:
        return {"confidence": "fuzzy", "score": int(similarity * 90)}

    return None


def _player_name_matches(requested_name: str, sofa_name: str) -> bool:
    return _player_name_match_details(requested_name, sofa_name) is not None


def _clean_requested_player_names(requested_player_names: Optional[List[str]]) -> List[str]:
    return list(dict.fromkeys(
        str(name).strip()
        for name in (requested_player_names or [])
        if str(name or "").strip()
    ))


def _trusted_player_name_links(
    players: List[Dict[str, Any]],
    requested_player_names: Optional[List[str]],
) -> Dict[int, Dict[str, Any]]:
    clean_requested_names = _clean_requested_player_names(requested_player_names)
    trusted_links: Dict[int, Dict[str, Any]] = {}

    for requested_name in clean_requested_names:
        candidates = []
        for index, player in enumerate(players):
            details = _player_name_match_details(requested_name, str(player.get("name", "")))
            if not details:
                continue
            candidates.append({
                "index": index,
                "score": details["score"],
                "confidence": details["confidence"],
                "sofa_name": player.get("name", ""),
            })

        if not candidates:
            logger.warning("No trusted SofaScore player match for Bet365 player '%s'.", requested_name)
            continue

        candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        if second and best["score"] - second["score"] < 8:
            logger.warning(
                "Ambiguous SofaScore player match for Bet365 player '%s': '%s' and '%s'.",
                requested_name,
                best["sofa_name"],
                second["sofa_name"],
            )
            continue

        link = trusted_links.setdefault(best["index"], {"names": [], "confidences": {}})
        link["names"].append(requested_name)
        link["confidences"][requested_name] = best["confidence"]

    return trusted_links


def attach_trusted_bet365_player_names(
    match_data: Dict[str, Any],
    requested_player_names: Optional[List[str]],
    filter_unlinked: bool = False,
) -> Dict[str, Any]:
    clean_requested_names = _clean_requested_player_names(requested_player_names)
    if not clean_requested_names:
        return match_data

    players = [dict(player) for player in match_data.get("players", [])]
    links = _trusted_player_name_links(players, clean_requested_names)
    enriched_players = []

    for index, player in enumerate(players):
        link = links.get(index)
        if not link:
            if not filter_unlinked:
                enriched_players.append(player)
            continue

        player["bet365_names"] = link["names"]
        player["bet365_match_confidences"] = link["confidences"]
        confidences = set(link["confidences"].values())
        player["match_confidence"] = "exact" if confidences == {"exact"} else "fuzzy"
        enriched_players.append(player)

    enriched_match = dict(match_data)
    enriched_match["players"] = enriched_players
    enriched_match["number_of_player's"] = len(enriched_players)
    return enriched_match


# --- Services ---
class SofaScoreService:
    def __init__(self, db=None):
        self._base_url = SOFASCORE_BASE_URL.rstrip("/")
        self._proxies = HTTP_PROXIES
        self.db = db
        # We will keep a pool of sessions equal to the number of proxies
        self._sessions: List[Optional[AsyncSession]] = [None] * len(self._proxies)
        self._request_counts: List[int] = [0] * len(self._proxies)
        self._warmed_up: List[bool] = [False] * len(self._proxies)
        self._session_locks = [asyncio.Lock() for _ in range(len(self._proxies))]
        self._next_proxy_index = 0
        self._proxy_index_lock = asyncio.Lock()
        
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

    async def warmup_sessions(self) -> None:
        """Create and warm active SofaScore sessions before the first UI request."""
        concurrency = min(_PROXY_WARMUP_CONCURRENCY, len(self._proxies))
        semaphore = asyncio.Semaphore(concurrency)

        async def warm_one(index: int) -> None:
            async with semaphore:
                session = await self._ensure_session(index)
                await self._warmup(session, index)

        logger.info(
            "Warming %s SofaScore proxy session(s) with concurrency %s",
            len(self._proxies),
            concurrency,
        )
        await asyncio.gather(
            *(warm_one(index) for index in range(len(self._proxies))),
            return_exceptions=True,
        )
        warmed = sum(1 for status in self._warmed_up if status)
        logger.info("SofaScore session warmup complete: %s/%s ready", warmed, len(self._proxies))
                
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

    async def _next_session_index(self) -> int:
        async with self._proxy_index_lock:
            index = self._next_proxy_index
            self._next_proxy_index = (index + 1) % len(self._proxies)
            return index

    async def _ready_session(self) -> tuple[int, AsyncSession]:
        index = await self._next_session_index()
        session = await self._ensure_session(index)
        await self._warmup(session, index)
        return index, session

    async def _get(self, path: str, **params: Any) -> Any:
        index, session = await self._ready_session()
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
                        index, session = await self._ready_session()
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
                    backoff = min(_RETRY_BACKOFF_MAX, _RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
                    backoff += random.uniform(0, _RETRY_JITTER_MAX)
                    await asyncio.sleep(backoff)
                    await self._rotate_session(session, index)
                    index, session = await self._ready_session()
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
        self._semaphore = asyncio.Semaphore(_PLAYER_REQUEST_CONCURRENCY)
        self.db = db
        
    async def _safe_api_call(self, coro, default_return: Any = None) -> Any:
        async with self._semaphore:
            try:
                return await coro
            except httpx.HTTPStatusError as e:
                return default_return
            except Exception as e:
                return default_return

    async def _fetch_player_stat_for_history(self, player_id: int, match_id: int) -> Optional[Dict[str, Any]]:
        stats_data = await self._safe_api_call(self._sofascore.get_event_player_statistics(match_id, player_id), {})
        if not stats_data or "statistics" not in stats_data:
            return None

        raw_stats = stats_data["statistics"]
        minutes = raw_stats.get("minutesPlayed", 0) or 0
        if minutes <= 0:
            return None

        return {
            "played": True,
            "statistics": {
                "totalTackle": raw_stats.get("totalTackle", 0),
                "totalShots": raw_stats.get("totalShots", 0),
                "minutesPlayed": minutes,
            },
        }

    async def _fetch_valid_player_history(self, player_id: int) -> tuple[int, List[Dict[str, Any]]]:
        valid_history: List[Dict[str, Any]] = []
        seen_event_ids: set[int] = set()
        scanned_event_count = 0

        for page in range(_PLAYER_HISTORY_MAX_PAGES):
            if len(valid_history) >= _PLAYER_HISTORY_TARGET_VALID:
                break
            if scanned_event_count >= _PLAYER_HISTORY_MAX_EVENTS:
                break

            page_data = await self._safe_api_call(self._sofascore.get_player_events(player_id, page), {})
            page_event_ids = []
            for event in page_data.get("events", []):
                event_id = event.get("id")
                if not event_id or event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                page_event_ids.append(event_id)

            if not page_event_ids:
                break

            remaining_scan_slots = _PLAYER_HISTORY_MAX_EVENTS - scanned_event_count
            page_event_ids = page_event_ids[:remaining_scan_slots]
            scanned_event_count += len(page_event_ids)

            stat_results = await asyncio.gather(
                *(self._fetch_player_stat_for_history(player_id, event_id) for event_id in page_event_ids)
            )
            for stat in stat_results:
                if stat:
                    valid_history.append(stat)
                    if len(valid_history) >= _PLAYER_HISTORY_TARGET_VALID:
                        break

        return player_id, valid_history[:_PLAYER_HISTORY_TARGET_VALID]

    async def _fetch_valid_player_history_with_timeout(self, player_id: int) -> tuple[int, List[Dict[str, Any]]]:
        try:
            return await asyncio.wait_for(
                self._fetch_valid_player_history(player_id),
                timeout=_PLAYER_HISTORY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out fetching PlayerHistory for player %s after %ss; leaving history uncached.",
                player_id,
                _PLAYER_HISTORY_TIMEOUT_SECONDS,
            )
            return player_id, []
        except Exception as exc:
            logger.warning("Failed fetching PlayerHistory for player %s: %s", player_id, exc)
            return player_id, []

    def _format_player_with_history(self, player: Dict[str, Any], h_match_stats: list) -> Dict[str, Any]:
        valid_stats = [st for st in h_match_stats if st.get("statistics") is not None]

        sum_tackles = sum(st["statistics"].get("totalTackle", 0) for st in valid_stats)
        sum_shots = sum(st["statistics"].get("totalShots", 0) for st in valid_stats)
        sum_minutes = sum(st["statistics"].get("minutesPlayed", 0) for st in valid_stats)

        if sum_minutes > 0:
            minutes_per_90 = sum_minutes / 90.0
            tackles_per_90 = round(sum_tackles / minutes_per_90, 2)
            shots_per_90 = round(sum_shots / minutes_per_90, 2)
        else:
            minutes_per_90 = tackles_per_90 = shots_per_90 = 0.0

        formatted_player = dict(player)
        formatted_player["number_of_match's"] = len(h_match_stats)
        formatted_player["matchs"] = [{
            "statistics": {
                "totalTackle_in_number_of_match's": sum_tackles,
                "totalShots_in_number_of_match's": sum_shots,
                "minutesPlayed_in_number_of_match's": sum_minutes,
                "minutesPlayed_per_90_minutes": round(minutes_per_90, 2),
                "tackles_per_90_minutes": tackles_per_90,
                "shots_per_90_minutes": shots_per_90,
            }
        }]
        return formatted_player

    async def _save_player_histories(self, newly_fetched_stats: Dict[int, list]) -> None:
        if not self.db:
            return

        histories_to_save = {
            p_id: stats
            for p_id, stats in newly_fetched_stats.items()
            if stats
        }
        if not histories_to_save:
            return

        try:
            from app.models.sofascore import PlayerHistory

            for p_id, stats in histories_to_save.items():
                await self.db.merge(PlayerHistory(player_id=str(p_id), history=stats))
            await self.db.commit()
            logger.info(f"Permanently saved history for {len(histories_to_save)} new players.")
        except IntegrityError:
            await self.db.rollback()

    async def _save_player_histories_detached(self, newly_fetched_stats: Dict[int, list]) -> None:
        histories_to_save = {
            p_id: stats
            for p_id, stats in newly_fetched_stats.items()
            if stats
        }
        if not histories_to_save:
            return

        from app.database import AsyncSessionLocal
        from app.models.sofascore import PlayerHistory

        async with AsyncSessionLocal() as db:
            try:
                for p_id, stats in histories_to_save.items():
                    await db.merge(PlayerHistory(player_id=str(p_id), history=stats))
                await db.commit()
                logger.info(f"Permanently saved history for {len(histories_to_save)} new players.")
            except IntegrityError:
                await db.rollback()
            except Exception as exc:
                await db.rollback()
                logger.warning("Failed saving PlayerHistory in background: %s", exc)

    async def _load_cached_player_histories(
        self,
        player_ids: List[int],
        player_stats_cache: Dict[int, list],
    ) -> None:
        players_to_fetch = [p_id for p_id in player_ids if p_id not in player_stats_cache]
        if not self.db or not players_to_fetch:
            return

        from app.models.sofascore import PlayerHistory

        stmt = select(PlayerHistory).where(PlayerHistory.player_id.in_([str(p) for p in players_to_fetch]))
        result = await self.db.execute(stmt)
        for history_entry in result.scalars().all():
            history = history_entry.history or []
            if history:
                player_stats_cache[int(history_entry.player_id)] = history

    async def _build_match_shell(
        self,
        match_info: Dict[str, Any],
        date: str,
        requested_player_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from datetime import datetime, timezone

        async def fetch_team_players(team_id: int):
            if not team_id:
                return team_id, {}
            return team_id, await self._safe_api_call(self._sofascore.get_team_players(team_id), {})

        team_ids = set()
        if match_info.get("homeTeam", {}).get("id"):
            team_ids.add(match_info["homeTeam"]["id"])
        if match_info.get("awayTeam", {}).get("id"):
            team_ids.add(match_info["awayTeam"]["id"])

        team_results = await asyncio.gather(*[fetch_team_players(t_id) for t_id in team_ids])
        team_data_map = {t_id: data for t_id, data in team_results}
        match_players = {}

        for t_id in [match_info.get("homeTeam", {}).get("id"), match_info.get("awayTeam", {}).get("id")]:
            if not t_id or t_id not in team_data_map:
                continue
            for player_entry in team_data_map[t_id].get("players", []):
                player = player_entry.get("player")
                if player and isinstance(player, dict) and player.get("id"):
                    raw_name = player.get("name", "Unknown")
                    clean_name = clean_display_name(raw_name)
                    match_players[player["id"]] = {
                        "player_id": player["id"],
                        "name": clean_name,
                        "matchs": [],
                    }

        clean_requested_names = _clean_requested_player_names(requested_player_names)
        if clean_requested_names:
            linked_match = attach_trusted_bet365_player_names(
                {"players": list(match_players.values())},
                clean_requested_names,
                filter_unlinked=True,
            )
            if linked_match.get("players"):
                filtered_players = {
                    player["player_id"]: player
                    for player in linked_match["players"]
                    if player.get("player_id")
                }
                logger.info(
                    "Filtered SofaScore squad %s -> %s requested player(s) for match %s.",
                    len(match_players),
                    len(filtered_players),
                    match_info.get("id"),
                )
                match_players = filtered_players
            else:
                logger.warning(
                    "Requested player filter matched no SofaScore players for match %s; using full squad.",
                    match_info.get("id"),
                )

        home_team = match_info.get("homeTeam", {}).get("name", "Unknown")
        away_team = match_info.get("awayTeam", {}).get("name", "Unknown")
        start_ts = match_info.get("startTimestamp", 0)
        start_date = (
            datetime.fromtimestamp(start_ts, timezone.utc).isoformat().replace("+00:00", "Z")
            if start_ts
            else date
        )

        return {
            "match_id": match_info["id"],
            "teams": f"{home_team} v {away_team}",
            "home": home_team,
            "away": away_team,
            "startTimestamp": start_ts,
            "date": start_date,
            "number_of_player's": len(match_players),
            "players": list(match_players.values()),
        }

    async def stream_match_progress(
        self,
        match_info: Dict[str, Any],
        date: str,
        player_stats_cache: Optional[Dict[int, list]] = None,
        bet365_event_id: Optional[str] = None,
        requested_player_names: Optional[List[str]] = None,
    ):
        player_stats_cache = player_stats_cache if player_stats_cache is not None else {}
        match_data = await self._build_match_shell(match_info, date, requested_player_names)
        if bet365_event_id:
            match_data["bet365_event_id"] = bet365_event_id

        yield {"type": "match_started", "data": match_data}

        players_by_id = {player["player_id"]: dict(player) for player in match_data["players"]}
        player_index = {
            player["player_id"]: index
            for index, player in enumerate(match_data["players"])
        }
        player_ids = list(players_by_id.keys())

        await self._load_cached_player_histories(player_ids, player_stats_cache)

        completed_player_ids = set()
        for p_id in player_ids:
            if p_id not in player_stats_cache:
                continue
            formatted_player = self._format_player_with_history(players_by_id[p_id], player_stats_cache[p_id])
            match_data["players"][player_index[p_id]] = formatted_player
            completed_player_ids.add(p_id)
            yield {
                "type": "player_done",
                "data": {
                    "match_id": match_data["match_id"],
                    "bet365_event_id": bet365_event_id,
                    "player": formatted_player,
                },
            }

        players_to_fetch = [p_id for p_id in player_ids if p_id not in completed_player_ids]
        newly_fetched_stats: Dict[int, list] = {}
        timed_out_player_ids: set[int] = set()

        async def fetch_history(p_id: int) -> tuple[int, list]:
            return await self._fetch_valid_player_history_with_timeout(p_id)

        def discard_cancelled_task(task: asyncio.Task) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Cancelled player-history task finished with error: %s", exc)

        def empty_player_result(p_id: int, status: str) -> Dict[str, Any]:
            player = dict(players_by_id[p_id])
            player["number_of_match's"] = 0
            player["matchs"] = []
            player["history_status"] = status
            return player

        if players_to_fetch:
            task_to_player = {
                asyncio.create_task(fetch_history(p_id)): p_id
                for p_id in players_to_fetch
            }
            pending_tasks = set(task_to_player.keys())
            deadline = (
                time.monotonic() + _MATCH_PLAYER_HISTORY_WAIT_SECONDS
                if _MATCH_PLAYER_HISTORY_WAIT_SECONDS > 0
                else None
            )

            while pending_tasks:
                wait_timeout = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    wait_timeout = min(1.0, remaining)

                done_tasks, pending_tasks = await asyncio.wait(
                    pending_tasks,
                    timeout=wait_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done_tasks:
                    continue

                for task in done_tasks:
                    fallback_player_id = task_to_player.get(task)
                    try:
                        p_id, stats = task.result()
                    except asyncio.CancelledError:
                        if fallback_player_id is None:
                            continue
                        p_id, stats = fallback_player_id, []
                    except Exception as exc:
                        if fallback_player_id is None:
                            continue
                        logger.warning("Failed streaming PlayerHistory for player %s: %s", fallback_player_id, exc)
                        p_id, stats = fallback_player_id, []

                    if not stats:
                        formatted_player = empty_player_result(p_id, "no_history")
                        match_data["players"][player_index[p_id]] = formatted_player
                        yield {
                            "type": "player_done",
                            "data": {
                                "match_id": match_data["match_id"],
                                "bet365_event_id": bet365_event_id,
                                "player": formatted_player,
                            },
                        }
                        continue

                    player_stats_cache[p_id] = stats
                    newly_fetched_stats[p_id] = stats

                    formatted_player = self._format_player_with_history(players_by_id[p_id], stats)
                    match_data["players"][player_index[p_id]] = formatted_player
                    yield {
                        "type": "player_done",
                        "data": {
                            "match_id": match_data["match_id"],
                            "bet365_event_id": bet365_event_id,
                            "player": formatted_player,
                        },
                    }

            if pending_tasks:
                timed_out_player_ids = {task_to_player[task] for task in pending_tasks if task in task_to_player}
                logger.warning(
                    "Stopping match %s player-history wait after %ss; %s player(s) left incomplete.",
                    match_data["match_id"],
                    _MATCH_PLAYER_HISTORY_WAIT_SECONDS,
                    len(timed_out_player_ids),
                )
                for task in pending_tasks:
                    task.cancel()
                    task.add_done_callback(discard_cancelled_task)

                for p_id in timed_out_player_ids:
                    formatted_player = empty_player_result(p_id, "timeout")
                    match_data["players"][player_index[p_id]] = formatted_player
                    yield {
                        "type": "player_done",
                        "data": {
                            "match_id": match_data["match_id"],
                            "bet365_event_id": bet365_event_id,
                            "player": formatted_player,
                        },
                    }

        match_data["players"].sort(key=lambda player: player.get("name", ""))
        cacheable = not requested_player_names and not timed_out_player_ids
        if newly_fetched_stats:
            asyncio.create_task(self._save_player_histories_detached(newly_fetched_stats))

        yield {
            "type": "match_done",
            "data": {
                "match_id": match_data["match_id"],
                "bet365_event_id": bet365_event_id,
                "match": match_data,
                "cacheable": cacheable,
            },
        }

    async def _process_match_batch(
        self,
        batch: List[Dict[str, Any]],
        date: str,
        player_stats_cache: Dict[int, list],
    ) -> List[Dict[str, Any]]:
        from datetime import datetime, timezone

        async def fetch_team_players(team_id: int):
            if not team_id:
                return team_id, {}
            return team_id, await self._safe_api_call(self._sofascore.get_team_players(team_id), {})

        team_ids = set()
        for match_info in batch:
            if match_info.get("homeTeam", {}).get("id"):
                team_ids.add(match_info["homeTeam"]["id"])
            if match_info.get("awayTeam", {}).get("id"):
                team_ids.add(match_info["awayTeam"]["id"])

        team_results = await asyncio.gather(*[fetch_team_players(t_id) for t_id in team_ids])
        team_data_map = {t_id: data for t_id, data in team_results}
        batch_results = []

        for match_info in batch:
            m_id = match_info["id"]
            match_players = {}
            home_team_id = match_info.get("homeTeam", {}).get("id")
            away_team_id = match_info.get("awayTeam", {}).get("id")

            for t_id in [home_team_id, away_team_id]:
                if not t_id or t_id not in team_data_map:
                    continue
                for player_entry in team_data_map[t_id].get("players", []):
                    player = player_entry.get("player")
                    if player and isinstance(player, dict) and player.get("id"):
                        raw_name = player.get("name", "Unknown")
                        clean_name = clean_display_name(raw_name)
                        match_players[player["id"]] = {"player_id": player["id"], "name": clean_name}

            home_team = match_info.get("homeTeam", {}).get("name", "Unknown")
            away_team = match_info.get("awayTeam", {}).get("name", "Unknown")
            start_ts = match_info.get("startTimestamp", 0)
            start_date = (
                datetime.fromtimestamp(start_ts, timezone.utc).isoformat().replace("+00:00", "Z")
                if start_ts
                else date
            )
            batch_results.append({
                "match_id": m_id,
                "teams": f"{home_team} v {away_team}",
                "home": home_team,
                "away": away_team,
                "startTimestamp": start_ts,
                "date": start_date,
                "players": list(match_players.values()),
            })

        unique_players = {p["player_id"]: p for m in batch_results for p in m["players"]}
        players_to_fetch = [p_id for p_id in unique_players if p_id not in player_stats_cache]

        if self.db and players_to_fetch:
            from app.models.sofascore import PlayerHistory

            stmt = select(PlayerHistory).where(PlayerHistory.player_id.in_([str(p) for p in players_to_fetch]))
            result = await self.db.execute(stmt)
            for history_entry in result.scalars().all():
                history = history_entry.history or []
                if history:
                    player_stats_cache[int(history_entry.player_id)] = history

        players_to_fetch = [p_id for p_id in unique_players if p_id not in player_stats_cache]
        if players_to_fetch:
            history_results = await asyncio.gather(
                *(self._fetch_valid_player_history_with_timeout(p_id) for p_id in players_to_fetch)
            )
            newly_fetched_stats = dict(history_results)

            if self.db:
                try:
                    from app.models.sofascore import PlayerHistory

                    histories_to_save = {
                        p_id: stats
                        for p_id, stats in newly_fetched_stats.items()
                        if stats
                    }
                    for p_id, stats in histories_to_save.items():
                        await self.db.merge(PlayerHistory(player_id=str(p_id), history=stats))
                    await self.db.commit()
                    logger.info(f"Permanently saved history for {len(histories_to_save)} new players.")
                except IntegrityError:
                    await self.db.rollback()

            player_stats_cache.update(newly_fetched_stats)

        for m in batch_results:
            m["number_of_player's"] = len(m["players"])
            for p in m["players"]:
                h_match_stats = player_stats_cache.get(p["player_id"], [])
                valid_stats = [st for st in h_match_stats if st.get("statistics") is not None]

                sum_tackles = sum(st["statistics"].get("totalTackle", 0) for st in valid_stats)
                sum_shots = sum(st["statistics"].get("totalShots", 0) for st in valid_stats)
                sum_minutes = sum(st["statistics"].get("minutesPlayed", 0) for st in valid_stats)

                if sum_minutes > 0:
                    minutes_per_90 = sum_minutes / 90.0
                    tackles_per_90 = round(sum_tackles / minutes_per_90, 2)
                    shots_per_90 = round(sum_shots / minutes_per_90, 2)
                else:
                    minutes_per_90 = tackles_per_90 = shots_per_90 = 0.0

                p["number_of_match's"] = len(h_match_stats)
                p["matchs"] = [{
                    "statistics": {
                        "totalTackle_in_number_of_match's": sum_tackles,
                        "totalShots_in_number_of_match's": sum_shots,
                        "minutesPlayed_in_number_of_match's": sum_minutes,
                        "minutesPlayed_per_90_minutes": round(minutes_per_90, 2),
                        "tackles_per_90_minutes": tackles_per_90,
                        "shots_per_90_minutes": shots_per_90,
                    }
                }]

        batch_results.sort(key=lambda m: (m.get("startTimestamp") or 0, m.get("teams", "")))
        return batch_results
                
    async def run_pipeline(self, tournament_id: int, date: str) -> Dict[str, Any]:
        logger.info(f"Starting pipeline for tournament {tournament_id} on {date}")
        matches = await self._safe_api_call(self._sofascore.get_unique_tournament_scheduled_events(tournament_id, date), [])

        from datetime import datetime, timezone

        strict_matches = []
        for m in matches:
            ts = m.get("startTimestamp")
            if ts:
                m_date = datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')
                if m_date == date:
                    strict_matches.append(m)
                    
        valid_matches = [m for m in strict_matches if m.get("id") and m.get("status", {}).get("type") in ["notstarted", "delayed"]]
        valid_matches.sort(key=lambda m: m.get("startTimestamp", 0))

        if not valid_matches:
            return {"date": date, "matches": []}

        matches_result = []
        player_stats_cache: Dict[int, list] = {}
        batch_size = max(1, _MATCH_CALCULATION_BATCH_SIZE)
        total_batches = (len(valid_matches) + batch_size - 1) // batch_size

        async def fetch_team_players(team_id: int):
            if not team_id:
                return team_id, {}
            return team_id, await self._safe_api_call(self._sofascore.get_team_players(team_id), {})

        for batch_start in range(0, len(valid_matches), batch_size):
            batch = valid_matches[batch_start:batch_start + batch_size]
            batch_number = (batch_start // batch_size) + 1
            logger.info(
                "Processing SofaScore match batch %s/%s for %s (%s match(es))",
                batch_number,
                total_batches,
                date,
                len(batch),
            )

            team_ids = set()
            for match_info in batch:
                if match_info.get("homeTeam", {}).get("id"):
                    team_ids.add(match_info["homeTeam"]["id"])
                if match_info.get("awayTeam", {}).get("id"):
                    team_ids.add(match_info["awayTeam"]["id"])

            team_results = await asyncio.gather(*[fetch_team_players(t_id) for t_id in team_ids])
            team_data_map = {t_id: data for t_id, data in team_results}
            batch_results = []

            for match_info in batch:
                m_id = match_info["id"]
                match_players = {}
                home_team_id = match_info.get("homeTeam", {}).get("id")
                away_team_id = match_info.get("awayTeam", {}).get("id")

                for t_id in [home_team_id, away_team_id]:
                    if not t_id or t_id not in team_data_map:
                        continue
                    for player_entry in team_data_map[t_id].get("players", []):
                        player = player_entry.get("player")
                        if player and isinstance(player, dict) and player.get("id"):
                            raw_name = player.get("name", "Unknown")
                            clean_name = clean_display_name(raw_name)
                            match_players[player["id"]] = {"player_id": player["id"], "name": clean_name}

                home_team = match_info.get("homeTeam", {}).get("name", "Unknown")
                away_team = match_info.get("awayTeam", {}).get("name", "Unknown")
                start_ts = match_info.get("startTimestamp", 0)
                start_date = (
                    datetime.fromtimestamp(start_ts, timezone.utc).isoformat().replace("+00:00", "Z")
                    if start_ts
                    else date
                )
                batch_results.append({
                    "match_id": m_id,
                    "teams": f"{home_team} v {away_team}",
                    "home": home_team,
                    "away": away_team,
                    "startTimestamp": start_ts,
                    "date": start_date,
                    "players": list(match_players.values()),
                })

            unique_players = {p["player_id"]: p for m in batch_results for p in m["players"]}
            players_to_fetch = [p_id for p_id in unique_players if p_id not in player_stats_cache]

            if self.db and players_to_fetch:
                from app.models.sofascore import PlayerHistory

                stmt = select(PlayerHistory).where(PlayerHistory.player_id.in_([str(p) for p in players_to_fetch]))
                result = await self.db.execute(stmt)
                for history_entry in result.scalars().all():
                    history = history_entry.history or []
                    if history:
                        player_stats_cache[int(history_entry.player_id)] = history

            players_to_fetch = [p_id for p_id in unique_players if p_id not in player_stats_cache]
            if players_to_fetch:
                history_results = await asyncio.gather(
                    *(self._fetch_valid_player_history_with_timeout(p_id) for p_id in players_to_fetch)
                )
                newly_fetched_stats = dict(history_results)

                if self.db:
                    try:
                        from app.models.sofascore import PlayerHistory

                        histories_to_save = {
                            p_id: stats
                            for p_id, stats in newly_fetched_stats.items()
                            if stats
                        }
                        for p_id, stats in histories_to_save.items():
                            await self.db.merge(PlayerHistory(player_id=str(p_id), history=stats))
                        await self.db.commit()
                        logger.info(f"Permanently saved history for {len(histories_to_save)} new players.")
                    except IntegrityError:
                        await self.db.rollback()

                player_stats_cache.update(newly_fetched_stats)

            for m in batch_results:
                m["number_of_player's"] = len(m["players"])
                for p in m["players"]:
                    p_id = p["player_id"]
                    h_match_stats = player_stats_cache.get(p_id, [])
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

            matches_result.extend(batch_results)

        matches_result.sort(key=lambda m: (m.get("startTimestamp") or 0, m.get("teams", "")))
        return {"date": date, "matches": matches_result}

    async def run_pipeline_stream(self, tournament_id: int, date: str):
        """
        Async generator — processes each match independently and yields its data
        as soon as it is ready, enabling progressive frontend rendering.
        """
        logger.info(f"[STREAM] Starting streaming pipeline for {date}")
        from datetime import datetime, timezone

        # 1. Discover matches
        matches = await self._safe_api_call(
            self._sofascore.get_unique_tournament_scheduled_events(tournament_id, date), []
        )
        valid_matches = []
        for m in matches:
            ts = m.get("startTimestamp")
            if ts:
                m_date = datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')
                if m_date == date and m.get("id") and m.get("status", {}).get("type") in ["notstarted", "delayed"]:
                    valid_matches.append(m)

        if not valid_matches:
            return

        # Sort chronologically so the stream populates the UI top-to-bottom
        valid_matches.sort(key=lambda m: m.get("startTimestamp", 0))

        player_stats_cache: Dict[int, list] = {}
        batch_size = max(1, _MATCH_CALCULATION_BATCH_SIZE)
        total_batches = (len(valid_matches) + batch_size - 1) // batch_size

        for batch_start in range(0, len(valid_matches), batch_size):
            batch = valid_matches[batch_start:batch_start + batch_size]
            batch_number = (batch_start // batch_size) + 1
            logger.info(
                "[STREAM] Processing SofaScore match batch %s/%s for %s (%s match(es))",
                batch_number,
                total_batches,
                date,
                len(batch),
            )
            batch_results = await self._process_match_batch(batch, date, player_stats_cache)
            for match_data in batch_results:
                logger.info(f"[STREAM] Yielding match {match_data.get('match_id')}: {match_data.get('teams')}")
                yield match_data

    async def sync_finished_matches_for_date(self, tournament_id: int, date: str):
        if not self.db:
            return
            
        from app.models.sofascore import Bet365SofascoreMapping, SofascoreMatchCache, SyncedMatch, PlayerHistory
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
                return p_id, await self._fetch_player_stat_for_history(p_id, m_id)
                
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
                    # Sliding window: remove oldest game, append new one, keep max 30
                    current_history = list(history_entry.history)
                    current_history.append(stats)
                    if len(current_history) > _PLAYER_HISTORY_TARGET_VALID:
                        current_history = current_history[-_PLAYER_HISTORY_TARGET_VALID:]
                    history_entry.history = current_history
                    self.db.add(history_entry)
                else:
                    self.db.add(PlayerHistory(player_id=str(p_id), history=[stats]))
            
            # Mark match as synced
            self.db.add(SyncedMatch(match_id=str(m_id)))
            mapping_stmt = select(Bet365SofascoreMapping).where(Bet365SofascoreMapping.sofascore_event_id == str(m_id))
            mapping_result = await self.db.execute(mapping_stmt)
            for mapping in mapping_result.scalars().all():
                mapping.sync_status = "synced"
                self.db.add(mapping)
            await self.db.commit()
            logger.info(f"Successfully synced match {m_id} to persistent database.")
            
            # Invalidate today's sofascore_cache so next request recalculates
            # fresh shots_per_90 / tackles_per_90 from updated player_history
            from app.models.sofascore import SofascoreCache
            cache_stmt = select(SofascoreCache).where(SofascoreCache.date == date)
            cache_result = await self.db.execute(cache_stmt)
            old_cache = cache_result.scalars().first()
            if old_cache:
                await self.db.delete(old_cache)
                await self.db.commit()
                logger.info(f"Invalidated sofascore_cache for {date} — fresh stats will be recalculated on next request.")
            match_cache = await self.db.get(SofascoreMatchCache, str(m_id))
            if match_cache:
                await self.db.delete(match_cache)

            now_ts = int(time.time())
            future_cache_stmt = select(SofascoreMatchCache).where(SofascoreMatchCache.start_timestamp > now_ts)
            future_cache_result = await self.db.execute(future_cache_stmt)
            for cache in future_cache_result.scalars().all():
                await self.db.delete(cache)
            await self.db.commit()
            logger.info(f"Invalidated prediction caches after syncing match {m_id}.")

    async def sync_mapped_finished_matches(self) -> None:
        if not self.db:
            return

        from app.models.sofascore import Bet365SofascoreMapping

        now_ts = int(time.time())
        stmt = select(Bet365SofascoreMapping).where(
            Bet365SofascoreMapping.sync_status == "pending",
            Bet365SofascoreMapping.start_timestamp <= now_ts,
        )
        result = await self.db.execute(stmt)
        mappings = result.scalars().all()
        checked_dates = sorted({mapping.date for mapping in mappings if mapping.date})

        for date in checked_dates:
            await self.sync_finished_matches_for_date(16, date)


# Global service instance
sofascore_service = SofaScoreService()
_extraction_locks: Dict[str, asyncio.Lock] = {}
_extraction_locks_guard = asyncio.Lock()


async def _get_extraction_lock(date: str) -> asyncio.Lock:
    async with _extraction_locks_guard:
        lock = _extraction_locks.get(date)
        if lock is None:
            lock = asyncio.Lock()
            _extraction_locks[date] = lock
        return lock

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

    extraction_lock = await _get_extraction_lock(date)
    async with extraction_lock:
        # Another request may have filled the cache while we waited.
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
