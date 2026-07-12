import {
  Activity,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Crosshair,
  Trophy,
} from "lucide-react";

export type MarketKey = "shots" | "tackles";

interface MarketSelectorProps {
  activeMarket: MarketKey | null;
  isLoading: boolean;
  shotsReady: boolean;
  tacklesReady: boolean;
  onSelectMarket: (market: MarketKey) => void;
}

const futureCompetitions = [
  "Premier League",
  "La Liga",
  "Serie A",
  "Bundesliga",
  "Ligue 1",
  "Primeira Liga",
];

function MarketStatus({
  market,
  activeMarket,
  isLoading,
  ready,
}: {
  market: MarketKey;
  activeMarket: MarketKey | null;
  isLoading: boolean;
  ready: boolean;
}) {
  const active = market === activeMarket;

  if (active && isLoading && !ready) {
    return (
      <span className="flex items-center gap-1.5 text-xs font-semibold text-warning">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-warning/25 border-t-warning" />
        Fetching
      </span>
    );
  }

  if (active) {
    return (
      <span className="flex items-center gap-1.5 text-xs font-semibold text-primary">
        <CircleDot className="h-3.5 w-3.5" />
        Active
      </span>
    );
  }

  if (ready) {
    return (
      <span className="flex items-center gap-1.5 text-xs font-semibold text-text-muted">
        <Check className="h-3.5 w-3.5" />
        Ready
      </span>
    );
  }

  return <span className="text-xs font-medium text-text-muted">Available</span>;
}

export function MarketSelector({
  activeMarket,
  isLoading,
  shotsReady,
  tacklesReady,
  onSelectMarket,
}: MarketSelectorProps) {
  const markets = [
    {
      key: "shots" as const,
      title: "Player Shots Odds",
      description: "Shot lines, probability and EV",
      icon: Crosshair,
      ready: shotsReady,
    },
    {
      key: "tackles" as const,
      title: "Player Tackles Odds",
      description: "Tackle lines, probability and EV",
      icon: Activity,
      ready: tacklesReady,
    },
  ];

  return (
    <section className="overflow-hidden border-y border-border bg-surface/35">
      <div className="flex flex-col gap-4 border-b border-border px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-primary">
            <CircleDot className="h-3.5 w-3.5" />
            Market console
          </div>
          <h3 className="text-lg font-bold text-text">Select Market</h3>
          <p className="mt-1 text-sm text-text-muted">Choose a sportsbook, competition and player market.</p>
        </div>

        <div className="flex w-full items-center border border-border bg-background/55 p-1 sm:w-auto" aria-label="Sportsbook">
          <button
            type="button"
            className="flex min-h-10 flex-1 items-center justify-center gap-2 bg-text px-4 text-sm font-bold text-background sm:flex-none"
            aria-pressed="true"
          >
            <span className="flex h-5 items-center bg-primary px-1.5 text-[10px] font-black text-white">365</span>
            Bet365
          </button>
          <button
            type="button"
            disabled
            className="flex min-h-10 flex-1 cursor-not-allowed items-center justify-center gap-2 px-4 text-sm font-semibold text-text-muted opacity-65 sm:flex-none"
            title="Stoiximan odds integration is coming soon"
          >
            Stoiximan
            <Clock3 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="border-b border-border px-4 py-4 sm:px-5">
        <div className="mb-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-text">
            <Trophy className="h-4 w-4 text-warning" />
            Competition
          </div>
          <span className="text-xs text-text-muted">1 active / 6 planned</span>
        </div>

        <div className="flex gap-2 overflow-x-auto pb-1">
          <button
            type="button"
            className="flex min-h-9 shrink-0 items-center gap-2 border border-primary/50 bg-primary/10 px-3 text-sm font-semibold text-text"
            aria-pressed="true"
          >
            <span className="h-2 w-2 bg-primary" />
            World Cup 2026
          </button>
          {futureCompetitions.map((competition) => (
            <button
              key={competition}
              type="button"
              disabled
              className="min-h-9 shrink-0 cursor-not-allowed border border-border bg-background/35 px-3 text-sm font-medium text-text-muted opacity-55"
              title={`${competition} support is planned`}
            >
              {competition}
            </button>
          ))}
        </div>
      </div>

      <div className="px-4 py-4 sm:px-5 sm:py-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-sm font-semibold text-text">Player markets</span>
          <span className="text-xs text-text-muted">Bet365 / World Cup 2026</span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {markets.map(({ key, title, description, icon: Icon, ready }) => {
            const active = activeMarket === key;
            const disabled = isLoading && active && !ready;

            return (
              <button
                key={key}
                type="button"
                onClick={() => onSelectMarket(key)}
                disabled={disabled}
                aria-pressed={active}
                className={`group flex min-h-20 items-center gap-3 border px-4 py-3 text-left transition-colors disabled:cursor-wait disabled:opacity-80 ${
                  active
                    ? "border-primary/60 bg-primary/10"
                    : "border-border bg-background/35 hover:border-text-muted hover:bg-surface-hover/50"
                }`}
              >
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center ${active ? "bg-primary text-white" : "bg-surface-hover text-text-muted"}`}>
                  <Icon className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-bold text-text sm:text-base">{title}</span>
                  <span className="mt-0.5 block text-xs text-text-muted sm:text-sm">{description}</span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-2">
                  <MarketStatus
                    market={key}
                    activeMarket={activeMarket}
                    isLoading={isLoading}
                    ready={ready}
                  />
                  <ChevronRight className={`h-4 w-4 transition-transform group-hover:translate-x-0.5 ${active ? "text-primary" : "text-text-muted"}`} />
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
