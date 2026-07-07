import { useState, useEffect } from "react";
import {
  getUserAliases,
  addUserAlias,
  removeUserAlias,
  type AliasEntry,
} from "../../lib/alias-store";
import { PLAYER_ALIASES } from "../../lib/string-matching";

interface AliasManagerProps {
  onClose: () => void;
  onAliasChange: () => void;
}

export function AliasManager({ onClose, onAliasChange }: AliasManagerProps) {
  const [userAliases, setUserAliases] = useState<AliasEntry[]>([]);
  const [bet365Input, setBet365Input] = useState("");
  const [sofascoreInput, setSofascoreInput] = useState("");
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const builtInAliases = Object.entries(PLAYER_ALIASES).map(
    ([bet365Name, sofascoreName]) => ({ bet365Name, sofascoreName })
  );

  useEffect(() => {
    setUserAliases(getUserAliases());
  }, []);

  const handleAdd = () => {
    setError("");
    setSuccessMsg("");
    if (!bet365Input.trim() || !sofascoreInput.trim()) {
      setError("Both fields are required.");
      return;
    }
    addUserAlias(bet365Input.trim(), sofascoreInput.trim());
    setUserAliases(getUserAliases());
    onAliasChange();
    setBet365Input("");
    setSofascoreInput("");
    setSuccessMsg(`✓ Alias added: "${bet365Input.trim()}" → "${sofascoreInput.trim()}"`);
    setTimeout(() => setSuccessMsg(""), 3000);
  };

  const handleRemove = (bet365Name: string) => {
    removeUserAlias(bet365Name);
    setUserAliases(getUserAliases());
    onAliasChange();
  };

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="bg-background border border-border rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
        style={{ boxShadow: "0 0 60px rgba(99,102,241,0.15)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-xl font-bold text-text">Player Alias Manager</h2>
            <p className="text-sm text-text-muted mt-0.5">
              Map Bet365 names to Sofascore names when they don't match automatically.
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-text-muted hover:text-text hover:bg-surface transition-colors text-lg"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-6">
          {/* Add New Alias */}
          <div className="bg-surface/60 border border-border rounded-xl p-5">
            <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wider mb-4">
              Add New Alias
            </h3>
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="flex-1">
                <label className="block text-xs text-text-muted mb-1.5">Bet365 Name</label>
                <input
                  type="text"
                  placeholder="e.g. Nabil Emad"
                  value={bet365Input}
                  onChange={(e) => setBet365Input(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                  className="w-full bg-background border border-border rounded-lg px-3 py-2.5 text-sm text-text placeholder-text-muted focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors"
                />
              </div>
              <div className="hidden sm:flex items-end pb-2.5 text-text-muted text-lg">→</div>
              <div className="flex-1">
                <label className="block text-xs text-text-muted mb-1.5">Sofascore Name</label>
                <input
                  type="text"
                  placeholder="e.g. Nabil Donga"
                  value={sofascoreInput}
                  onChange={(e) => setSofascoreInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                  className="w-full bg-background border border-border rounded-lg px-3 py-2.5 text-sm text-text placeholder-text-muted focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors"
                />
              </div>
              <div className="flex items-end">
                <button
                  onClick={handleAdd}
                  className="w-full sm:w-auto px-5 py-2.5 bg-primary hover:bg-primary/90 text-white font-semibold rounded-lg text-sm transition-colors"
                >
                  Add
                </button>
              </div>
            </div>
            {error && (
              <p className="text-red-400 text-xs mt-3">{error}</p>
            )}
            {successMsg && (
              <p className="text-green-400 text-xs mt-3">{successMsg}</p>
            )}
          </div>

          {/* User Aliases */}
          <div>
            <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wider mb-3">
              Your Aliases{" "}
              <span className="ml-1 bg-primary/15 text-primary text-xs px-2 py-0.5 rounded-full">
                {userAliases.length}
              </span>
            </h3>
            {userAliases.length === 0 ? (
              <div className="text-center py-8 text-text-muted text-sm border border-dashed border-border rounded-xl">
                No custom aliases yet. Add one above!
              </div>
            ) : (
              <div className="space-y-2">
                {userAliases.map((alias) => (
                  <div
                    key={alias.bet365Name}
                    className="flex items-center justify-between bg-surface/50 border border-border rounded-lg px-4 py-3 group hover:border-primary/30 transition-colors"
                  >
                    <div className="flex items-center gap-3 text-sm min-w-0">
                      <span className="font-medium text-text truncate">{alias.bet365Name}</span>
                      <span className="text-text-muted shrink-0">→</span>
                      <span className="text-primary truncate">{alias.sofascoreName}</span>
                    </div>
                    <button
                      onClick={() => handleRemove(alias.bet365Name)}
                      className="ml-3 shrink-0 text-text-muted hover:text-red-400 transition-colors text-sm opacity-0 group-hover:opacity-100"
                      title="Remove alias"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Built-in Aliases */}
          {builtInAliases.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wider mb-3">
                Built-in Aliases{" "}
                <span className="ml-1 bg-surface text-text-muted text-xs px-2 py-0.5 rounded-full border border-border">
                  {builtInAliases.length}
                </span>
              </h3>
              <div className="space-y-2">
                {builtInAliases.map((alias) => (
                  <div
                    key={alias.bet365Name}
                    className="flex items-center justify-between bg-surface/30 border border-border/60 rounded-lg px-4 py-3"
                  >
                    <div className="flex items-center gap-3 text-sm min-w-0">
                      <span className="font-medium text-text/70 truncate">{alias.bet365Name}</span>
                      <span className="text-text-muted shrink-0">→</span>
                      <span className="text-primary/70 truncate">{alias.sofascoreName}</span>
                    </div>
                    <span className="ml-3 shrink-0 text-xs text-text-muted border border-border/50 rounded px-2 py-0.5">
                      built-in
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border bg-surface/30">
          <p className="text-xs text-text-muted">
            💾 Aliases are saved in your browser and applied instantly — no restart needed.
          </p>
        </div>
      </div>
    </div>
  );
}
