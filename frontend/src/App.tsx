import { useState, useEffect } from "react";
import { Header } from "./components/layout/Header";
import { MatchCard } from "./components/match/MatchCard";
import { Skeleton } from "./components/ui/Skeleton";
import type { ApiResponse, MatchEntry, SofascoreResponse } from "./types/api";

function App() {
  const [data, setData] = useState<ApiResponse | null>(null);
  const [sofascoreData, setSofascoreData] = useState<SofascoreResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [aliasVersion, setAliasVersion] = useState(0);

  const [targetEndpoint, setTargetEndpoint] = useState<string | null>(null);

  useEffect(() => {
    let intervalId: any;

    const fetchData = async (isInitial: boolean) => {
      if (!targetEndpoint) return;
      try {
        if (isInitial) setIsLoading(true);
        setError(null);
        
        const response = await fetch(targetEndpoint);
        
        if (!response.ok) {
          throw new Error(`Failed to fetch data: ${response.statusText}`);
        }
        
        const result = await response.json();
        console.log("FETCHED DATA:", result);
        setData(result);
        
        // Set loading false immediately so the UI renders the Bet365 data!
        if (isInitial) setIsLoading(false);
        
        // Fetch Sofascore Data in the background
        if (isInitial && result.matches && result.matches.length > 0) {
            const uniqueDates = Array.from(new Set(result.matches.map((m: any) => m.match.date.split('T')[0])));
            // We do not await this try/catch block so it runs independently
            (async () => {
                try {
                    const fetchPromises = uniqueDates.map(date => 
                        fetch(`http://localhost:8002/api/extraction/date/${date}`).then(res => res.ok ? res.json() : null)
                    );
                    const results = await Promise.all(fetchPromises);
                    
                    const mergedSofaData: SofascoreResponse = {
                        match_count: 0,
                        total_number_of_player_s: 0,
                        matches: []
                    };
                    
                    for (const res of results) {
                        if (res && res.matches) {
                            mergedSofaData.match_count += res.match_count || 0;
                            mergedSofaData.total_number_of_player_s += res.total_number_of_player_s || 0;
                            mergedSofaData.matches.push(...res.matches);
                        }
                    }
                    setSofascoreData(mergedSofaData);
                } catch (err) {
                    console.error("Failed to fetch Sofascore data:", err);
                }
            })();
        }
      } catch (err: any) {
        setError(err.message || "An unexpected error occurred while fetching data.");
        if (isInitial) setIsLoading(false);
      }
    };

    if (targetEndpoint) {
      // Fetch immediately with loading state
      fetchData(true);
      
      // Set up silent background polling every 5 seconds
      intervalId = setInterval(() => {
        fetchData(false);
      }, 5000);
    } else {
      setIsLoading(false);
    }
    
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [targetEndpoint]);

  // Filter matches based on search query (teams or players inside the match)
  const filteredMatches = data?.matches.filter((entry: MatchEntry) => {
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
  });

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
                onClick={() => setTargetEndpoint('http://localhost:8002/upcoming/player_shots')}
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
                onClick={() => setTargetEndpoint('http://localhost:8002/upcoming/player_tackles')}
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
                sofascoreData={sofascoreData}
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
