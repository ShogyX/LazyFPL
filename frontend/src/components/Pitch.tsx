import type { Position } from "../lib/api";
import PlayerAvatar from "./PlayerAvatar";

export interface PitchPlayer {
  id: number;
  name: string;
  position: Position | null;
  code?: number | null;
  meta?: string;       // price / xp / status shown under the name
  captain?: boolean;
  vice?: boolean;
}

const ROWS: Position[] = ["GK", "DEF", "MID", "FWD"];

// FPL-style pitch: a green field with markings, players laid out in position
// rows as photo mugshots, plus an optional bench strip.
export default function Pitch({ starters, bench }: { starters: PitchPlayer[]; bench?: PitchPlayer[] }) {
  return (
    <div className="grid gap-3">
      <div
        className="relative overflow-hidden rounded-card p-3 ring-1 ring-inset ring-black/10"
        style={{
          background:
            "repeating-linear-gradient(0deg, var(--color-pitch) 0px, var(--color-pitch) 38px, color-mix(in srgb, var(--color-pitch) 88%, white) 38px, color-mix(in srgb, var(--color-pitch) 88%, white) 76px)",
        }}
      >
        {/* field markings */}
        <div className="pointer-events-none absolute inset-2 rounded-md border border-white/25" aria-hidden />
        <div className="pointer-events-none absolute left-1/2 top-2 h-14 w-28 -translate-x-1/2 rounded-b-md border border-t-0 border-white/25" aria-hidden />
        <div className="relative grid gap-3 py-2">
          {ROWS.map((row) => {
            const players = starters.filter((p) => p.position === row);
            if (players.length === 0) return null;
            return (
              <div key={row} className="flex flex-wrap items-start justify-center gap-x-3 gap-y-2 sm:gap-x-5">
                {players.map((p) => <Shirt key={p.id} player={p} />)}
              </div>
            );
          })}
        </div>
      </div>
      {bench && bench.length > 0 && (
        <div className="flex flex-wrap items-start justify-center gap-3 rounded-card border border-border bg-surface p-2 sm:gap-5">
          <span className="self-center pr-1 text-xs font-semibold uppercase tracking-wide text-muted-fg">Bench</span>
          {bench.map((p) => <Shirt key={p.id} player={p} muted />)}
        </div>
      )}
    </div>
  );
}

function Shirt({ player, muted }: { player: PitchPlayer; muted?: boolean }) {
  return (
    <div className="flex w-[68px] flex-col items-center text-center sm:w-20">
      <div className="relative">
        <PlayerAvatar code={player.code ?? null} position={player.position} size={muted ? 38 : 46} muted={muted} />
        {player.captain && <Badge label="C" />}
        {!player.captain && player.vice && <Badge label="V" muted />}
      </div>
      <span className="mt-1 w-full truncate rounded bg-surface/90 px-1 text-[11px] font-semibold text-fg shadow-sm" title={player.name}>
        {player.name}
      </span>
      {player.meta && (
        <span className="tnum w-full truncate rounded-b bg-primary px-1 text-[10px] font-medium text-on-primary">{player.meta}</span>
      )}
    </div>
  );
}

function Badge({ label, muted }: { label: string; muted?: boolean }) {
  return (
    <span
      className={`absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold text-on-primary shadow ${
        muted ? "bg-secondary" : "bg-accent"
      }`}
    >
      {label}
    </span>
  );
}
