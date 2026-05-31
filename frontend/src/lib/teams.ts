// Static design data: team kit colours (for kit-avatars / badges) and the FDR
// colour scale. Not from the API — copied from the design handoff.
export interface Team { name: string; short: string; kit: string; trim: string; ink: string }

export const TEAMS: Record<string, Team> = {
  ARS: { name: "Arsenal", short: "ARS", kit: "#EF0107", trim: "#FFFFFF", ink: "#fff" },
  AVL: { name: "Aston Villa", short: "AVL", kit: "#95BFE5", trim: "#670E36", ink: "#3a0a20" },
  BOU: { name: "Bournemouth", short: "BOU", kit: "#DA291C", trim: "#000000", ink: "#fff" },
  BRE: { name: "Brentford", short: "BRE", kit: "#E30613", trim: "#FFFFFF", ink: "#fff" },
  BHA: { name: "Brighton", short: "BHA", kit: "#0057B8", trim: "#FFCD00", ink: "#fff" },
  BUR: { name: "Burnley", short: "BUR", kit: "#6C1D45", trim: "#99D6EA", ink: "#fff" },
  CHE: { name: "Chelsea", short: "CHE", kit: "#034694", trim: "#FFFFFF", ink: "#fff" },
  CRY: { name: "Crystal Palace", short: "CRY", kit: "#1B458F", trim: "#C4122E", ink: "#fff" },
  EVE: { name: "Everton", short: "EVE", kit: "#003399", trim: "#FFFFFF", ink: "#fff" },
  FUL: { name: "Fulham", short: "FUL", kit: "#FFFFFF", trim: "#000000", ink: "#111" },
  LEE: { name: "Leeds United", short: "LEE", kit: "#FFFFFF", trim: "#1D428A", ink: "#1d428a" },
  LIV: { name: "Liverpool", short: "LIV", kit: "#C8102E", trim: "#00B2A9", ink: "#fff" },
  MCI: { name: "Manchester City", short: "MCI", kit: "#6CABDD", trim: "#1C2C5B", ink: "#0b1733" },
  MUN: { name: "Manchester United", short: "MUN", kit: "#DA291C", trim: "#FBE122", ink: "#fff" },
  NEW: { name: "Newcastle", short: "NEW", kit: "#241F20", trim: "#FFFFFF", ink: "#fff" },
  NFO: { name: "Nott'm Forest", short: "NFO", kit: "#DD0000", trim: "#FFFFFF", ink: "#fff" },
  SUN: { name: "Sunderland", short: "SUN", kit: "#EB172B", trim: "#211E1F", ink: "#fff" },
  TOT: { name: "Tottenham", short: "TOT", kit: "#FFFFFF", trim: "#132257", ink: "#132257" },
  WHU: { name: "West Ham", short: "WHU", kit: "#7A263A", trim: "#1BB1E7", ink: "#fff" },
  WOL: { name: "Wolves", short: "WOL", kit: "#FDB913", trim: "#231F20", ink: "#2a2410" },
};

export const POS_RING: Record<number, string> = { 1: "var(--s3)", 2: "var(--s1)", 3: "var(--s0)", 4: "var(--s5)" };
export const POS_NAME: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };

export function isLight(hex: string): boolean {
  const c = hex.replace("#", "");
  if (c.length < 6) return false;
  const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) > 165;
}

export function team(code: string | null | undefined): Team {
  return (code && TEAMS[code]) || { name: code || "", short: code || "?", kit: "#39465c", trim: "#fff", ink: "#fff" };
}

// FDR (1 easy .. 5 hard) -> [bg, fg] tokens.
export function fdrColor(v: number): [string, string] {
  if (v <= 2) return ["color-mix(in srgb, var(--s0) 22%, transparent)", "var(--s0)"];
  if (v <= 2.6) return ["color-mix(in srgb, var(--s0) 14%, transparent)", "var(--s0)"];
  if (v <= 3.2) return ["var(--surface-3)", "var(--fg-dim)"];
  if (v <= 3.7) return ["color-mix(in srgb, var(--warn) 16%, transparent)", "var(--warn)"];
  return ["color-mix(in srgb, var(--bad) 16%, transparent)", "var(--bad)"];
}

export const SERIES = ["var(--s0)", "var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"];
