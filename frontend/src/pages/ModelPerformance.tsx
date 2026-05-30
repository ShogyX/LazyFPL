import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Loader2, Search } from "lucide-react";
import { PageHeader, Card } from "../components/Layout";
import { api, type CompareRun, type PlayerPrediction, type PlayerSearchResult } from "../lib/api";

const PALETTE = ["#1e40af", "#d97706", "#15803d", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];
type Tab = "comparison" | "trend" | "predictions" | "players";

export default function ModelPerformance() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const all = useQuery({ queryKey: ["compare", "all"], queryFn: () => api.compareModels() });

  const seasons = useMemo(() => uniq(all.data?.runs.map((r) => r.season)).sort().reverse(), [all.data]);
  const strategies = useMemo(() => uniq(all.data?.runs.map((r) => r.strategy)).sort(), [all.data]);

  const [tab, setTab] = useState<Tab>("comparison");
  const [season, setSeason] = useState<string>("");
  const [picked, setPicked] = useState<string[]>([]);

  // Default season + a handful of strategies once data lands.
  const effSeason = season || seasons[0] || "";
  const effPicked = picked.length ? picked : strategies.slice(0, 4);

  const version = settings.data?.general.active_model ?? "v1";

  if (all.isLoading) return <><Hdr /><Loading /></>;
  if (all.error) return <><Hdr /><ErrorBox message={String(all.error)} /></>;

  return (
    <>
      <Hdr />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Mini label="Season">
          <select className={inputCls} value={effSeason} onChange={(e) => setSeason(e.target.value)}>
            {seasons.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Mini>
        <div className="flex flex-wrap gap-1">
          {strategies.map((s, i) => {
            const on = effPicked.includes(s);
            return (
              <button
                key={s}
                onClick={() => setPicked(on ? effPicked.filter((x) => x !== s) : [...effPicked, s])}
                className={`rounded-full border px-2.5 py-1 text-xs transition ${
                  on ? "border-transparent text-on-primary" : "border-border text-muted-fg hover:text-fg"
                }`}
                style={on ? { background: PALETTE[i % PALETTE.length] } : undefined}
              >
                {s}
              </button>
            );
          })}
        </div>
      </div>

      <Tabs tab={tab} onTab={setTab} />

      <div className="mt-4">
        {tab === "comparison" && <Comparison runs={all.data!.runs} season={effSeason} picked={effPicked} />}
        {tab === "trend" && <Trend runs={all.data!.runs} season={effSeason} picked={effPicked} />}
        {tab === "predictions" && <Predictions season={effSeason} version={version} />}
        {tab === "players" && <Players season={effSeason} />}
      </div>
    </>
  );
}

function Hdr() {
  return (
    <PageHeader
      title="Model Performance"
      subtitle="Compare models across seasons and gameweeks — per-GW predictions, player search, confidence, and KPIs."
    />
  );
}

