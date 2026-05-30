import type { Position } from "../lib/api";

export interface PitchPlayer {
  id: number;
  name: string;
  position: Position | null;
  meta?: string;       // price / xp / status shown under the name
  captain?: boolean;
  vice?: boolean;
}

const ROWS: Position[] = ["GK", "DEF", "MID", "FWD"];

// FPL-style pitch: starters laid out in position rows, an optional bench strip.
export default function Pitch({ starters, bench }: { starters: PitchPlayer[]; bench?: PitchPlayer[] }) {
  return (
    <div className="grid gap-3">
      <div className="rounded-card bg-[var(--color-pitch)] p-3 ring-1 ring-inset ring-border">
        <div className="grid gap-4 py-2">
          {ROWS.map((row) => {
            const players = starters.filter((p) => p.position === row);
            if (players.length === 0) return null;
            return (
              <div key={row} className="flex flex-wrap items-start justify-center gap-2 sm:gap-3">
                {players.map((p) => (
                  <Shirt key={p.id} player={p} />
                ))}
              </div>
            );
          })}
        </div>
      </div>
      {bench && bench.length > 0 && (
        <div className="flex flex-wrap items-start justify-center gap-2 rounded-card border border-border bg-surface p-2 sm:gap-3">
          <span className="self-center pr-1 text-xs font-medium uppercase tracking-wide text-muted-fg">Bench</span>
          {bench.map((p) => (
            <Shirt key={p.id} player={p} muted />
          ))}
        </div>
      )}
    </div>
  );
}

function Shirt({ player, muted }: { player: PitchPlayer; muted?: boolean }) {
  return (
    <div className="flex w-16 flex-col items-center text-center sm:w-20">
      <div
        className={`relative flex h-9 w-9 items-center justify-center rounded-full text-xs font-bold ${
          muted ? "bg-muted text-muted-fg" : "bg-on-primary text-primary ring-2 ring-primary"
        }`}
      >
        {player.position ?? "?"}
        {player.captain && <Badge label="C" />}
        {!player.captain && player.vice && <Badge label="V" />}
      </div>
      <span className="mt-1 w-full truncate text-[11px] font-medium text-fg" title={player.name}>
        {player.name}
      </span>
      {player.meta && <span className="tnum text-[10px] text-muted-fg">{player.meta}</span>}
    </div>
  );
}

function Badge({ label }: { label: string }) {
  return (
    <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-accent text-[9px] font-bold text-on-primary">
      {label}
    </span>
  );
}
