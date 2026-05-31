import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Info, Search } from "lucide-react";
import { BarChart, LineChart, type Series } from "../components/charts";
import PlayerAvatar, { TeamBadge } from "../components/PlayerAvatar";
import { Card, Chip, CountUp, Eyebrow, ErrorBox, MiniBar, Segmented, Spinner, StatTile, TextInput, Hint } from "../components/ui";
import { SERIES } from "../lib/teams";
import { api, type CompareRun, type HedgeWeights, type OptimalXi, type PlayerSearchResult } from "../lib/api";

const TABS = [
  { value: "compare", label: "Compare" },
  { value: "accuracy", label: "Predicted vs actual" },
  { value: "optimal", label: "Optimal XI" },
  { value: "weights", label: "Weight adaptation" },
  { value: "players", label: "Player search" },
];

export default function ModelPerformance() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const all = useQuery({ queryKey: ["compare", "all"], queryFn: () => api.compareModels() });
  const seasons = useMemo(() => uniq(all.data?.runs.map((r) => r.season)).sort().reverse(), [all.data]);
  const [season, setSeason] = useState<string>("");
  const [tab, setTab] = useState("compare");
  const effSeason = season || seasons[0] || "";
  const version = settings.data?.general.active_model ?? "v1";

  return (
    <div className="fade-up" style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "clamp(22px,3vw,30px)", fontWeight: 800, letterSpacing: "-0.025em" }}>Model performance</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13.5, color: "var(--fg-dim)" }}>Leakage-safe walk-forward backtests · hover anything to compare.</p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center", overflowX: "auto", maxWidth: "100%" }}>
          {seasons.length > 0 && (
            <select className="seg" style={{ padding: "7px 10px", borderRadius: 9, color: "var(--fg)" }} value={effSeason} onChange={(e) => setSeason(e.target.value)}>
              {seasons.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}
          <Segmented value={tab} onChange={setTab} options={TABS} />
        </div>
      </div>
      {all.isLoading && <Spinner />}
      {all.error && <ErrorBox message={String(all.error)} />}
      {all.data && tab === "compare" && <Compare runs={all.data.runs} season={effSeason} />}
      {tab === "accuracy" && <AccuracyTab season={effSeason} version={version} />}
      {tab === "optimal" && <OptimalTab season={effSeason} version={version} />}
      {tab === "weights" && <WeightsTab season={effSeason} />}
      {tab === "players" && <PlayersTab season={effSeason} />}
    </div>
  );
}

