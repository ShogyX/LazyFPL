import { useState } from "react";
import { POS_RING, isLight, team as teamOf } from "../lib/teams";

const PHOTO = (code: number) => `https://resources.premierleague.com/premierleague/photos/players/110x140/p${code}.png`;

export interface AvatarPlayer {
  name: string;
  team?: string | null;
  position?: string | null;   // GK/DEF/MID/FWD
  pos?: number | null;        // 1..4
  code?: number | null;
}

const POS_NUM: Record<string, number> = { GK: 1, DEF: 2, MID: 3, FWD: 4 };
function posNum(p: AvatarPlayer): number {
  return p.pos ?? (p.position ? POS_NUM[p.position] ?? 0 : 0);
}

// FPL mugshot when a photo code exists; otherwise the designed CSS kit-avatar
// (team-kit fill, collar arc, initials) with a position-coloured ring.
export default function PlayerAvatar({ player, size = 46, ring = true, dim }:
  { player: AvatarPlayer; size?: number; ring?: boolean; dim?: boolean }) {
  const [failed, setFailed] = useState(false);
  const T = teamOf(player.team);
  const ringC = ring ? (POS_RING[posNum(player)] ?? "var(--line-2)") : "transparent";
  const ringStyle = ring ? `0 0 0 2px var(--surface), 0 0 0 ${Math.max(2, size * 0.05)}px ${ringC}` : "none";

  if (player.code && !failed) {
    return (
      <img src={PHOTO(player.code)} alt={player.name} loading="lazy" onError={() => setFailed(true)}
        style={{ width: size, height: size, borderRadius: "50%", objectFit: "cover", objectPosition: "top",
          background: "var(--surface-2)", boxShadow: ringStyle, opacity: dim ? 0.62 : 1, flexShrink: 0 }} />
    );
  }

  const light = isLight(T.kit);
  const ink = light ? (T.trim && !isLight(T.trim) ? T.trim : "#10161f") : "#fff";
  const initials = player.name.replace(/[^A-Za-z ]/g, "").slice(0, 3).toUpperCase();
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%", position: "relative", flexShrink: 0,
      background: `radial-gradient(120% 120% at 50% 18%, color-mix(in srgb, ${T.kit} 78%, #fff 22%), ${T.kit})`,
      boxShadow: ringStyle, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", opacity: dim ? 0.62 : 1,
    }}>
      <span style={{ position: "absolute", top: -size * 0.34, left: "50%", transform: "translateX(-50%)", width: size * 0.5, height: size * 0.5, borderRadius: "50%", background: T.trim, opacity: 0.5 }} />
      <span style={{ fontWeight: 800, fontSize: size * 0.3, letterSpacing: "-0.04em", color: ink, position: "relative", lineHeight: 1 }}>{initials}</span>
    </div>
  );
}

export function TeamBadge({ code, size = 22 }: { code: string | null | undefined; size?: number }) {
  const T = teamOf(code);
  return (
    <span style={{ width: size, height: size, borderRadius: 6, background: T.kit, color: isLight(T.kit) ? "#10161f" : "#fff",
      display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: size * 0.4, fontWeight: 800,
      letterSpacing: "-0.03em", boxShadow: `inset 0 0 0 1.5px ${T.trim}55` }}>{T.short}</span>
  );
}
