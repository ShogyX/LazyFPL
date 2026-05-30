// Typed client for the FastAPI read API, always under "/api". In dev the Vite
// server proxies "/api" to the backend; in production the served app mounts the
// API at "/api" and serves this SPA at the root — same origin, no CORS.
const BASE = "/api";

async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const qs = params
    ? "?" +
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .flatMap(([k, v]) =>
          (Array.isArray(v) ? v : [v]).map(
            (item) => `${encodeURIComponent(k)}=${encodeURIComponent(String(item))}`,
          ),
        )
        .join("&")
    : "";
  const res = await fetch(`${BASE}${path}${qs}`);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${path} ${body}`.trim());
  }
  return res.json() as Promise<T>;
}

async function send<T>(method: "PUT" | "POST", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${path} ${txt}`.trim());
  }
  return res.json() as Promise<T>;
}

// ---- types (mirror the read API responses) ----
export type Position = "GK" | "DEF" | "MID" | "FWD";

export interface PlayerPrediction {
  element_id: number;
  name: string;
  position: Position | null;
  team: string | null;
  code: number | null;
  xp_next1: number | null;
  xp_next6: number | null;
  pred_minutes: number | null;
  price: number;
  status: string | null;
}

export interface SquadPick {
  element_id: number;
  name: string;
  position: Position | null;
  code: number | null;
  team: string | null;
  price: number;
  xp: number;
  start: boolean;
  captain: boolean;
  vice: boolean;
}

export interface Squad {
  season: string;
  gw: number;
  status: string;
  total_cost: number;
  xi_xp: number;
  formation: Record<string, number>;
  picks: SquadPick[];
}

export interface Backtest {
  id: number;
  season: string;
  strategy: string;
  start_gw: number;
  end_gw: number;
  total_points: number;
  total_hits: number;
  net_points: number;
}

export interface PlayerHistoryRow {
  gw: number;
  points: number;
  minutes: number;
  goals: number;
  assists: number;
  bonus: number;
  price: number;
}

export interface GeneralSettings {
  entry_id: number | null;
  season: string | null;
  horizon: number;
  theme: "light" | "dark";
  active_model: string;
  active_strategy: string;
  ft_value: number;
  decay_base: number;
  eo_weight: number;
  notify_email: boolean;
  notify_push: boolean;
  ev_threshold: number;
}

export interface ModelsInfo {
  versions: string[];
  strategies: string[];
  active_model: string;
  active_strategy: string;
}

export interface SettingsPayload {
  general: GeneralSettings;
  secrets: Record<string, boolean>;
  models: ModelsInfo;
}

export interface CompareGw {
  gw: number;
  points: number | null;
  hit: number | null;
  captain: number | null;
}

export interface CompareRun {
  id: number;
  season: string;
  strategy: string;
  start_gw: number;
  end_gw: number;
  total_points: number;
  total_hits: number;
  net_points: number;
  per_gw: CompareGw[];
}

export interface PlayerSearchResult {
  element_id: number;
  name: string;
  full_name: string;
  team: string | null;
  position: Position | null;
  code: number | null;
  price: number;
  status: string | null;
  predictions: Record<string, { season: string; gw: number; xp_next1: number | null; xp_next6: number | null }>;
}

export interface TrackedEntry {
  entry_id: number;
  name: string | null;
  current_event: number | null;
  bank: number;
  team_value: number;
  total_points: number | null;
  overall_rank: number | null;
  updated_at: string | null;
}

export interface TrackedPick {
  element_id: number;
  name: string | null;
  position: Position | null;
  code: number | null;
  team: string | null;
  slot: number | null;
  multiplier: number | null;
  captain: boolean;
  vice: boolean;
}

export interface TrackedDetail extends TrackedEntry {
  picks: TrackedPick[];
}

export interface AccuracyGw {
  gw: number;
  n: number;
  ic: number | null;
  rmse: number | null;
  mae: number | null;
  mean_pred: number | null;
  mean_actual: number | null;
}

