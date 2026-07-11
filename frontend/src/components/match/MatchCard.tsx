import { useState } from "react";
import type { MatchEntry, MatchJobStatus, SofascoreMatch } from "../../types/api";
import { PlayerTable } from "./PlayerTable";
import { ChevronDown, ChevronUp, Calendar, Clock, ExternalLink } from "lucide-react";
import { cn } from "../../lib/utils";

interface MatchCardProps {
  entry: MatchEntry;
  searchQuery: string;
  sofascoreMatch: SofascoreMatch | null;
  status?: MatchJobStatus;
  marketType: 'shots' | 'tackles';
  aliasVersion: number;
}

export function MatchCard({ entry, searchQuery, sofascoreMatch, status, marketType, aliasVersion }: MatchCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const { match, player_shots, player_tackles } = entry;
  
  const players = player_shots || player_tackles || [];

  // Filter players if there's a search query
  const filteredPlayers = players.filter(p => 
    p.player.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Auto-expand if searching for a specific player and they match
  const shouldExpand = isExpanded || (searchQuery.length > 2 && filteredPlayers.length > 0 && filteredPlayers.length < players.length);

  return (
    <div className="glass-card rounded-xl overflow-hidden mb-6 transition-all duration-300 hover:shadow-2xl hover:border-primary/30 group">
      {/* Card Header (Clickable) */}
      <div 
        className="p-6 cursor-pointer flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 relative overflow-hidden"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="absolute inset-0 bg-gradient-to-r from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
        
        <div className="flex-1 z-10">
          <div className="flex items-center gap-3 text-text-muted text-sm mb-2 font-medium">
            <span className="flex items-center gap-1.5"><Calendar className="w-4 h-4 text-primary/70" /> {match.date.split('T')[0]}</span>
            <span className="w-1 h-1 rounded-full bg-border"></span>
            <span className="flex items-center gap-1.5"><Clock className="w-4 h-4 text-primary/70" /> {match.date.split('T')[1]?.replace('Z', '')}</span>
            <span className="w-1 h-1 rounded-full bg-border"></span>
            <span className="px-2 py-0.5 rounded text-xs bg-surface text-text-muted border border-border">Odds ID: {match.id}</span>
            {status && (
              <>
                <span className="w-1 h-1 rounded-full bg-border"></span>
                <span className={cn(
                  "px-2 py-0.5 rounded text-xs border capitalize",
                  status === "done" || status === "cached"
                    ? "bg-primary/10 text-primary border-primary/20"
                    : status === "failed"
                      ? "bg-danger/10 text-danger border-danger/20"
                      : "bg-surface text-text-muted border-border"
                )}>
                  {status}
                </span>
              </>
            )}
            <span className="w-1 h-1 rounded-full bg-border"></span>
            <a 
              href={`https://www.bet365.com/#/AX/K^${encodeURIComponent(match.home + ' ' + match.away)}/`}
              target="_blank"
              rel="noopener noreferrer" 
              className="flex items-center gap-1 hover:text-primary transition-colors text-xs font-semibold"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="w-3.5 h-3.5" /> Bet365
            </a>
          </div>
          
          <h2 className="text-xl sm:text-2xl font-bold tracking-tight flex flex-wrap items-center gap-x-2">
            <span>{match.home}</span>
            <span className="text-primary/50 mx-2 text-lg">v</span>
            <span>{match.away}</span>
          </h2>
        </div>

        <div className="flex items-center gap-4 z-10 w-full sm:w-auto justify-between sm:justify-end">
          <div className="flex items-center gap-3">
            <div className="text-right mr-4 hidden sm:block">
              <p className="text-sm font-medium text-primary">{filteredPlayers.length} Players</p>
              <p className="text-xs text-text-muted">Available markets</p>
            </div>
            
            <button className="p-2 rounded-full hover:bg-surface-hover transition-colors text-text-muted hover:text-text">
              {shouldExpand ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      <div 
        className={cn(
          "grid transition-all duration-300 ease-in-out",
          shouldExpand ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="overflow-hidden bg-background/50 border-t border-border">
          <PlayerTable players={filteredPlayers} sofascoreMatch={sofascoreMatch} marketType={marketType} aliasVersion={aliasVersion} />
        </div>
      </div>
    </div>
  );
}
