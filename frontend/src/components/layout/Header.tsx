import { useState } from "react";
import { Search, Activity, UserCog } from "lucide-react";
import { AliasManager } from "../ui/AliasManager";

interface HeaderProps {
  onSearch: (term: string) => void;
  onAliasChange: () => void;
}

export function Header({ onSearch, onAliasChange }: HeaderProps) {
  const [showAliasManager, setShowAliasManager] = useState(false);

  return (
    <>
      <header className="sticky top-0 z-50 glass border-b border-border shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 shrink-0">
            <Activity className="w-6 h-6 text-primary animate-pulse" />
            <h1 className="text-xl font-bold tracking-tight">SOFA <span className="text-primary">Analytics</span></h1>
          </div>

          <div className="relative w-full max-w-md hidden sm:block">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-4 w-4 text-text-muted" />
            </div>
            <input
              type="text"
              className="block w-full pl-10 pr-3 py-2 border border-border rounded-full leading-5 bg-surface/50 text-text placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary sm:text-sm transition-all"
              placeholder="Search players or teams..."
              onChange={(e) => onSearch(e.target.value)}
            />
          </div>

          <button
            onClick={() => setShowAliasManager(true)}
            title="Player Alias Manager"
            className="shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-surface/50 hover:bg-surface hover:border-primary/50 text-text-muted hover:text-text transition-all text-sm font-medium"
          >
            <UserCog className="w-4 h-4" />
            <span className="hidden sm:inline">Aliases</span>
          </button>
        </div>
      </header>

      {showAliasManager && (
        <AliasManager onClose={() => setShowAliasManager(false)} onAliasChange={onAliasChange} />
      )}
    </>
  );
}