export interface Accuracy {
  season: string;
  version: string;
  per_gw: AccuracyGw[];
  per_position: { position: string; n: number; ic: number | null; rmse: number | null; bias: number | null }[];
  calibration: { bucket: string; n: number; mean_pred: number | null; mean_actual: number | null }[];
  overall: { n: number; n_gws: number; ic: number | null; rmse: number | null; mae: number | null; bias: number | null } | null;
}

export interface OptimalXi {
  season: string;
  version: string;
  gws: {
    gw: number;
    predicted_xi_xp: number;
    actual_points: number;
    captain: string | null;
    captain_pred: number;
    captain_actual: number;
  }[];
  totals: { sum_predicted: number; sum_actual: number; n_gws: number } | null;
}

export interface HedgeWeights {
  eval_season: string;
  train_season: string | null;
  members: string[];
  series: { gw: number; weights: Record<string, number> }[];
}

export interface PlannerResult {
  entry_id: number;
  season: string;
  gw: number;
  kind: string;
  ev_uplift: number | null;
  confidence: number | null;
  bank: number | null;
  rationale: {
    horizon: number;
    transfers_in: { id: number; name: string; xp_next: number }[];
    transfers_out: { id: number; name: string }[];
    captain: { id: number; name: string; xp_next: number };
    gw0_hit: number;
    plan_net_xp: number;
    hold_net_xp: number | null;
    uplift: number | null;
  };
}

export const api = {
  health: () => get<{ status: string }>("/health"),
  predictions: (season: string, gw: number, version = "v1", position?: number, limit = 100) =>
    get<{ players: PlayerPrediction[] }>("/predictions", { season, gw, version, position, limit }),
  squad: (season: string, gw: number, version = "v1", budget = 1000, eo_weight = 0) =>
    get<Squad>("/squad", { season, gw, version, budget, eo_weight }),
  recommendations: (entry?: number, season?: string, limit = 20) =>
    get<{ recommendations: Record<string, unknown>[] }>("/recommendations", { entry, season, limit }),
  backtests: (season?: string, limit = 200) =>
    get<{ backtests: Backtest[] }>("/backtests", { season, limit }),
  playerHistory: (elementId: number, season: string) =>
    get<{ history: PlayerHistoryRow[] }>(`/players/${elementId}/history`, { season }),

  // ---- settings / models ----
  settings: () => get<SettingsPayload>("/settings"),
  saveSettings: (updates: Partial<GeneralSettings>) =>
    send<{ general: GeneralSettings }>("PUT", "/settings", updates),
  saveSecrets: (updates: Record<string, string | null>) =>
    send<{ secrets: Record<string, boolean> }>("PUT", "/settings/secrets", updates),
  models: () => get<ModelsInfo>("/models"),
  compareModels: (season?: string, strategy?: string[], version = "v1") =>
    get<{ runs: CompareRun[] }>("/models/compare", { season, strategy, version }),

  // ---- player search ----
  searchPlayers: (q: string, season?: string, limit = 25) =>
    get<{ players: PlayerSearchResult[] }>("/players/search", { q, season, limit }),

  // ---- predicted-vs-actual analytics ----
  accuracy: (season: string, version = "v1") => get<Accuracy>("/accuracy", { season, version }),
  optimalXi: (season: string, version = "v1") => get<OptimalXi>("/optimal-xi", { season, version }),
  hedgeWeights: (evalSeason: string, trainSeason?: string, lo?: number, hi?: number) =>
    get<HedgeWeights>("/hedge-weights", { eval_season: evalSeason, train_season: trainSeason, lo, hi }),

  // ---- tracking + planner ----
  trackedEntries: () => get<{ entries: TrackedEntry[] }>("/track"),
  trackedEntry: (entryId: number) => get<TrackedDetail>(`/track/${entryId}`),
  trackEntry: (entryId: number) => send<TrackedEntry>("POST", `/track/${entryId}`),
  planner: (entry: number, season: string, gw: number, opts?: { version?: string; horizon?: number; ft?: number; eo_weight?: number }) =>
    get<PlannerResult>("/planner", { entry, season, gw, ...opts }),
};
