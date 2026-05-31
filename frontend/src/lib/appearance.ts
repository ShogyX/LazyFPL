// Appearance "tweaks": theme + accent hue + density + motion, persisted to
// localStorage and applied as CSS variables on <html>.
import { createContext, useContext, useEffect, useState } from "react";

export type Theme = "dark" | "light";
export type Accent = "green" | "cyan" | "violet" | "magenta" | "coral" | "amber";
export type Density = "compact" | "regular" | "comfy";
export type Motion = "full" | "calm" | "off";

export interface Appearance { theme: Theme; accent: Accent; density: Density; motion: Motion }

export const ACCENT_HUE: Record<Accent, number> = { green: 152, cyan: 196, violet: 285, magenta: 338, coral: 32, amber: 74 };
const DENSITY_MULT: Record<Density, number> = { compact: 0.9, regular: 1, comfy: 1.12 };
const MOTION_MULT: Record<Motion, number> = { full: 1, calm: 0.55, off: 0.001 };

const DEFAULTS: Appearance = { theme: "dark", accent: "green", density: "regular", motion: "full" };
const KEY = "lazyfpl-appearance";

export function loadAppearance(): Appearance {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; }
  catch { return { ...DEFAULTS }; }
}

export function applyAppearance(a: Appearance): void {
  const r = document.documentElement;
  r.setAttribute("data-theme", a.theme);
  r.style.setProperty("--accent-h", String(ACCENT_HUE[a.accent] ?? 152));
  r.style.setProperty("--dens", String(DENSITY_MULT[a.density] ?? 1));
  r.style.setProperty("--motion", String(MOTION_MULT[a.motion] ?? 1));
}

export function useAppearance(): [Appearance, (patch: Partial<Appearance>) => void] {
  const [a, setA] = useState<Appearance>(loadAppearance);
  useEffect(() => { applyAppearance(a); localStorage.setItem(KEY, JSON.stringify(a)); }, [a]);
  return [a, (patch) => setA((prev) => ({ ...prev, ...patch }))];
}

export function accentSwatch(k: Accent): string { return `oklch(0.78 0.17 ${ACCENT_HUE[k]})`; }

type Ctx = { appearance: Appearance; set: (patch: Partial<Appearance>) => void };
export const AppearanceContext = createContext<Ctx | null>(null);
export function useAppearanceCtx(): Ctx {
  const ctx = useContext(AppearanceContext);
  if (!ctx) throw new Error("useAppearanceCtx outside provider");
  return ctx;
}
