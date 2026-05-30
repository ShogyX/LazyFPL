import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Search } from "lucide-react";
import { PageHeader, Card } from "../components/Layout";
import PlayerAvatar from "../components/PlayerAvatar";
import { Chip, ErrorBox, Mini, Select, Spinner, TextInput } from "../components/ui";
import {
  api, type Accuracy, type CompareRun, type HedgeWeights, type OptimalXi,
  type PlayerPrediction, type PlayerSearchResult,
} from "../lib/api";

const PALETTE = ["#1e40af", "#d97706", "#15803d", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d", "#0d9488", "#9333ea"];
type Tab = "comparison" | "trend" | "predictions" | "accuracy" | "weights" | "players";

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
          <div style={{ width: 130 }}>
            <Select value={effSeason} onChange={(e) => setSeason(e.target.value)}>
              {seasons.map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          </div>
        </Mini>
        <div className="flex flex-wrap gap-1">
          {strategies.map((s, i) => {
            const on = effPicked.includes(s);
            return (
              <Chip
                key={s}
                active={on}
                color={PALETTE[i % PALETTE.length]}
                onClick={() => setPicked(on ? effPicked.filter((x) => x !== s) : [...effPicked, s])}
              >
                {s}
              </Chip>
            );
          })}
        </div>
      </div>

      <Tabs tab={tab} onTab={setTab} />

      <div className="mt-4">
        {tab === "comparison" && <Comparison runs={all.data!.runs} season={effSeason} picked={effPicked} />}
        {tab === "trend" && <Trend runs={all.data!.runs} season={effSeason} picked={effPicked} />}
        {tab === "predictions" && <Predictions season={effSeason} version={version} />}
        {tab === "accuracy" && <AccuracyTab season={effSeason} version={version} />}
        {tab === "weights" && <Weights season={effSeason} />}
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
    ["accuracy", "Predicted vs actual"],
    ["weights", "Weight adaptation"],
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
          <TextInput style={{ width: 90 }} type="number" min={minGw} max={maxGw} value={lo} placeholder={String(minGw)} onChange={(e) => setLo(e.target.value === "" ? "" : Number(e.target.value))} />
        </Mini>
        <Mini label={`To GW (max ${maxGw})`}>
          <TextInput style={{ width: 90 }} type="number" min={minGw} max={maxGw} value={hi} placeholder={String(maxGw)} onChange={(e) => setHi(e.target.value === "" ? "" : Number(e.target.value))} />
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
    placeholderData: keepPreviousData,
  });

  const players = (data?.players ?? [])
    .filter((p) => p.name.toLowerCase().includes(q.toLowerCase()) || (p.team ?? "").toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) as number);

  const teamRows = useMemo(() => aggregateByTeam(players), [players]);

  return (
    <Card title={`Predictions — ${season || "?"} (${version})`}>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Mini label="GW"><TextInput style={{ width: 64 }} type="number" min={1} max={38} value={gw} onChange={(e) => setGw(Number(e.target.value))} /></Mini>
        <Mini label="Position">
          <div style={{ width: 96 }}>
            <Select value={pos} onChange={(e) => setPos(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">All</option><option value={1}>GK</option><option value={2}>DEF</option><option value={3}>MID</option><option value={4}>FWD</option>
            </Select>
          </div>
        </Mini>
        <Mini label="Sort by">
          <div style={{ width: 130 }}>
            <Select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="xp_next1">xP next</option><option value="xp_next6">xP next-6</option><option value="price">Price</option><option value="pred_minutes">Pred mins</option>
            </Select>
          </div>
        </Mini>
        <Mini label="Filter"><TextInput style={{ width: 150 }} placeholder="name / team" value={q} onChange={(e) => setQ(e.target.value)} /></Mini>
        <label className="flex cursor-pointer items-center gap-1.5 text-sm text-fg">
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

// ---- Predicted vs actual: accuracy, calibration, optimal-XI ----
function AccuracyTab({ season, version }: { season: string; version: string }) {
  const acc = useQuery({ queryKey: ["accuracy", season, version], queryFn: () => api.accuracy(season, version), enabled: !!season, retry: false, placeholderData: keepPreviousData });
  const oxi = useQuery({ queryKey: ["optimal-xi", season, version], queryFn: () => api.optimalXi(season, version), enabled: !!season, retry: false, placeholderData: keepPreviousData });

  if (acc.isLoading) return <Loading />;
  if (acc.error) return <ErrorBox message={String(acc.error)} />;
  const a = acc.data;
  if (!a || !a.overall) return <Card title="Predicted vs actual"><Hint>No stored predictions for {season} ({version}). Live predictions exist only for recent gameweeks.</Hint></Card>;

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Rank IC" value={fmt(a.overall.ic)} />
        <Kpi label="RMSE" value={fmt(a.overall.rmse)} />
        <Kpi label="MAE" value={fmt(a.overall.mae)} />
        <Kpi label="GWs / rows" value={`${a.overall.n_gws} / ${a.overall.n}`} />
      </div>

      <Card title="Per-GW accuracy">
        <AccuracyChart data={a} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Calibration (predicted vs realised)">
          <CalibrationChart data={a} />
          <p className="mt-2 text-xs text-muted-fg">Points by predicted-xP bucket; close to the diagonal means well-calibrated.</p>
        </Card>
        <Card title="Per-position accuracy">
          <Table
            head={["Pos", "n", "IC", "RMSE", "Bias"]}
            rows={a.per_position.map((p) => [p.position, p.n, fmt(p.ic), fmt(p.rmse), fmt(p.bias)])}
          />
        </Card>
      </div>

      <Card title="Optimal XI — predicted vs actual">
        {oxi.isLoading && <Loading />}
        {oxi.data?.totals && <OptimalXiView data={oxi.data} />}
        {oxi.data && !oxi.data.totals && <Hint>No optimal-XI history for {season}.</Hint>}
      </Card>
    </div>
  );
}

function AccuracyChart({ data }: { data: Accuracy }) {
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data.per_gw} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey="gw" tick={chartTick} />
          <YAxis yAxisId="ic" domain={[0, 1]} tick={chartTick} width={36} />
          <YAxis yAxisId="err" orientation="right" tick={chartTick} width={36} />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line yAxisId="ic" type="monotone" dataKey="ic" name="Rank IC" stroke={PALETTE[0]} strokeWidth={2} dot={{ r: 2 }} />
          <Line yAxisId="err" type="monotone" dataKey="rmse" name="RMSE" stroke={PALETTE[3]} strokeWidth={2} dot={{ r: 2 }} />
          <Line yAxisId="err" type="monotone" dataKey="mae" name="MAE" stroke={PALETTE[1]} strokeWidth={2} dot={{ r: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function CalibrationChart({ data }: { data: Accuracy }) {
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.calibration} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey="bucket" tick={chartTick} />
          <YAxis tick={chartTick} />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="mean_pred" name="Mean predicted" fill={PALETTE[0]} radius={[3, 3, 0, 0]} />
          <Bar dataKey="mean_actual" name="Mean actual" fill={PALETTE[2]} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function OptimalXiView({ data }: { data: OptimalXi }) {
  const t = data.totals!;
  const hitRate = t.sum_predicted ? (t.sum_actual / t.sum_predicted) * 100 : 0;
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-3 gap-3">
        <Kpi label="Σ predicted xP" value={t.sum_predicted.toFixed(1)} />
        <Kpi label="Σ actual pts" value={t.sum_actual.toFixed(0)} />
        <Kpi label="Realised %" value={`${hitRate.toFixed(0)}%`} />
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.gws} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey="gw" tick={chartTick} />
            <YAxis tick={chartTick} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="predicted_xi_xp" name="Predicted XI xP" fill={PALETTE[0]} radius={[3, 3, 0, 0]} />
            <Bar dataKey="actual_points" name="Actual points" fill={PALETTE[1]} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Table
        head={["GW", "Pred XI xP", "Actual", "Captain", "C pred", "C actual"]}
        rows={data.gws.map((g) => [g.gw, g.predicted_xi_xp.toFixed(1), g.actual_points.toFixed(0), g.captain ?? "—", g.captain_pred.toFixed(1), g.captain_actual.toFixed(0)])}
      />
    </div>
  );
}

// ---- Online-Hedge member weight adaptation across a season ----
function Weights({ season }: { season: string }) {
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["hedge-weights", season],
    queryFn: () => api.hedgeWeights(season),
    enabled: !!season,
    retry: false,
    staleTime: Infinity,
  });
  return (
    <Card title={`Online-Hedge weight adaptation — ${season || "?"}`}>
      <p className="mb-3 text-sm text-muted-fg">
        How the adaptive ensemble re-weights its members as the season unfolds (leakage-safe: each GW’s
        weights use only earlier results). First load replays the season and can take ~20s.
      </p>
      {(isLoading || isFetching) && <Loading />}
      {error && <ErrorBox message={String(error)} />}
      {data && !isFetching && (data.series.length === 0
        ? <Hint>No feature panel for {season}.</Hint>
        : <WeightsChart data={data} />)}
    </Card>
  );
}