function Tabs({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  const items: [Tab, string][] = [
    ["comparison", "Season comparison"],
    ["trend", "Per-GW trend"],
    ["predictions", "Predictions"],
    ["players", "Player search"],
  ];
  return (
    <div className="flex gap-1 border-b border-border">
      {items.map(([k, label]) => (
        <button
          key={k}
          onClick={() => onTab(k)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
            tab === k ? "border-primary font-medium text-fg" : "border-transparent text-muted-fg hover:text-fg"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// ---- Season comparison: bar chart of totals + KPI tiles ----
function Comparison({ runs, season, picked }: { runs: CompareRun[]; season: string; picked: string[] }) {
  const rows = runs.filter((r) => r.season === season && picked.includes(r.strategy));
  if (rows.length === 0) return <Card title="Season comparison"><Hint>Select a season and at least one strategy.</Hint></Card>;
  const data = rows.map((r) => ({ strategy: r.strategy, points: r.total_points, net: r.net_points }));
  const best = [...rows].sort((a, b) => b.total_points - a.total_points)[0];
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Best strategy" value={best.strategy} />
        <Kpi label="Best total" value={best.total_points} />
        <Kpi label="Net (best)" value={best.net_points} />
        <Kpi label="Hits (best)" value={best.total_hits} />
      </div>
      <Card title={`Total points — ${season}`}>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 40, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="strategy" angle={-30} textAnchor="end" interval={0} tick={chartTick} height={60} />
              <YAxis tick={chartTick} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="points" name="Total" radius={[3, 3, 0, 0]}>
                {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card title="Detail">
        <Table
          head={["Strategy", "GWs", "Total", "Net", "Hits"]}
          rows={rows.map((r) => [r.strategy, `${r.start_gw}–${r.end_gw}`, r.total_points, r.net_points, r.total_hits])}
        />
      </Card>
    </div>
  );
}

// ---- Per-GW trend: cumulative points line chart over a configurable range ----
function Trend({ runs, season, picked }: { runs: CompareRun[]; season: string; picked: string[] }) {
  const rows = runs.filter((r) => r.season === season && picked.includes(r.strategy));
  const allGws = uniq(rows.flatMap((r) => r.per_gw.map((g) => g.gw))).sort((a, b) => a - b);
  const [lo, setLo] = useState<number | "">("");
  const [hi, setHi] = useState<number | "">("");
  const minGw = allGws[0] ?? 1;
  const maxGw = allGws[allGws.length - 1] ?? 38;
  const loV = lo === "" ? minGw : lo;
  const hiV = hi === "" ? maxGw : hi;

  const data = useMemo(() => {
    const byGw = new Map<number, Record<string, number>>();
    for (const r of rows) {
      let cum = 0;
      for (const g of [...r.per_gw].sort((a, b) => a.gw - b.gw)) {
        cum += g.points ?? 0;
        if (g.gw < loV || g.gw > hiV) continue;
        const slot = byGw.get(g.gw) ?? { gw: g.gw };
        slot[r.strategy] = cum;
        byGw.set(g.gw, slot);
      }
    }
    return [...byGw.values()].sort((a, b) => (a.gw as number) - (b.gw as number));
  }, [rows, loV, hiV]);

  if (rows.length === 0) return <Card title="Per-GW trend"><Hint>Select a season and at least one strategy.</Hint></Card>;

  return (
    <Card title={`Cumulative points — ${season}`}>
      <div className="mb-3 flex items-end gap-3">
        <Mini label={`From GW (min ${minGw})`}>
          <input className={inputCls} style={{ width: 90 }} type="number" min={minGw} max={maxGw} value={lo} placeholder={String(minGw)} onChange={(e) => setLo(e.target.value === "" ? "" : Number(e.target.value))} />
        </Mini>
        <Mini label={`To GW (max ${maxGw})`}>
          <input className={inputCls} style={{ width: 90 }} type="number" min={minGw} max={maxGw} value={hi} placeholder={String(maxGw)} onChange={(e) => setHi(e.target.value === "" ? "" : Number(e.target.value))} />
        </Mini>
      </div>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey="gw" tick={chartTick} />
            <YAxis tick={chartTick} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {rows.map((r, i) => (
              <Line key={r.strategy} type="monotone" dataKey={r.strategy} stroke={PALETTE[picked.indexOf(r.strategy) % PALETTE.length] ?? PALETTE[i % PALETTE.length]} dot={false} strokeWidth={2} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

// ---- Sortable / filterable per-GW predictions ----
type SortKey = "xp_next1" | "xp_next6" | "price" | "pred_minutes";
function Predictions({ season, version }: { season: string; version: string }) {
  const [gw, setGw] = useState(1);
  const [pos, setPos] = useState<number | "">("");
  const [q, setQ] = useState("");
  const [byTeam, setByTeam] = useState(false);
  const [sort, setSort] = useState<SortKey>("xp_next1");

  const { data, isLoading, error } = useQuery({
    queryKey: ["predictions", season, gw, version, pos],
    queryFn: () => api.predictions(season, gw, version, pos === "" ? undefined : pos, 1000),
    enabled: !!season,
    retry: false,
  });

  const players = (data?.players ?? [])
    .filter((p) => p.name.toLowerCase().includes(q.toLowerCase()) || (p.team ?? "").toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) as number);

  const teamRows = useMemo(() => aggregateByTeam(players), [players]);

  return (
    <Card title={`Predictions — ${season || "?"} (${version})`}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Mini label="GW"><input className={inputCls} style={{ width: 64 }} type="number" min={1} max={38} value={gw} onChange={(e) => setGw(Number(e.target.value))} /></Mini>
        <Mini label="Position">
          <select className={inputCls} value={pos} onChange={(e) => setPos(e.target.value === "" ? "" : Number(e.target.value))}>
            <option value="">All</option><option value={1}>GK</option><option value={2}>DEF</option><option value={3}>MID</option><option value={4}>FWD</option>
          </select>
        </Mini>
        <Mini label="Sort by">
          <select className={inputCls} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="xp_next1">xP next</option><option value="xp_next6">xP next-6</option><option value="price">Price</option><option value="pred_minutes">Pred mins</option>
          </select>
        </Mini>
        <Mini label="Filter">
          <input className={inputCls} placeholder="name / team" value={q} onChange={(e) => setQ(e.target.value)} />
        </Mini>
        <label className="flex items-center gap-1.5 text-sm text-fg">
          <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={byTeam} onChange={(e) => setByTeam(e.target.checked)} /> By team
        </label>
      </div>
      {isLoading && <Loading />}
      {error && <Hint>No predictions for {season} GW{gw}.</Hint>}
      {data && !byTeam && (
        <Table
          head={["Player", "Team", "Pos", "xP", "xP-6", "Mins", "£"]}
          rows={players.slice(0, 300).map((p) => [p.name, p.team ?? "—", p.position ?? "—", fmt(p.xp_next1), fmt(p.xp_next6), fmt(p.pred_minutes, 0), p.price.toFixed(1)])}
        />
      )}
      {data && byTeam && (
        <Table
          head={["Team", "Players", "Σ xP", "Mean xP"]}
          rows={teamRows.map((t) => [t.team, t.n, t.sum.toFixed(1), t.mean.toFixed(2)])}
        />
      )}
    </Card>
  );
}

// ---- Player search with per-model xP + history sparkline ----
function Players({ season }: { season: string }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<PlayerSearchResult | null>(null);
  const search = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.searchPlayers(q),
    enabled: q.length >= 2,
    retry: false,
  });
  const history = useQuery({
    queryKey: ["history", sel?.element_id, season],
    queryFn: () => api.playerHistory(sel!.element_id, season),
    enabled: !!sel && !!season,
    retry: false,
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Search">
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-fg" />
          <input className={`${inputCls} w-full pl-8`} placeholder="Type a player name…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {search.isFetching && <Loading />}
        {search.data && (
          <ul className="grid gap-1">
            {search.data.players.map((p) => (
              <li key={p.element_id}>
                <button
                  onClick={() => setSel(p)}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition hover:bg-muted ${sel?.element_id === p.element_id ? "bg-muted" : ""}`}
                >
                  <span className="font-medium text-fg">{p.name}</span>
                  <span className="text-xs text-muted-fg">{p.team} · {p.position} · £{p.price.toFixed(1)}</span>
                  <span className="tnum ml-auto text-xs text-muted-fg">
                    {Object.entries(p.predictions).map(([v, d]) => `${v}: ${fmt(d.xp_next1)}`).join("  ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={sel ? `${sel.name} — ${season || "?"}` : "Player detail"}>
        {!sel && <Hint>Select a player to see per-model xP and gameweek history.</Hint>}
        {sel && (
          <div className="grid gap-3">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              {Object.entries(sel.predictions).map(([v, d]) => (
                <Stat key={v} label={`${v} xP (GW${d.gw})`} value={fmt(d.xp_next1)} />
              ))}
            </div>
            {history.isLoading && <Loading />}
            {history.error && <Hint>No {season} history for this player.</Hint>}
            {history.data && history.data.history.length > 0 && (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={history.data.history} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                    <XAxis dataKey="gw" tick={chartTick} />
                    <YAxis tick={chartTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Line type="monotone" dataKey="points" stroke={PALETTE[0]} strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

// ---- helpers & shared bits ----
function aggregateByTeam(players: PlayerPrediction[]) {
  const m = new Map<string, { team: string; n: number; sum: number }>();
  for (const p of players) {
    const team = p.team ?? "—";
    const e = m.get(team) ?? { team, n: 0, sum: 0 };
    e.n += 1;
    e.sum += p.xp_next1 ?? 0;
    m.set(team, e);
  }
  return [...m.values()].map((e) => ({ ...e, mean: e.n ? e.sum / e.n : 0 })).sort((a, b) => b.sum - a.sum);
}

function uniq<T>(xs: T[] | undefined): T[] {
  return [...new Set(xs ?? [])];
}
function fmt(v: number | null | undefined, d = 2): string {
  return v == null ? "—" : v.toFixed(d);
}

const inputCls = "rounded-md border border-border bg-bg px-2 py-1.5 text-sm text-fg outline-none focus:ring-2 focus:ring-ring";
const chartTick = { fontSize: 11, fill: "var(--color-muted-foreground)" };
const tooltipStyle = { background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12, color: "var(--color-foreground)" };

function Mini({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-0.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-fg">{label}</span>
      {children}
    </label>
  );
}
function Kpi({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-card border border-border bg-surface p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-fg">{label}</div>
      <div className="tnum mt-0.5 text-lg font-semibold text-fg">{value}</div>
    </div>
  );
}
function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="grid">
      <span className="text-[11px] uppercase tracking-wide text-muted-fg">{label}</span>
      <span className="tnum font-medium text-fg">{value ?? "—"}</span>
    </span>
  );
}
function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-fg">
            {head.map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border last:border-0 hover:bg-muted">
              {r.map((c, j) => <td key={j} className={`px-2 py-1.5 ${j === 0 ? "text-fg" : "tnum text-muted-fg"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Loading() {
  return <div className="flex items-center gap-2 text-sm text-muted-fg"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
}
function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-fg">{children}</p>;
}
function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-md border border-destructive bg-surface px-3 py-2 text-sm text-destructive">{message}</div>;
}
