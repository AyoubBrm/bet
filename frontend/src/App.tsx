import { useState, useEffect, useMemo } from "react";
import { Header } from "./components/layout/Header";
import { MatchCard } from "./components/match/MatchCard";
import { Skeleton } from "./components/ui/Skeleton";
import type { ApiResponse, MatchEntry, MatchJobStatus, SofascoreMatch, SofascoreResponse } from "./types/api";
import { normalizeName } from "./lib/string-matching";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8002";

function getMatchTime(entry: MatchEntry): number {
  const timestamp = Date.parse(entry.match.date);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function sortMatchEntries(matches: MatchEntry[]): MatchEntry[] {
  return [...matches].sort((a, b) => {
    const timeDiff = getMatchTime(a) - getMatchTime(b);
    if (timeDiff !== 0) return timeDiff;
    return a.match.id - b.match.id;
  });
}

function getSofascoreTime(match: SofascoreMatch): number {
  if (match.startTimestamp) return match.startTimestamp * 1000;
  const timestamp = Date.parse(match.date ?? "");
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function sortSofascoreMatches(matches: SofascoreMatch[]): SofascoreMatch[] {
  return [...matches].sort((a, b) => {
    const timeDiff = getSofascoreTime(a) - getSofascoreTime(b);
    if (timeDiff !== 0) return timeDiff;
    return a.teams.localeCompare(b.teams);
  });
}

function buildSofascoreResponse(matches: SofascoreMatch[]): SofascoreResponse {
  const sortedMatches = sortSofascoreMatches(matches);
  return {
    match_count: sortedMatches.length,
    total_number_of_player_s: sortedMatches.reduce(
      (sum, match) => sum + (match["number_of_player's"] ?? match.number_of_player_s ?? 0),
      0
    ),
    matches: sortedMatches,
  };
}

function normalizeTeamName(name: string): string {
  return normalizeName(name)
    .replace(/\b(fc|cf|sc|club)\b/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function getSofascoreTeams(match: SofascoreMatch): [string, string] {
  if (match.home && match.away) {
    return [match.home, match.away];
  }
  const parts = match.teams.split(" v ");
  return [parts[0] ?? "", parts[1] ?? ""];
}

function sameMatchDay(entry: MatchEntry, match: SofascoreMatch): boolean {
  const oddsDate = entry.match.date.split("T")[0];
  const sofaDate = match.startTimestamp
    ? new Date(match.startTimestamp * 1000).toISOString().split("T")[0]
    : match.date?.split("T")[0];
  return !sofaDate || oddsDate === sofaDate;
}

function getKickoffDistance(entry: MatchEntry, match: SofascoreMatch): number {
  const oddsTime = getMatchTime(entry);
  const sofaTime = getSofascoreTime(match);
  if (!oddsTime || !sofaTime) return Number.MAX_SAFE_INTEGER;
  return Math.abs(oddsTime - sofaTime);
}

function findSofascoreMatch(
  entry: MatchEntry,
  sofascoreData: SofascoreResponse | null
): SofascoreMatch | null {
  if (!sofascoreData) return null;

  const directMatch = sofascoreData.matches.find(
    (match) => String(match.bet365_event_id ?? "") === String(entry.match.id)
  );
  if (directMatch) return directMatch;

  // Bet365 event ids and SofaScore event ids are unrelated. Match by teams + kickoff.
  const home = normalizeTeamName(entry.match.home);
  const away = normalizeTeamName(entry.match.away);
  const candidates: SofascoreMatch[] = [];

  for (const match of sofascoreData.matches) {
    const [sofaHomeRaw, sofaAwayRaw] = getSofascoreTeams(match);
    const sofaHome = normalizeTeamName(sofaHomeRaw);
    const sofaAway = normalizeTeamName(sofaAwayRaw);
    const sameTeams =
      (home === sofaHome && away === sofaAway) ||
      (home === sofaAway && away === sofaHome);

    if (!sameTeams) continue;
    candidates.push(match);
  }

  if (candidates.length === 0) return null;

  candidates.sort((a, b) => {
    const dayDiff = Number(!sameMatchDay(entry, a)) - Number(!sameMatchDay(entry, b));
    if (dayDiff !== 0) return dayDiff;

    const timeDiff = getKickoffDistance(entry, a) - getKickoffDistance(entry, b);
    if (timeDiff !== 0) return timeDiff;

    return a.teams.localeCompare(b.teams);
  });

  return candidates[0];
}

function App() {
  const [data, setData] = useState<ApiResponse | null>(null);
  const [sofascoreData, setSofascoreData] = useState<SofascoreResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [aliasVersion, setAliasVersion] = useState(0);
  const [matchStatuses, setMatchStatuses] = useState<Record<number, MatchJobStatus>>({});

  const [targetEndpoint, setTargetEndpoint] = useState<string | null>(null);

  useEffect(() => {
    let intervalId: any;
    const controller = new AbortController();
    let cancelled = false;
    let streamActive = false;

    const streamSofascoreMatches = async (
      sortedMatches: MatchEntry[],
      matchesById: Map<number, SofascoreMatch>
    ): Promise<void> => {
      const response = await fetch(`${API_BASE_URL}/api/extraction/stream/matches`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          matches: sortedMatches.map((entry) => ({
            id: entry.match.id,
            home: entry.match.home,
            away: entry.match.away,
            date: entry.match.date,
            players: Array.from(
              new Set((entry.player_shots ?? entry.player_tackles ?? []).map((player) => player.player).filter(Boolean))
            ),
          })),
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Failed to stream SofaScore match data: ${response.statusText}`);
      }

      if (!response.body) {
        throw new Error("SofaScore match stream did not return a readable body.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const handleEvent = (rawEvent: string) => {
        const data = rawEvent
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n")
          .trim();

        if (!data) return;

        const payload = JSON.parse(data);
        if (payload.done) return;

        const publishMatches = () => {
          setSofascoreData(buildSofascoreResponse([...matchesById.values()]));
        };

        const findMatchedEntry = (matchPayload: Partial<SofascoreMatch>) => {
          if (matchPayload.bet365_event_id) {
            return sortedMatches.find((entry) => String(entry.match.id) === String(matchPayload.bet365_event_id));
          }
          if (!matchPayload.match_id || !matchPayload.teams) {
            return undefined;
          }
          return sortedMatches.find((entry) => findSofascoreMatch(
                entry,
                buildSofascoreResponse([matchPayload as SofascoreMatch])
              ));
        };

        const markMatchStatus = (matchPayload: Partial<SofascoreMatch>, status: MatchJobStatus) => {
          const matchedEntry = findMatchedEntry(matchPayload);
          if (matchedEntry) {
            setMatchStatuses((current) => ({
              ...current,
              [matchedEntry.match.id]: status,
            }));
          }
        };

        const upsertMatch = (matchPayload: SofascoreMatch) => {
          if (!matchPayload?.match_id) return;
          const existing = matchesById.get(matchPayload.match_id);
          matchesById.set(matchPayload.match_id, {
            ...existing,
            ...matchPayload,
            players: matchPayload.players ?? existing?.players ?? [],
          });
          publishMatches();
        };

        if (payload.type === "status") {
          if (payload.bet365_event_id) {
            setMatchStatuses((current) => ({
              ...current,
              [Number(payload.bet365_event_id)]: payload.status,
            }));
          }
          return;
        }

        if (payload.type === "match_started") {
          upsertMatch(payload.data);
          markMatchStatus(payload.data, "calculating");
          return;
        }

        if (payload.type === "player_done") {
          const playerPayload = payload.data;
          const matchId = Number(playerPayload?.match_id);
          const player = playerPayload?.player;
          if (!matchId || !player) return;

          const existing = matchesById.get(matchId) ?? {
            match_id: matchId,
            bet365_event_id: playerPayload.bet365_event_id,
            teams: "",
            players: [],
          };

          const playerExists = existing.players.some((currentPlayer) => currentPlayer.player_id === player.player_id);
          const updatedPlayers = playerExists
            ? existing.players.map((currentPlayer) =>
                currentPlayer.player_id === player.player_id ? player : currentPlayer
              )
            : [...existing.players, player];

          matchesById.set(matchId, {
            ...existing,
            bet365_event_id: playerPayload.bet365_event_id ?? existing.bet365_event_id,
            players: updatedPlayers,
          });
          markMatchStatus(matchesById.get(matchId) ?? existing, "calculating");
          publishMatches();
          return;
        }

        if (payload.type === "match_done") {
          const donePayload = payload.data;
          if (donePayload?.match) {
            upsertMatch(donePayload.match);
            markMatchStatus(donePayload.match, "done");
          } else {
            markMatchStatus(donePayload, "done");
          }
          return;
        }

        const matchPayload = payload.type === "match" ? payload.data : payload;
        if (!matchPayload?.match_id) return;

        upsertMatch(matchPayload);
        markMatchStatus(matchPayload, "done");
      };

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done }).replace(/\r\n/g, "\n");

        let eventEnd = buffer.indexOf("\n\n");
        while (eventEnd !== -1) {
          const rawEvent = buffer.slice(0, eventEnd);
          buffer = buffer.slice(eventEnd + 2);
          handleEvent(rawEvent);
          eventEnd = buffer.indexOf("\n\n");
        }

        if (done) break;
      }

      if (buffer.trim()) {
        handleEvent(buffer);
      }
    };

    const fetchData = async (isInitial: boolean) => {
      if (!targetEndpoint) return;
      try {
        if (isInitial) setIsLoading(true);
        setError(null);
        
        const response = await fetch(targetEndpoint, {
          signal: controller.signal,
        });
        
        if (!response.ok) {
          throw new Error(`Failed to fetch data: ${response.statusText}`);
        }
        
        const result = await response.json();
        const sortedResult: ApiResponse = {
          ...result,
          matches: sortMatchEntries(result.matches ?? []),
        };
        setData(sortedResult);
        if (isInitial) {
          setMatchStatuses(
            Object.fromEntries(
              sortedResult.matches.map((entry) => [entry.match.id, "queued" as MatchJobStatus])
            )
          );
        }
        
        // Set loading false immediately so the UI renders the Bet365 data!
        if (isInitial) setIsLoading(false);
        
        // Stream one global sorted match queue so finished matches render immediately.
        if (isInitial && sortedResult.matches && sortedResult.matches.length > 0) {
          // Reset sofascore state so stale data doesn't linger
          setSofascoreData(buildSofascoreResponse([]));

          const matchesById = new Map<number, SofascoreMatch>();
          if (cancelled) return;
          streamActive = true;
          try {
            await streamSofascoreMatches(sortedResult.matches, matchesById);
          } finally {
            streamActive = false;
          }
        }
      } catch (err: any) {
        if (err?.name === "AbortError") return;
        setError(err.message || "An unexpected error occurred while fetching data.");
        if (isInitial) setIsLoading(false);
      }
    };

    if (targetEndpoint) {
      // Fetch immediately with loading state
      fetchData(true);
      
      // Set up silent background polling every 5 seconds
      intervalId = setInterval(() => {
        if (!streamActive) {
          fetchData(false);
        }
      }, 5000);
    } else {
      setIsLoading(false);
    }
    
    return () => {
      cancelled = true;
      controller.abort();
      if (intervalId) clearInterval(intervalId);
    };
  }, [targetEndpoint]);

  // Filter matches based on search query (teams or players inside the match)
  const filteredMatches = useMemo(() => data?.matches.filter((entry: MatchEntry) => {
    const q = searchQuery.toLowerCase();
    
    // Check match teams
    if (entry.match.home.toLowerCase().includes(q) || 
        entry.match.away.toLowerCase().includes(q)) {
      return true;
    }
    
    // Check players inside the match
    const players = entry.player_shots || entry.player_tackles || [];
    if (players.length > 0) {
      return players.some(p => p.player.toLowerCase().includes(q));
    }
    
    return false;
  }), [data, searchQuery]);

  return (
    <div className="min-h-screen bg-background text-text">
      <Header onSearch={setSearchQuery} onAliasChange={() => setAliasVersion(v => v + 1)} />
      
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 animate-fade-in">
        <div className="mb-8 flex flex-col gap-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-3xl font-bold tracking-tight mb-2">Upcoming Matches</h2>
              <p className="text-text-muted">Player predictions and analytics.</p>
            </div>
            {data && !isLoading && (
              <div className="hidden sm:flex items-center gap-2 text-sm text-text-muted bg-surface/50 px-4 py-2 rounded-full border border-border">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                {data.num_of_matches} Matches tracked
              </div>
            )}
          </div>

          <div className="bg-surface/50 p-6 rounded-xl border border-border">
            <h3 className="text-lg font-bold mb-4 text-text">Select Market</h3>
            <div className="flex flex-col sm:flex-row gap-4">
              <button 
                onClick={() => setTargetEndpoint(`${API_BASE_URL}/upcoming/player_shots`)}
                disabled={isLoading}
                className={`px-8 py-3 rounded-lg font-medium disabled:opacity-50 transition-all flex items-center justify-center flex-1 ${
                  targetEndpoint?.includes('player_shots')
                    ? 'bg-primary text-white border-transparent'
                    : 'bg-surface hover:bg-surface-hover text-text border border-border'
                }`}
              >
                {isLoading && targetEndpoint?.includes("player_shots") ? (
                  <span className="flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin"></span>
                    Fetching Shots...
                  </span>
                ) : "Player Shots Odds"}
              </button>

              <button 
                onClick={() => setTargetEndpoint(`${API_BASE_URL}/upcoming/player_tackles`)}
                disabled={isLoading}
                className={`px-8 py-3 rounded-lg font-medium disabled:opacity-50 transition-all flex items-center justify-center flex-1 ${
                  targetEndpoint?.includes('player_tackles')
                    ? 'bg-primary text-white border-transparent'
                    : 'bg-surface hover:bg-surface-hover text-text border border-border'
                }`}
              >
                {isLoading && targetEndpoint?.includes("player_tackles") ? (
                  <span className="flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
                    Fetching Tackles...
                  </span>
                ) : "Player Tackles Odds"}
              </button>
            </div>
          </div>
        </div>

        {isLoading && (
          <div className="space-y-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="glass-card rounded-xl p-6 h-32 flex flex-col justify-between border border-border">
                <div className="flex justify-between w-full">
                  <div className="space-y-3 w-1/3">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-6 w-full" />
                  </div>
                  <Skeleton className="h-10 w-24 rounded-lg" />
                </div>
              </div>
            ))}
          </div>
        )}

        {error && !isLoading && (
          <div className="glass-card rounded-xl p-8 text-center border-danger/20 border">
            <h3 className="text-xl font-bold text-danger mb-2">Error Loading Data</h3>
            <p className="text-text-muted mb-4">{error}</p>
            <button 
              onClick={() => window.location.reload()}
              className="px-6 py-2 bg-surface hover:bg-surface-hover text-text font-medium rounded-lg border border-border transition-colors"
            >
              Try Again
            </button>
          </div>
        )}

        {data && !isLoading && filteredMatches && filteredMatches.length > 0 && (
          <div className="space-y-6">
            {filteredMatches.map((entry) => (
              <MatchCard 
                key={entry.match.id} 
                entry={entry} 
                searchQuery={searchQuery}
                sofascoreMatch={findSofascoreMatch(entry, sofascoreData)}
                status={matchStatuses[entry.match.id]}
                marketType={targetEndpoint?.includes('player_shots') ? 'shots' : 'tackles'}
                aliasVersion={aliasVersion}
              />
            ))}
          </div>
        )}

        {data && !isLoading && filteredMatches && filteredMatches.length === 0 && (
          <div className="glass-card rounded-xl p-12 text-center border border-border flex flex-col items-center justify-center">
            <p className="text-xl font-medium text-text-muted mb-2">No matches found</p>
            <p className="text-text-muted/60 text-sm">Try adjusting your search terms.</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