// ---------------- Compare ----------------
function Compare({ runs, season }: { runs: CompareRun[]; season: string }) {
  const seasonRuns = useMemo(() => {
    const seen = new Set<string>(); const out: (CompareRun & { idx: number })[] = [];
    runs.filter((r) => r.season === season).forEach((r) => { if (!seen.has(r.strategy)) { seen.add(r.strategy); out.push({ ...r, idx: out.length }); } });
    return out.sort((a, b) => b.total_points - a.total_points).map((r, i) => ({ ...r, idx: i }));
  }, [runs, season]);

  const [picked, setPicked] = useState<string[] | null>(null);
  const eff = picked ?? seasonRuns.slice(0, 4).map((r) => r.strategy);
  const [metric, setMetric] = useState("cumulative");
  const [focus, setFocus] = useState<string | null>(null);
  const ngw = Math.max(1, ...seasonRuns.flatMap((r) => r.per_gw.map((g) => g.gw)));
  const [range, setRange] = useState<[number, number]>([1, 38]);
  const lo = Math.min(range[0], ngw), hi = Math.min(range[1], ngw);

  const sel = seasonRuns.filter((r) => eff.includes(r.strategy));
  const color = (r: { idx: number }) => SERIES[r.idx % 6];

  const chartData = useMemo(() => {
    const rows: Record<string, number>[] = [];
    const cum: Record<string, number> = {};
    for (let gw = 1; gw <= ngw; gw++) {
      const row: Record<string, number> = { gw };
      sel.forEach((r) => {
        const g = r.per_gw.find((p) => p.gw === gw);
        cum[r.strategy] = (cum[r.strategy] ?? 0) + (g?.points ?? 0);
        if (gw >= lo && gw <= hi && g) row[r.strategy] = metric === "cumulative" ? cum[r.strategy] : (g.points ?? 0);
      });
      if (gw >= lo && gw <= hi) rows.push(row);
    }
    return rows;
  }, [sel, metric, lo, hi, ngw]);

  const series: Series[] = sel.map((r) => ({
    key: r.strategy, label: r.strategy, color: focus && focus !== r.strategy ? "color-mix(in srgb, " + color(r) + " 38%, var(--surface))" : color(r),
    width: focus && focus !== r.strategy ? 1.3 : 2.6,
  }));
  const leader = sel.length ? sel.reduce((a, b) => (b.total_points > a.total_points ? b : a)) : null;

  if (!season) return <Hint>No backtest data.</Hint>;
  return (
    <div style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <Eyebrow>Strategies</Eyebrow>
        {seasonRuns.map((r) => (
          <Chip key={r.strategy} on={eff.includes(r.strategy)} color={color(r)}
            onClick={() => setPicked(eff.includes(r.strategy) ? eff.filter((k) => k !== r.strategy) : [...eff, r.strategy])}>
            {r.strategy}
          </Chip>
        ))}
      </div>
      <div className="cmp-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1.1fr) minmax(300px,0.9fr)", alignItems: "start" }}>
        <Card title={metric === "cumulative" ? "Cumulative points" : metric === "weekly" ? "Points per gameweek" : "Season totals"}
          right={<Segmented size="sm" value={metric} onChange={setMetric} options={[{ value: "cumulative", label: "Cumulative" }, { value: "weekly", label: "Weekly" }, { value: "totals", label: "Totals" }]} />}>
          {metric === "totals"
            ? <BarChart height={320} horizontalLabels data={sel.map((r) => ({ name: r.strategy, total: r.total_points, net: r.net_points }))} xKey="name"
                series={[{ key: "total", label: "Total", color: "var(--s1)" }, { key: "net", label: "Net (after hits)", color: "var(--s0)" }]} xFormat={(v) => String(v)} />
            : <>
                <LineChart height={320} data={chartData} xKey="gw" xFormat={(v) => "GW" + v} series={series} legend={false} />
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10, flexWrap: "wrap" }}>
                  <Eyebrow>GW range</Eyebrow>
                  <input type="range" min={1} max={ngw} value={lo} onChange={(e) => setRange([Math.min(+e.target.value, hi - 1), hi])} style={{ flex: 1, minWidth: 80 }} />
                  <input type="range" min={1} max={ngw} value={hi} onChange={(e) => setRange([lo, Math.max(+e.target.value, lo + 1)])} style={{ flex: 1, minWidth: 80 }} />
                  <span className="num" style={{ fontSize: 12, color: "var(--fg-dim)" }}>GW{lo}–{hi}</span>
                </div>
              </>}
        </Card>
        <Card title="Leaderboard" right={<Eyebrow>vs leader</Eyebrow>}>
          <div style={{ display: "grid", gap: 7 }}>
            {sel.map((r, i) => {
              const isF = focus === r.strategy; const dn = (leader?.total_points ?? 0) - r.total_points;
              return (
                <div key={r.strategy} className="tx" onMouseEnter={() => setFocus(r.strategy)} onMouseLeave={() => setFocus(null)}
                  style={{ display: "grid", gridTemplateColumns: "20px auto 1fr auto", alignItems: "center", gap: 10, padding: "9px 10px", borderRadius: 10, border: "1px solid " + (isF ? "var(--line-2)" : "var(--line)"), background: isF ? "var(--surface-2)" : "transparent" }}>
                  <span className="num" style={{ fontWeight: 800, color: i === 0 ? "var(--accent)" : "var(--fg-faint)", fontSize: 13 }}>{i + 1}</span>
                  <span style={{ width: 11, height: 11, borderRadius: 3, background: color(r) }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.strategy}</div>
                    <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--fg-faint)", marginTop: 2 }}><span className="num">net {r.net_points}</span><span className="num">{r.total_hits} hits</span></div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="display num" style={{ fontSize: 18 }}><CountUp value={r.total_points} /></div>
                    {dn > 0 ? <div className="num down" style={{ fontSize: 11, fontWeight: 700 }}>−{dn}</div> : <div className="num up" style={{ fontSize: 11, fontWeight: 700 }}>leader</div>}
                  </div>
                </div>
              );
            })}
            {sel.length === 0 && <Hint>Pick at least one strategy above to compare.</Hint>}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ---------------- Accuracy ----------------
