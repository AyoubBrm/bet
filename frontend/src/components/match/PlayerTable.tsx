import { useMemo } from "react";
import type { Player, SofascoreMatch } from "../../types/api";
import { PlayerRow } from "./PlayerRow";
import { isSofascorePlayerForBet365 } from "../../lib/sofascore-player-match";
import { calculateEdgeData } from "../../lib/math";

interface PlayerTableProps {
  players: Player[];
  sofascoreMatch: SofascoreMatch | null;
  marketType: 'shots' | 'tackles';
  aliasVersion: number;
}

/** Returns the line (e.g. "Shot 1+") with odds closest to 2.0 */
function getBestLine(player: Player): { line: string; odds: number } | null {
  let best: { line: string; odds: number } | null = null;
  let bestDist = Infinity;
  for (const [line, oddsVal] of Object.entries(player.odds)) {
    const num = Number(oddsVal);
    const dist = Math.abs(num - 2.0);
    if (dist < bestDist) {
      bestDist = dist;
      best = { line, odds: num };
    }
  }
  return best;
}

/** Looks up the sofascore stats for a player */
function getSofaStats(
  player: Player,
  sofascoreMatch: SofascoreMatch | null
) {
  if (!sofascoreMatch) return null;
  for (const p of sofascoreMatch.players) {
    if (isSofascorePlayerForBet365(player.player, p)) {
      if (p.matchs && p.matchs.length > 0 && p.matchs[0].statistics) {
        return p.matchs[0].statistics;
      }
    }
  }
  return null;
}

export function PlayerTable({ players, sofascoreMatch, marketType, aliasVersion }: PlayerTableProps) {
  // Keep rows stable while partial SofaScore stats are still streaming in.
  const enrichedPlayers = useMemo(() => {
    const mappedPlayers = players
      .map((player, index) => {
        const best = getBestLine(player);
        if (!best) return null;

        const sofaStats = getSofaStats(player, sofascoreMatch);
        const lambda =
          marketType === 'shots'
            ? sofaStats?.shots_per_90_minutes
            : sofaStats?.tackles_per_90_minutes;

        const edgeData = calculateEdgeData(best.line, best.odds, lambda);
        const ev = edgeData?.evAtBookOdds ?? -Infinity;

        return { player, bestLine: best.line, ev, hasStats: Boolean(sofaStats), index };
      })
      .filter((x): x is { player: Player; bestLine: string; ev: number; hasStats: boolean; index: number } => x !== null);

    const allRowsHaveStats = mappedPlayers.length > 0 && mappedPlayers.every((entry) => entry.hasStats);
    if (allRowsHaveStats) {
      return [...mappedPlayers].sort((a, b) => b.ev - a.ev);
    }
    return mappedPlayers;
  }, [players, sofascoreMatch, marketType, aliasVersion]);

  if (enrichedPlayers.length === 0) {
    return (
      <div className="p-8 text-center text-text-muted text-sm">
        No player odds found for this match.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-border">
        <thead className="bg-surface/50">
          <tr>
            <th scope="col" className="py-3 px-6 text-left text-xs font-medium text-text-muted uppercase tracking-wider">
              Player
            </th>
            <th scope="col" className="py-3 px-6 text-center text-xs font-medium text-text-muted uppercase tracking-wider">
              Line ▼
            </th>
            <th scope="col" className="py-3 px-6 text-center text-xs font-medium text-text-muted uppercase tracking-wider">
              Bet365 Odds
            </th>
            {marketType === 'shots' && (
              <th scope="col" className="py-3 px-6 text-center text-xs font-medium text-text-muted uppercase tracking-wider">
                Shots/90
              </th>
            )}
            {marketType === 'tackles' && (
              <th scope="col" className="py-3 px-6 text-center text-xs font-medium text-text-muted uppercase tracking-wider">
                Tackles/90
              </th>
            )}
            <th scope="col" className="py-3 px-6 text-center text-xs font-medium text-text-muted uppercase tracking-wider">
              My Probability
            </th>
            <th scope="col" className="py-3 px-6 text-center text-xs font-medium text-text-muted uppercase tracking-wider">
              EV ↓
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50 bg-background/30 backdrop-blur-sm">
          {enrichedPlayers.map(({ player, bestLine }, idx) => (
            <PlayerRow
              key={`${player.player}-${idx}`}
              player={player}
              sofascoreMatch={sofascoreMatch}
              marketType={marketType}
              aliasVersion={aliasVersion}
              defaultLine={bestLine}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