function WeightsChart({ data }: { data: HedgeWeights }) {
  const rows = data.series.map((s) => ({ gw: s.gw, ...s.weights }));
  return (
    <>
      {data.train_season && <p className="mb-2 text-xs text-muted-fg">Seeded from {data.train_season} IC.</p>}
      <div className="h-96">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey="gw" tick={chartTick} />
            <YAxis domain={[0, "auto"]} tick={chartTick} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {data.members.map((m, i) => (
              <Line key={m} type="monotone" dataKey={m} stroke={PALETTE[i % PALETTE.length]} dot={false} strokeWidth={2} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
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
          <Search className="pointer-events-none absolute left-2.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-fg" />
          <TextInput className="pl-8" placeholder="Type a player name…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {search.isFetching && <Loading />}
        {search.data && (
          <ul className="grid gap-1">
            {search.data.players.map((p) => (
              <li key={p.element_id}>
                <button
                  onClick={() => setSel(p)}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition duration-150 hover:bg-muted ${sel?.element_id === p.element_id ? "bg-muted ring-1 ring-primary/40" : ""}`}
                >
                  <PlayerAvatar code={p.code} position={p.position} size={32} />
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
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
              <PlayerAvatar code={sel.code} position={sel.position} size={56} />
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

const chartTick = { fontSize: 11, fill: "var(--color-muted-foreground)" };
const tooltipStyle = { background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12, color: "var(--color-foreground)" };

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
const Loading = Spinner;
function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-fg">{children}</p>;
}
