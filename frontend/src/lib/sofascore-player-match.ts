import type { SofascorePlayer } from "../types/api";
import { getAllAliases } from "./alias-store";
import { PLAYER_ALIASES, normalizeName } from "./string-matching";

function isExactOrAlias(bet365Name: string, sofascoreName: string): boolean {
  const normBet365 = normalizeName(bet365Name);
  const normSofa = normalizeName(sofascoreName);
  if (normBet365 === normSofa) return true;

  const aliases = getAllAliases(PLAYER_ALIASES);
  const aliasForBet365 = aliases[bet365Name];
  const aliasForSofa = aliases[sofascoreName];

  return (
    Boolean(aliasForBet365 && normalizeName(aliasForBet365) === normSofa) ||
    Boolean(aliasForSofa && normalizeName(aliasForSofa) === normBet365)
  );
}

export function isSofascorePlayerForBet365(
  bet365Name: string,
  sofascorePlayer: SofascorePlayer
): boolean {
  const linkedNames = [
    ...(sofascorePlayer.bet365_names ?? []),
    ...(sofascorePlayer.bet365_name ? [sofascorePlayer.bet365_name] : []),
  ];

  // Backend only sends bet365_names after resolving ambiguity, so these are trusted.
  if (linkedNames.some((name) => isExactOrAlias(bet365Name, name))) {
    return true;
  }

  // Fallback for old cached payloads that do not include bet365_names.
  // Keep this exact-only so frontend does not guess between similar names.
  return isExactOrAlias(bet365Name, sofascorePlayer.name);
}
