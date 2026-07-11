import { useState, useMemo, useEffect } from "react";
import type { Player, SofascoreMatch } from "../../types/api";
import { isSofascorePlayerForBet365 } from "../../lib/sofascore-player-match";
import { calculateEdgeData } from "../../lib/math";

interface PlayerRowProps {
  player: Player;
  sofascoreMatch: SofascoreMatch | null;
  marketType: 'shots' | 'tackles';
  aliasVersion: number;
  defaultLine?: string;
}

function getEdgeColorClass(value: number): string {
  const percentage = value * 100;
  if (percentage >= 30) return "text-emerald-400";
  if (percentage >= 20) return "text-lime-400";
  if (percentage >= 10) return "text-yellow-300";
  if (percentage >= 0) return "text-orange-400";
  return "text-red-400";
}

export function PlayerRow({ player, sofascoreMatch, marketType, aliasVersion, defaultLine }: PlayerRowProps) {
  // Extract all available shot lines (e.g., "shot +1", "shot +2")
  // Sort them numerically so +1 comes before +2, +10, etc.
  const shotOptions = useMemo(() => {
    return Object.keys(player.odds).sort((a, b) => {
      const numA = parseInt(a.replace(/\D/g, "")) || 0;
      const numB = parseInt(b.replace(/\D/g, "")) || 0;
      return numA - numB;
    });
  }, [player.odds]);

  // Default to the line passed from parent (closest to 2.0) or fallback to lowest
  const [selectedShot, setSelectedShot] = useState(defaultLine || shotOptions[0] || "");

  // Reset selected shot if it's no longer in the available options (e.g., when switching markets)
  useEffect(() => {
    if (shotOptions.length > 0 && !shotOptions.includes(selectedShot)) {
      setSelectedShot(shotOptions[0]);
    }
  }, [shotOptions, selectedShot]);

  const currentOdds = selectedShot ? player.odds[selectedShot] : undefined;
  
  // Format numeric odds
  const cleanOdds = currentOdds !== undefined ? currentOdds.toFixed(2) : "N/A";

  const formatLineLabel = (line: string): string => {
    const num = parseInt(line.replace(/\D/g, ""), 10);
    return isNaN(num) ? line : `Over ${num - 0.5}`;
  };

  // Find the player in Sofascore data
  const sofaStats = useMemo(() => {
    if (!sofascoreMatch) return null;
    
    for (const p of sofascoreMatch.players) {
      if (isSofascorePlayerForBet365(player.player, p)) {
        if (p.matchs && p.matchs.length > 0 && p.matchs[0].statistics) {
           return p.matchs[0].statistics;
        }
      }
    }
    return null;
  }, [player.player, sofascoreMatch, aliasVersion]);

  // Run Edge Calculation
  const lambda = marketType === 'shots' 
    ? sofaStats?.shots_per_90_minutes 
    : sofaStats?.tackles_per_90_minutes;
    
  const edgeData = calculateEdgeData(selectedShot, currentOdds, lambda);

  return (
    <tr className="hover:bg-surface-hover/50 transition-colors border-b border-border/50 last:border-0 group">
      <td className="py-4 px-6 text-base font-semibold text-text whitespace-nowrap">
        {player.player}
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        <div className="relative w-[98px] mx-auto">
          <select
            value={selectedShot}
            onChange={(e) => setSelectedShot(e.target.value)}
            className="appearance-none bg-surface border border-border text-sm font-bold rounded-md focus:ring-primary focus:border-primary block w-full h-9 pl-2 pr-6 cursor-pointer transition-colors hover:border-primary/50 text-center tabular-nums"
            style={{ textAlignLast: "center" }}
          >
            {shotOptions.map((opt) => {
              return (
                <option key={opt} value={opt} style={{ textAlign: "center" }}>
                  {formatLineLabel(opt)}
                </option>
              );
            })}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-1.5 text-text">
            <svg className="w-3.5 h-3.5 fill-current" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
              <path d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
            </svg>
          </div>
        </div>
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        <span className={`inline-flex min-w-16 items-center justify-center px-3 py-1.5 rounded-md text-base font-bold tabular-nums ${cleanOdds !== 'N/A' ? 'bg-primary/10 text-primary border border-primary/20' : 'bg-surface text-text-muted border border-border'}`}>
          {cleanOdds}
        </span>
      </td>
      {marketType === 'shots' && (
        <td className="py-4 px-6 whitespace-nowrap text-center">
          <span className="text-base font-bold tabular-nums text-text">{sofaStats ? sofaStats.shots_per_90_minutes : "--"}</span>
        </td>
      )}
      {marketType === 'tackles' && (
        <td className="py-4 px-6 whitespace-nowrap text-center">
          <span className="text-base font-bold tabular-nums text-text">{sofaStats ? sofaStats.tackles_per_90_minutes : "--"}</span>
        </td>
      )}
      <td className="py-4 px-6 whitespace-nowrap text-center">
        {edgeData ? (
          <span className="text-base font-bold tabular-nums text-text">
            {(edgeData.probability * 100).toFixed(1)}%
          </span>
        ) : (
          <span className="text-text-muted text-sm opacity-50 group-hover:opacity-100 transition-opacity">--</span>
        )}
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        {edgeData ? (
          <span className={`text-base font-bold tabular-nums ${getEdgeColorClass(edgeData.evAtBookOdds)}`}>
            {edgeData.evAtBookOdds > 0 ? '+' : ''}{(edgeData.evAtBookOdds * 100).toFixed(1)}%
          </span>
        ) : (
          <span className="text-text-muted text-sm opacity-50 group-hover:opacity-100 transition-opacity">--</span>
        )}
      </td>
    </tr>
  );
}
