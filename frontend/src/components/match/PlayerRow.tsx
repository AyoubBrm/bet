import { useState, useMemo, useEffect } from "react";
import type { Player, SofascoreResponse } from "../../types/api";
import { isPlayerMatch } from "../../lib/string-matching";
import { calculateEdgeData } from "../../lib/math";

interface PlayerRowProps {
  player: Player;
  sofascoreData: SofascoreResponse | null;
  marketType: 'shots' | 'tackles';
  aliasVersion: number;
  defaultLine?: string;
}

export function PlayerRow({ player, sofascoreData, marketType, aliasVersion, defaultLine }: PlayerRowProps) {
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

  // Find the player in Sofascore data
  const sofaStats = useMemo(() => {
    if (!sofascoreData) return null;
    
    // We search across all matches in the Sofascore payload for this player's name
    for (const match of sofascoreData.matches) {
      for (const p of match.players) {
        if (isPlayerMatch(player.player, p.name)) {
          // Found fuzzy/alias match!
          if (p.matchs && p.matchs.length > 0 && p.matchs[0].statistics) {
             return p.matchs[0].statistics;
          }
        }
      }
    }
    return null;
  }, [player.player, sofascoreData, aliasVersion]);

  // Run Edge Calculation
  const lambda = marketType === 'shots' 
    ? sofaStats?.shots_per_90_minutes 
    : sofaStats?.tackles_per_90_minutes;
    
  const edgeData = calculateEdgeData(selectedShot, currentOdds, lambda);

  return (
    <tr className="hover:bg-surface-hover/50 transition-colors border-b border-border/50 last:border-0 group">
      <td className="py-4 px-6 text-sm font-medium text-text whitespace-nowrap">
        {player.player}
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        <div className="relative w-32 mx-auto">
          <select
            value={selectedShot}
            onChange={(e) => setSelectedShot(e.target.value)}
            className="appearance-none bg-surface border border-border text-sm font-semibold rounded-lg focus:ring-primary focus:border-primary block w-full py-2.5 cursor-pointer transition-colors hover:border-primary/50 text-center"
            style={{ textAlignLast: "center" }}
          >
            {shotOptions.map((opt) => {
              const num = parseInt(opt.replace(/\D/g, ""), 10);
              const over = isNaN(num) ? opt : `Over ${num - 0.5}`;
              return (
                <option key={opt} value={opt} style={{ textAlign: "center" }}>
                  {over}
                </option>
              );
            })}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3 text-text">
            <svg className="w-4 h-4 fill-current" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
              <path d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
            </svg>
          </div>
        </div>
      </td>
      {marketType === 'shots' && (
        <td className="py-4 px-6 whitespace-nowrap text-center">
          <span className="text-sm font-medium text-text">{sofaStats ? sofaStats.shots_per_90_minutes : "--"}</span>
        </td>
      )}
      {marketType === 'tackles' && (
        <td className="py-4 px-6 whitespace-nowrap text-center">
          <span className="text-sm font-medium text-text">{sofaStats ? sofaStats.tackles_per_90_minutes : "--"}</span>
        </td>
      )}
      <td className="py-4 px-6 whitespace-nowrap text-center">
        <span className={`inline-flex items-center justify-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${cleanOdds !== 'N/A' ? 'bg-primary/10 text-primary border border-primary/20' : 'bg-surface text-text-muted border border-border'}`}>
          {cleanOdds}
        </span>
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        {edgeData ? (
          <span className="text-sm font-medium text-text">
            {(edgeData.probability * 100).toFixed(1)}%
          </span>
        ) : (
          <span className="text-text-muted text-sm opacity-50 group-hover:opacity-100 transition-opacity">--</span>
        )}
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        {edgeData ? (
          <span className={`text-sm font-medium ${edgeData.evAtBookOdds > 0 ? 'text-primary' : 'text-text-muted'}`}>
            {edgeData.evAtBookOdds > 0 ? '+' : ''}{(edgeData.evAtBookOdds * 100).toFixed(1)}%
          </span>
        ) : (
          <span className="text-text-muted text-sm opacity-50 group-hover:opacity-100 transition-opacity">--</span>
        )}
      </td>
      <td className="py-4 px-6 whitespace-nowrap text-center">
        {edgeData ? (
          <span className={`text-sm font-bold ${edgeData.edgeVsFairOdds > 0 ? 'text-primary' : 'text-text-muted'}`}>
            {edgeData.edgeVsFairOdds > 0 ? '+' : ''}{(edgeData.edgeVsFairOdds * 100).toFixed(1)}%
          </span>
        ) : (
          <span className="text-text-muted text-sm opacity-50 group-hover:opacity-100 transition-opacity">--</span>
        )}
      </td>
    </tr>
  );
}
