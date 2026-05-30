import { useState } from "react";
import { Shirt } from "lucide-react";
import type { Position } from "../lib/api";

// Official FPL player mugshot. `code` is the element's photo code (players.code).
const PHOTO = (code: number) =>
  `https://resources.premierleague.com/premierleague/photos/players/110x140/p${code}.png`;

const POS_RING: Record<string, string> = {
  GK: "ring-amber-400",
  DEF: "ring-sky-400",
  MID: "ring-emerald-400",
  FWD: "ring-rose-400",
};

export default function PlayerAvatar({
  code, position, size = 44, muted,
}: { code: number | null; position: Position | null; size?: number; muted?: boolean }) {
  const [failed, setFailed] = useState(false);
  const ring = POS_RING[position ?? ""] ?? "ring-border";
  const dim = { width: size, height: size };

  if (code && !failed) {
    return (
      <img
        src={PHOTO(code)}
        alt={position ?? "player"}
        loading="lazy"
        onError={() => setFailed(true)}
        style={dim}
        className={`rounded-full bg-surface object-cover object-top shadow ring-2 ${ring} ${muted ? "opacity-80" : ""}`}
      />
    );
  }
  // Fallback: a position-tinted jersey icon.
  return (
    <span
      style={dim}
      className={`flex items-center justify-center rounded-full bg-muted shadow ring-2 ${ring}`}
      title={position ?? "player"}
    >
      <Shirt className="h-1/2 w-1/2 text-muted-fg" aria-hidden />
    </span>
  );
}
