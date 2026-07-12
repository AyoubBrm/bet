import re

with open(r'c:\Users\bmayo\OneDrive\Desktop\SOFA\frontend\src\App.tsx', 'r', encoding='utf-8') as f:
    original = f.read()

imports_replacement = """import { useState, useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Header } from "./components/layout/Header";
import { MatchCard } from "./components/match/MatchCard";
import { Skeleton } from "./components/ui/Skeleton";
import { MarketSelector, type MarketKey } from "./components/market/MarketSelector";
import type { ApiResponse, MatchEntry, MatchJobStatus, Player, SofascoreMatch, SofascoreResponse } from "./types/api";
import { normalizeName } from "./lib/string-matching";
import { isSofascorePlayerForBet365 } from "./lib/sofascore-player-match";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8002";

interface StreamMatchTarget {
  entry: MatchEntry;
  playerNames: string[];
}"""

original = re.sub(r'import \{ useState, useEffect, useMemo \} from "react";.*?interface StreamMatchTarget \{\n  entry: MatchEntry;\n  playerNames: string\[\];\n\}', imports_replacement, original, flags=re.DOTALL)

app_replacement = """function App() {
  const [activeMarket, setActiveMarket] = useState<MarketKey | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [aliasVersion, setAliasVersion] = useState(0);

  // SofaScore global cache
  const [sofascoreData, setSofascoreData] = useState<SofascoreResponse>({ match_count: 0, total_number_of_player_s: 0, matches: [] });
  const [matchStatuses, setMatchStatuses] = useState<Record<number, MatchJobStatus>>({});

  // Use React Query for the Odds fetching
  const { data, isLoading, error } = useQuery<ApiResponse, Error>({
    queryKey: ['odds', activeMarket],
    queryFn: async () => {
      if (!activeMarket) throw new Error("No market selected");
      const response = await fetch(getMarketEndpoint(activeMarket));
      if (!response.ok) {
        throw new Error(`Failed to fetch data: ${response.statusText}`);
      }
      const result = await response.json();
      return {
        ...result,
        matches: sortMatchEntries(result.matches ?? []),
      } as ApiResponse;
    },
    enabled: activeMarket !== null,
    refetchInterval: 5000,
    staleTime: 4000,
    gcTime: 300000,
  });

  const selectMarket = (market: MarketKey) => {
    setActiveMarket(market);
  };

  const sofascoreDataRef = useRef(sofascoreData);
  sofascoreDataRef.current = sofascoreData;

  const matchStatusesRef = useRef(matchStatuses);
  matchStatusesRef.current = matchStatuses;

  const updateMatchStatuses = (updater: (current: Record<number, MatchJobStatus>) => Record<number, MatchJobStatus>) => {
    setMatchStatuses(updater);
  };

  const isStreamingRef = useRef(false);

  // SSE Streaming Effect
  useEffect(() => {
    if (!data?.matches || data.matches.length === 0) return;
    if (isStreamingRef.current) return;

    // Initialize statuses for new matches
    setMatchStatuses(prev => {
      const next = { ...prev };
      let changed = false;
      for (const entry of data.matches) {
        if (!next[entry.match.id]) {
          next[entry.match.id] = "queued";
          changed = true;
        }
      }
      return changed ? next : prev;
    });

    const streamTargets: StreamMatchTarget[] = data.matches.flatMap((entry) => {
      const status = matchStatusesRef.current[entry.match.id];
      if (status === "failed") return [];

      const playerNames = getMissingSofascorePlayerNames(entry, sofascoreDataRef.current);
      if (playerNames.length === 0) return [];

      return [{ entry, playerNames }];
    });

    if (streamTargets.length === 0) return;

    isStreamingRef.current = true;
    const controller = new AbortController();

    const streamMatches = async () => {
      try {
        const matchesById = new Map<number, SofascoreMatch>(
          sofascoreDataRef.current.matches.map((match) => [match.match_id, match])
        );

        const response = await fetch(`${API_BASE_URL}/api/extraction/stream/matches`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            matches: streamTargets.map(({ entry, playerNames }) => ({
              id: entry.match.id,
              home: entry.match.home,
              away: entry.match.away,
              date: entry.match.date,
              players: playerNames,
            })),
          }),
          signal: controller.signal,
        });

        if (!response.ok) throw new Error("Failed to stream SofaScore match data");
        if (!response.body) throw new Error("No readable body");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const handleEvent = (rawEvent: string) => {
          const evtData = rawEvent.split("\\n").filter((l: string) => l.startsWith("data:")).map((l: string) => l.slice(5).trimStart()).join("\\n").trim();
          if (!evtData) return;

          const payload = JSON.parse(evtData);
          if (payload.done) return;

          const publishMatches = () => {
            const nextSofascoreData = buildSofascoreResponse([...matchesById.values()]);
            setSofascoreData(nextSofascoreData);
          };

          const findMatchedEntry = (matchPayload: Partial<SofascoreMatch>) => {
            if (matchPayload.bet365_event_id) {
              return streamTargets.find(({ entry }) => String(entry.match.id) === String(matchPayload.bet365_event_id))?.entry;
            }
            if (!matchPayload.match_id || !matchPayload.teams) return undefined;
            return streamTargets.find(({ entry }) => findSofascoreMatch(entry, buildSofascoreResponse([matchPayload as SofascoreMatch])))?.entry;
          };

          const markMatchStatus = (matchPayload: Partial<SofascoreMatch>, status: MatchJobStatus) => {
            const matchedEntry = findMatchedEntry(matchPayload);
            if (matchedEntry) {
              updateMatchStatuses((current) => ({ ...current, [matchedEntry.match.id]: status }));
            }
          };

          const upsertMatch = (matchPayload: SofascoreMatch) => {
            if (!matchPayload?.match_id) return;
            const existing = matchesById.get(matchPayload.match_id);
            matchesById.set(matchPayload.match_id, {
              ...existing,
              ...matchPayload,
              players: mergeSofascorePlayers(existing?.players ?? [], matchPayload.players ?? []),
            });
            publishMatches();
          };

          if (payload.type === "status") {
            if (payload.bet365_event_id) {
              updateMatchStatuses((current) => ({ ...current, [Number(payload.bet365_event_id)]: payload.status }));
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

            const existing = matchesById.get(matchId) ?? { match_id: matchId, bet365_event_id: playerPayload.bet365_event_id, teams: "", players: [] };
            matchesById.set(matchId, { ...existing, bet365_event_id: playerPayload.bet365_event_id ?? existing.bet365_event_id, players: mergeSofascorePlayers(existing.players, [player]) });
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
          buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done }).replace(/\\r\\n/g, "\\n");
          let eventEnd = buffer.indexOf("\\n\\n");
          while (eventEnd !== -1) {
            handleEvent(buffer.slice(0, eventEnd));
            buffer = buffer.slice(eventEnd + 2);
            eventEnd = buffer.indexOf("\\n\\n");
          }
          if (done) break;
        }
        if (buffer.trim()) handleEvent(buffer);
      } catch (err: any) {
        if (err?.name !== "AbortError") console.error("Stream error:", err);
      } finally {
        isStreamingRef.current = false;
      }
    };

    streamMatches();

    return () => {
      controller.abort();
      isStreamingRef.current = false;
    };
  }, [data?.matches]);

  const filteredMatches = useMemo(() => data?.matches.filter((entry: MatchEntry) => {
    const q = searchQuery.toLowerCase();
    if (entry.match.home.toLowerCase().includes(q) || entry.match.away.toLowerCase().includes(q)) return true;
    const players = entry.player_shots || entry.player_tackles || [];
    if (players.length > 0) return players.some(p => p.player.toLowerCase().includes(q));
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
                {data.num_of_matches ?? data.matches.length} Matches tracked
              </div>
            )}
          </div>

          <MarketSelector
            activeMarket={activeMarket}
            isLoading={isLoading}
            shotsReady={true}
            tacklesReady={true}
            onSelectMarket={selectMarket}
          />
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
            <p className="text-text-muted mb-4">{String(error)}</p>
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
                marketType={activeMarket === 'shots' ? 'shots' : 'tackles'}
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

export default App;"""

original = re.sub(r'function App\(\) \{.*', app_replacement, original, flags=re.DOTALL)

with open(r'c:\Users\bmayo\OneDrive\Desktop\SOFA\frontend\src\App.tsx', 'w', encoding='utf-8') as f:
    f.write(original)

print('Done')
