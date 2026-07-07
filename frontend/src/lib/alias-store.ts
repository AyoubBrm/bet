/**
 * Alias Store — manages user-defined player aliases in localStorage.
 * These are merged with the hardcoded PLAYER_ALIASES at runtime.
 * Key = Bet365 name, Value = Sofascore name.
 */

const STORAGE_KEY = "player_aliases_v1";

export type AliasEntry = {
  bet365Name: string;
  sofascoreName: string;
};

export function getUserAliases(): AliasEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function addUserAlias(bet365Name: string, sofascoreName: string): void {
  const aliases = getUserAliases();
  // Prevent duplicates
  const exists = aliases.some(
    (a) => a.bet365Name.toLowerCase() === bet365Name.toLowerCase()
  );
  if (!exists) {
    aliases.push({ bet365Name: bet365Name.trim(), sofascoreName: sofascoreName.trim() });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(aliases));
  }
}

export function removeUserAlias(bet365Name: string): void {
  const aliases = getUserAliases().filter(
    (a) => a.bet365Name.toLowerCase() !== bet365Name.toLowerCase()
  );
  localStorage.setItem(STORAGE_KEY, JSON.stringify(aliases));
}

/**
 * Returns all aliases (hardcoded + user-defined) as a flat Record.
 */
export function getAllAliases(
  hardcoded: Record<string, string>
): Record<string, string> {
  const result: Record<string, string> = { ...hardcoded };
  for (const entry of getUserAliases()) {
    result[entry.bet365Name] = entry.sofascoreName;
  }
  return result;
}
