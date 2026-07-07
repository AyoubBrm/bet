import { getAllAliases } from "./alias-store";

/**
 * Alias Dictionary — FOR EXTREME CASES ONLY
 * These are players who use completely different names on Bet365 vs Sofascore.
 * Key = Bet365 name, Value = Sofascore name.
 * User-defined aliases are stored in localStorage and merged at runtime.
 */
export const PLAYER_ALIASES: Record<string, string> = {
  "Nabil Emad": "Nabil Donga",
  // Add more hardcoded aliases here when discovered
};

/**
 * Normalizes a string by converting to lowercase and removing diacritics.
 * e.g., "Fernández" -> "fernandez"
 */
export function normalizeName(name: string): string {
  if (!name) return "";
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

/**
 * Calculates the Levenshtein Distance between two strings.
 */
function levenshteinDistance(a: string, b: string): number {
  const matrix = [];

  for (let i = 0; i <= b.length; i++) {
    matrix[i] = [i];
  }
  for (let j = 0; j <= a.length; j++) {
    matrix[0][j] = j;
  }

  for (let i = 1; i <= b.length; i++) {
    for (let j = 1; j <= a.length; j++) {
      if (b.charAt(i - 1) === a.charAt(j - 1)) {
        matrix[i][j] = matrix[i - 1][j - 1];
      } else {
        matrix[i][j] = Math.min(
          matrix[i - 1][j - 1] + 1, // substitution
          matrix[i][j - 1] + 1,     // insertion
          matrix[i - 1][j] + 1      // deletion
        );
      }
    }
  }

  return matrix[b.length][a.length];
}

/**
 * Returns a similarity score between 0 and 1.
 * 1 means exact match, 0 means completely different.
 */
export function calculateSimilarity(s1: string, s2: string): number {
  let longer = s1;
  let shorter = s2;

  if (s1.length < s2.length) {
    longer = s2;
    shorter = s1;
  }

  const longerLength = longer.length;
  if (longerLength === 0) {
    return 1.0;
  }

  const distance = levenshteinDistance(longer, shorter);
  return (longerLength - distance) / parseFloat(longerLength.toString());
}

/**
 * Master matching function — combines:
 * 1. Alias map (hardcoded + user-defined from localStorage)
 * 2. Exact match
 * 3. Substring match
 * 4. Token-prefix match (handles "Nico Paz" vs "Nicolas Paz")
 * 5. Fuzzy Levenshtein match
 */
export function isPlayerMatch(
  bet365Name: string,
  sofascoreName: string,
  threshold: number = 0.8
): boolean {
  // 1. Alias Match (hardcoded + user localStorage aliases, bidirectional)
  const allAliases = getAllAliases(PLAYER_ALIASES);
  const aliasForBet365 = allAliases[bet365Name];
  const aliasForSofa = allAliases[sofascoreName];
  if (aliasForBet365 && aliasForBet365.toLowerCase() === sofascoreName.toLowerCase()) return true;
  if (aliasForSofa && aliasForSofa.toLowerCase() === bet365Name.toLowerCase()) return true;

  // 2. Normalize both
  const normBet365 = normalizeName(bet365Name);
  const normSofa = normalizeName(sofascoreName);

  // 3. Exact Match (fast path)
  if (normBet365 === normSofa) return true;

  // 4. Substring Match (e.g. "Alex" inside "Alexander")
  if (normSofa.includes(normBet365) || normBet365.includes(normSofa)) return true;

  // 5. Token-Prefix Match:
  // Handles nicknames like "Nico Paz" vs "Nicolas Paz" and "Jose Flaco Lopez" vs "Jose Lopez"
  const tokensBet365 = normBet365.split(/\s+/);
  const tokensSofa = normSofa.split(/\s+/);
  const [shorter, longer] =
    tokensBet365.length <= tokensSofa.length
      ? [tokensBet365, tokensSofa]
      : [tokensSofa, tokensBet365];

  const allTokensMatch = shorter.every((shortToken) =>
    longer.some(
      (longToken) =>
        longToken === shortToken ||
        longToken.startsWith(shortToken) ||
        shortToken.startsWith(longToken)
    )
  );
  if (allTokensMatch) return true;

  // 6. Fuzzy Match (Levenshtein)
  const similarity = calculateSimilarity(normBet365, normSofa);
  return similarity >= threshold;
}