function AccuracyTab({ season, version }: { season: string; version: string }) {
  const acc = useQuery({ queryKey: ["accuracy", season, version], queryFn: () => api.accuracy(season, version), enabled: !!season, retry: false, placeholderData: keepPreviousData });
  if (acc.isLoading) return <Spinner />;
  const a = acc.data;
  if (!a || !a.overall) return <Card title="Predicted vs actual"><Hint>No stored predictions for {season} ({version}).</Hint></Card>;
  return (
    <div style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--gap)" }}>
        <StatTile label="Rank IC" value={a.overall.ic ?? 0} decimals={3} accent sub="information coefficient" />
        <StatTile label="RMSE" value={a.overall.rmse ?? 0} decimals={2} sub="root-mean-square error" />
        <StatTile label="MAE" value={a.overall.mae ?? 0} decimals={2} sub="mean abs. error" />
        <StatTile label="Bias" value={a.overall.bias ?? 0} decimals={2} sub={`${a.overall.n.toLocaleString()} rows`} />
      </div>
      <Card title="Per-gameweek accuracy" right={<Eyebrow>IC ↑ better · error ↓ better</Eyebrow>}>
        <LineChart height={300} data={a.per_gw.map((g) => ({ gw: g.gw, ic: g.ic ?? 0, rmse: g.rmse ?? 0, mae: g.mae ?? 0 }))} xKey="gw" xFormat={(v) => "GW" + v}
          series={[{ key: "ic", label: "Rank IC", color: "var(--s0)" }, { key: "rmse", label: "RMSE", color: "var(--s4)", axis: "right" }, { key: "mae", label: "MAE", color: "var(--s3)", axis: "right" }]}
          yDomain={[0, 1]} yFormat={(v) => v.toFixed(2)} rightFormat={(v) => v.toFixed(1)} />
      </Card>
      <div className="cmp-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1fr) minmax(280px,0.8fr)", alignItems: "start" }}>
        <Card title="Calibration" right={<span style={{ color: "var(--fg-faint)" }}><Info size={14} /></span>}>
          <BarChart height={250} data={a.calibration.map((c) => ({ bucket: c.bucket, pred: c.mean_pred ?? 0, actual: c.mean_actual ?? 0 }))} xKey="bucket"
            series={[{ key: "pred", label: "Predicted", color: "var(--s2)" }, { key: "actual", label: "Actual", color: "var(--s0)" }]} xFormat={(v) => String(v)} yFormat={(v) => v.toFixed(1)} />
        </Card>
        <Card title="By position">
          <div style={{ display: "grid", gap: 9 }}>
            {a.per_position.map((p) => (
              <div key={p.position} style={{ display: "grid", gridTemplateColumns: "44px 1fr auto", alignItems: "center", gap: 10 }}>
                <span className="tag tag-flat" style={{ justifyContent: "center" }}>{p.position}</span>
                <div>
                  <MiniBar value={p.ic ?? 0} max={1} color="var(--s0)" />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 11, color: "var(--fg-faint)" }}>
                    <span className="num">RMSE {p.rmse?.toFixed(2)}</span><span className="num">bias {(p.bias ?? 0) > 0 ? "+" : ""}{p.bias?.toFixed(2)}</span>
                  </div>
                </div>
                <span className="num display" style={{ fontSize: 16, color: "var(--accent)", width: 44, textAlign: "right" }}>{p.ic?.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ---------------- Optimal XI ----------------
function OptimalTab({ season, version }: { season: string; version: string }) {
  const oxi = useQuery({ queryKey: ["optimal-xi", season, version], queryFn: () => api.optimalXi(season, version), enabled: !!season, retry: false, placeholderData: keepPreviousData });
  if (oxi.isLoading) return <Spinner />;
  const d: OptimalXi | undefined = oxi.data;
  if (!d || !d.totals) return <Card title="Optimal XI"><Hint>No optimal-XI history for {season}.</Hint></Card>;
  const realised = d.totals.sum_predicted ? (d.totals.sum_actual / d.totals.sum_predicted) * 100 : 0;
  return (
    <div style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--gap)" }}>
        <StatTile label="Σ predicted xP" value={d.totals.sum_predicted} decimals={0} />
        <StatTile label="Σ actual pts" value={d.totals.sum_actual} decimals={0} accent />
        <StatTile label="Realised" value={realised} decimals={0} suffix="%" sub="actual ÷ predicted" />
      </div>
      <Card title="Predicted XI xP vs actual points" right={<Eyebrow>per gameweek</Eyebrow>}>
        <BarChart height={320} data={d.gws.map((g) => ({ gw: g.gw, pred: g.predicted_xi_xp, actual: g.actual_points }))} xKey="gw"
          series={[{ key: "pred", label: "Predicted XI xP", color: "var(--s2)" }, { key: "actual", label: "Actual points", color: "var(--s0)" }]} xFormat={(v) => String(v)} />
      </Card>
    </div>
  );
}

// ---------------- Weights ----------------
function WeightsTab({ season }: { season: string }) {
  const hw = useQuery({ queryKey: ["hedge-weights", season], queryFn: () => api.hedgeWeights(season), enabled: !!season, retry: false, staleTime: Infinity });
  return (
    <Card title="Online-Hedge member weights" right={<span style={{ color: "var(--fg-faint)" }}><Info size={14} /></span>}>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--fg-dim)", lineHeight: 1.5 }}>
        The ensemble continuously re-weights its component predictors as the season unfolds — heavier weight to whatever forecasts best, strictly causally. First load replays the season (~20s).
      </p>
      {(hw.isLoading || hw.isFetching) && <Spinner label="Replaying season…" />}
      {hw.error && <ErrorBox message={String(hw.error)} />}
      {hw.data && !hw.isFetching && <WeightsChart data={hw.data} />}
    </Card>
  );
}
function WeightsChart({ data }: { data: HedgeWeights }) {
  if (!data.series.length) return <Hint>No feature panel for {data.eval_season}.</Hint>;
  const rows: Record<string, number>[] = data.series.map((s) => ({ gw: s.gw, ...s.weights }));
  return <LineChart height={360} data={rows} xKey="gw" xFormat={(v) => "GW" + v}
    series={data.members.map((m, i) => ({ key: m, label: m, color: SERIES[i % 6] }))} yDomain={[0, Math.max(...rows.flatMap((r) => data.members.map((m) => r[m] || 0))) * 1.1]} yFormat={(v) => v.toFixed(2)} />;
}

// ---------------- Players ----------------
function PlayersTab({ season }: { season: string }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<PlayerSearchResult | null>(null);
  const search = useQuery({ queryKey: ["search", q], queryFn: () => api.searchPlayers(q), enabled: q.length >= 2, retry: false });
  const hist = useQuery({ queryKey: ["history", sel?.element_id, season], queryFn: () => api.playerHistory(sel!.element_id, season), enabled: !!sel && !!season, retry: false });
  return (
    <div className="cmp-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1fr) minmax(300px,0.85fr)", alignItems: "start" }}>
      <Card title="Search players">
        <div style={{ position: "relative", marginBottom: 12 }}>
          <Search size={16} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--fg-faint)", zIndex: 1 }} />
          <TextInput style={{ paddingLeft: 34 }} placeholder="Name or club…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {search.isFetching && <Spinner />}
        <div style={{ display: "grid", gap: 4, maxHeight: 480, overflowY: "auto" }}>
          {search.data?.players.map((p) => {
            const xp = Object.values(p.predictions)[0]?.xp_next1;
            return (
              <button key={p.element_id} onClick={() => setSel(p)} className="tx"
                style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", alignItems: "center", gap: 11, textAlign: "left", padding: "8px 9px", borderRadius: 10, cursor: "pointer", border: "1px solid " + (sel?.element_id === p.element_id ? "var(--accent)" : "transparent"), background: sel?.element_id === p.element_id ? "var(--accent-faint)" : "var(--surface-2)" }}>
                <PlayerAvatar player={{ name: p.name, team: p.team, position: p.position, code: p.code }} size={34} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{p.name}</div>
                  <div style={{ fontSize: 11, color: "var(--fg-faint)", display: "flex", gap: 6, alignItems: "center" }}><TeamBadge code={p.team} size={15} /> {p.position} · £{p.price.toFixed(1)}</div>
                </div>
                <div className="num display" style={{ fontSize: 16, color: "var(--accent)", width: 40, textAlign: "right" }}>{xp != null ? xp.toFixed(1) : "—"}</div>
              </button>
            );
          })}
          {search.data && search.data.players.length === 0 && <Hint>No players match “{q}”.</Hint>}
          {q.length < 2 && <Hint>Type at least two letters to search.</Hint>}
        </div>
      </Card>
      {sel
        ? <Card title={`${sel.name} — ${season}`} pad={false}>
            <div className="card-b">
              <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
                <PlayerAvatar player={{ name: sel.name, team: sel.team, position: sel.position, code: sel.code }} size={56} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 19, fontWeight: 800 }}>{sel.full_name || sel.name}</div>
                  <div style={{ fontSize: 12.5, color: "var(--fg-dim)", display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}><TeamBadge code={sel.team} size={18} /> {sel.position} · £{sel.price.toFixed(1)}</div>
                </div>
              </div>
              <div className="eyebrow" style={{ marginBottom: 6 }}>Per-model xP</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
                {Object.entries(sel.predictions).map(([v, d]) => (
                  <div key={v} style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 9, padding: "9px 12px" }}>
                    <div className="eyebrow">{v} · GW{d.gw}</div>
                    <div className="display num" style={{ fontSize: 19, color: "var(--accent)" }}>{d.xp_next1?.toFixed(1) ?? "—"}</div>
                  </div>
                ))}
              </div>
              <div className="eyebrow" style={{ marginBottom: 6 }}>Gameweek returns</div>
              {hist.isLoading && <Spinner />}
              {hist.data && hist.data.history.length > 0
                ? <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px" }}>
                    <BarChart height={140} data={hist.data.history.map((h) => ({ gw: h.gw, pts: h.points }))} xKey="gw" series={[{ key: "pts", label: "Points", color: "var(--accent)" }]} legend={false} />
                  </div>
                : <Hint>No {season} history.</Hint>}
            </div>
          </Card>
        : <Card title="Player detail"><div style={{ display: "grid", placeItems: "center", minHeight: 280, gap: 10, color: "var(--fg-faint)", textAlign: "center" }}><Search size={32} /><p style={{ margin: 0, fontSize: 13, maxWidth: 220 }}>Select a player to see their per-model xP and gameweek returns.</p></div></Card>}
    </div>
  );
}

function uniq<T>(xs: T[] | undefined): T[] { return [...new Set(xs ?? [])]; }
