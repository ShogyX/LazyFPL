/* Model Performance — comparison-first, progressive disclosure.
   Tabs keep each view focused; the Compare view is built for easy side-by-side. */
function PerformancePage() {
  const { STRATEGIES, SEASON } = window.FPL;
  const [tab, setTab] = React.useState("compare");
  const TABS = [
    { value: "compare", label: "Compare" },
    { value: "accuracy", label: "Predicted vs actual" },
    { value: "optimal", label: "Optimal XI" },
    { value: "weights", label: "Weight adaptation" },
    { value: "players", label: "Player search" },
  ];
  return (
    <div className="fade-up" style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "clamp(22px,3vw,30px)", fontWeight: 800, letterSpacing: "-0.025em" }}>Model performance</h1>
          <p style={{ margin: "4px 0 0", fontSize: 13.5, color: "var(--fg-dim)" }}>Backtested {SEASON} · leakage-safe walk-forward · hover anything to compare.</p>
        </div>
        <div style={{ marginLeft: "auto", overflowX: "auto", maxWidth: "100%" }}>
          <Segmented value={tab} onChange={setTab} options={TABS} />
        </div>
      </div>
      {tab === "compare" && <CompareView />}
      {tab === "accuracy" && <AccuracyView />}
      {tab === "optimal" && <OptimalXiView />}
      {tab === "weights" && <WeightsView />}
      {tab === "players" && <PlayersView />}
    </div>
  );
}

/* ---------------- Compare ---------------- */
function CompareView() {
  const { STRATEGIES, NGW } = window.FPL;
  const [picked, setPicked] = React.useState(STRATEGIES.slice(0, 4).map((s) => s.key));
  const [metric, setMetric] = React.useState("cumulative");
  const [focus, setFocus] = React.useState(null);            // hovered/clicked strategy key
  const [range, setRange] = React.useState([1, NGW]);

  const sel = STRATEGIES.filter((s) => picked.includes(s.key));
  const leader = [...sel].sort((a, b) => b.total - a.total)[0];

  const chartData = React.useMemo(() => {
    const rows = [];
    for (let gw = range[0]; gw <= range[1]; gw++) {
      const row = { gw };
      sel.forEach((s) => { const g = s.per.find((p) => p.gw === gw); if (g) row[s.key] = metric === "cumulative" ? g.cum : g.points; });
      rows.push(row);
    }
    return rows;
  }, [picked, metric, range[0], range[1]]);

  const series = sel.map((s) => ({ key: s.key, label: s.name, color: SERIES[s.color], width: focus && focus !== s.key ? 1.3 : 2.6, dimmed: focus && focus !== s.key }));

  return (
    <div style={{ display: "grid", gap: "var(--gap)" }}>
      {/* strategy chips */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="eyebrow" style={{ marginRight: 2 }}>Strategies</span>
        {STRATEGIES.map((s) => (
          <Chip key={s.key} on={picked.includes(s.key)} color={SERIES[s.color]}
            onClick={() => setPicked(picked.includes(s.key) ? picked.filter((k) => k !== s.key) : [...picked, s.key])}>
            {s.name}
          </Chip>
        ))}
      </div>

      <div className="cmp-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1.1fr) minmax(300px,0.9fr)", alignItems: "start" }}>
        {/* chart */}
        <Card title={metric === "cumulative" ? "Cumulative points" : metric === "weekly" ? "Points per gameweek" : "Season totals"}
          right={<Segmented size="sm" value={metric} onChange={setMetric} options={[{ value: "cumulative", label: "Cumulative" }, { value: "weekly", label: "Weekly" }, { value: "totals", label: "Totals" }]} />}>
          {metric === "totals" ? (
            <BarChart height={320} horizontalLabels data={sel.map((s) => ({ name: s.name, total: s.total, net: s.net }))} xKey="name"
              series={[{ key: "total", label: "Total", color: "var(--s1)" }, { key: "net", label: "Net (after hits)", color: "var(--s0)" }]} yFormat={(v) => v} />
          ) : (
            <LineChart height={320} data={chartData} xKey="gw" xFormat={(v) => "GW" + v}
              series={series.map((s) => ({ ...s, color: s.dimmed ? "color-mix(in srgb," + s.color + " 38%, var(--surface))" : s.color }))} legend={false} />
          )}
          {metric !== "totals" && (
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10, flexWrap: "wrap" }}>
              <span className="eyebrow">GW range</span>
              <input type="range" min={1} max={NGW} value={range[0]} onChange={(e) => setRange([Math.min(+e.target.value, range[1] - 1), range[1]])} style={{ accentColor: "var(--accent)", flex: 1, minWidth: 80 }} />
              <input type="range" min={1} max={NGW} value={range[1]} onChange={(e) => setRange([range[0], Math.max(+e.target.value, range[0] + 1)])} style={{ accentColor: "var(--accent)", flex: 1, minWidth: 80 }} />
              <span className="num" style={{ fontSize: 12, color: "var(--fg-dim)" }}>GW{range[0]}–{range[1]}</span>
            </div>
          )}
        </Card>

        {/* ranked comparison */}
        <Card title="Leaderboard" right={<span className="eyebrow">vs leader</span>}>
          <div style={{ display: "grid", gap: 7 }}>
            {[...sel].sort((a, b) => b.total - a.total).map((s, i) => {
              const isF = focus === s.key;
              const dn = leader.total - s.total;
              return (
                <div key={s.key} className="tx" onMouseEnter={() => setFocus(s.key)} onMouseLeave={() => setFocus(null)}
                  style={{ display: "grid", gridTemplateColumns: "20px auto 1fr auto", alignItems: "center", gap: 10, padding: "9px 10px", borderRadius: 10, cursor: "default",
                    border: "1px solid " + (isF ? "var(--line-2)" : "var(--line)"), background: isF ? "var(--surface-2)" : "transparent" }}>
                  <span className="num" style={{ fontWeight: 800, color: i === 0 ? "var(--accent)" : "var(--fg-faint)", fontSize: 13 }}>{i + 1}</span>
                  <span style={{ width: 11, height: 11, borderRadius: 3, background: SERIES[s.color] }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.name}</div>
                    <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--fg-faint)", marginTop: 2 }}>
                      <span className="num">net {s.net}</span><span className="num">{s.hits} hits</span>
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="display num" style={{ fontSize: 18 }}><CountUp value={s.total} /></div>
                    {dn > 0 && <div className="num down" style={{ fontSize: 11, fontWeight: 700 }}>−{dn}</div>}
                    {dn === 0 && <div className="num up" style={{ fontSize: 11, fontWeight: 700 }}>leader</div>}
                  </div>
                </div>
              );
            })}
            {sel.length === 0 && <p style={{ fontSize: 13, color: "var(--fg-dim)", margin: "6px 2px" }}>Pick at least one strategy above to compare.</p>}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ---------------- Accuracy (predicted vs actual) ---------------- */
function AccuracyView() {
  const { ACC_GW, ACC_POS, CALIB, ACC_OVERALL } = window.FPL;
  return (
    <div style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--gap)" }}>
        <StatTile label="Rank IC" value={ACC_OVERALL.ic} decimals={3} accent sub="information coefficient" />
        <StatTile label="RMSE" value={ACC_OVERALL.rmse} decimals={2} sub="root-mean-square error" />
        <StatTile label="MAE" value={ACC_OVERALL.mae} decimals={2} sub="mean abs. error" />
        <StatTile label="Bias" value={ACC_OVERALL.bias} decimals={2} sub={`${ACC_OVERALL.n.toLocaleString()} rows`} />
      </div>
      <Card title="Per-gameweek accuracy" right={<span className="eyebrow">IC ↑ better · error ↓ better</span>}>
        <LineChart height={300} data={ACC_GW} xKey="gw" xFormat={(v) => "GW" + v}
          series={[
            { key: "ic", label: "Rank IC", color: "var(--s0)", axis: "left" },
            { key: "rmse", label: "RMSE", color: "var(--s4)", axis: "right" },
            { key: "mae", label: "MAE", color: "var(--s3)", axis: "right" },
          ]}
          yDomain={[0, 0.6]} yFormat={(v) => v.toFixed(2)} rightFormat={(v) => v.toFixed(1)} />
      </Card>
      <div className="cmp-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1fr) minmax(280px,0.8fr)", alignItems: "start" }}>
        <Card title="Calibration" right={<InfoDot text="Mean actual points per predicted-xP bucket. Equal bars = well-calibrated." />}>
          <BarChart height={250} data={CALIB} xKey="bucket"
            series={[{ key: "pred", label: "Predicted", color: "var(--s2)" }, { key: "actual", label: "Actual", color: "var(--s0)" }]}
            yFormat={(v) => v.toFixed(1)} />
        </Card>
        <Card title="By position">
          <div style={{ display: "grid", gap: 9 }}>
            {ACC_POS.map((p) => (
              <div key={p.pos} style={{ display: "grid", gridTemplateColumns: "44px 1fr auto", alignItems: "center", gap: 10 }}>
                <span className="tag tag-flat" style={{ justifyContent: "center" }}>{p.pos}</span>
                <div>
                  <MiniBar value={p.ic} max={0.5} color="var(--s0)" />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 11, color: "var(--fg-faint)" }}>
                    <span className="num">RMSE {p.rmse}</span><span className="num">bias {p.bias > 0 ? "+" : ""}{p.bias}</span>
                  </div>
                </div>
                <span className="num display" style={{ fontSize: 16, color: "var(--accent)", width: 40, textAlign: "right" }}>{p.ic.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ---------------- Optimal XI ---------------- */
function OptimalXiView() {
  const { OPTXI } = window.FPL;
  const sumP = OPTXI.reduce((a, b) => a + b.pred, 0), sumA = OPTXI.reduce((a, b) => a + b.actual, 0);
  return (
    <div style={{ display: "grid", gap: "var(--gap)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--gap)" }}>
        <StatTile label="Σ predicted xP" value={sumP} decimals={0} />
        <StatTile label="Σ actual pts" value={sumA} decimals={0} accent />
        <StatTile label="Realised" value={(sumA / sumP) * 100} decimals={0} suffix="%" sub="actual ÷ predicted" />
      </div>
      <Card title="Predicted XI xP vs actual points" right={<span className="eyebrow">per gameweek</span>}>
        <BarChart height={320} data={OPTXI} xKey="gw" xFormat={(v) => v}
          series={[{ key: "pred", label: "Predicted XI xP", color: "var(--s2)" }, { key: "actual", label: "Actual points", color: "var(--s0)" }]} />
      </Card>
    </div>
  );
}

/* ---------------- Weight adaptation ---------------- */
function WeightsView() {
  const { HEDGE, MEMBERS } = window.FPL;
  return (
    <Card title="Online-Hedge member weights" right={<InfoDot text="How the adaptive ensemble re-weights its members each GW using only earlier results (leakage-safe)." />}>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--fg-dim)", lineHeight: 1.5 }}>
        The ensemble continuously re-weights its component predictors as the season unfolds — heavier weight to whatever has been forecasting best, strictly causally.
      </p>
      <LineChart height={360} data={HEDGE} xKey="gw" xFormat={(v) => "GW" + v}
        series={MEMBERS.map((m, i) => ({ key: m, label: m, color: SERIES[i] }))}
        yDomain={[0, "auto"]} yFormat={(v) => v.toFixed(2)} />
    </Card>
  );
}

/* ---------------- Player search ---------------- */
function PlayersView() {
  const { PLAYERS, POS } = window.FPL;
  const [q, setQ] = React.useState("");
  const [pos, setPos] = React.useState("all");
  const [sel, setSel] = React.useState(null);
  const list = PLAYERS
    .filter((p) => (pos === "all" || POS[p.pos] === pos) && (p.name.toLowerCase().includes(q.toLowerCase()) || window.FPL.TEAMS[p.team].name.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => b.x1 - a.x1);
  return (
    <div className="cmp-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1fr) minmax(300px,0.85fr)", alignItems: "start" }}>
      <Card title="Search players" right={<Segmented size="sm" value={pos} onChange={setPos} options={["all", "GK", "DEF", "MID", "FWD"]} />}>
        <div style={{ position: "relative", marginBottom: 12 }}>
          <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--fg-faint)" }}><Icon name="search" size={16} /></span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or club…"
            style={{ width: "100%", padding: "10px 12px 10px 34px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--fg)", fontSize: 14 }} />
        </div>
        <div style={{ display: "grid", gap: 4, maxHeight: 460, overflowY: "auto", margin: "0 -4px", padding: "0 4px" }}>
          {list.map((p) => (
            <button key={p.id} onClick={() => setSel(p)} className="tx"
              style={{ display: "grid", gridTemplateColumns: "auto 1fr auto auto", alignItems: "center", gap: 11, textAlign: "left", padding: "8px 9px", borderRadius: 10, cursor: "pointer",
                border: "1px solid " + (sel?.id === p.id ? "var(--accent)" : "transparent"), background: sel?.id === p.id ? "var(--accent-faint)" : "var(--surface-2)" }}>
              <KitAvatar player={p} size={34} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>{p.name} <StatusDot status={p.status} /></div>
                <div style={{ fontSize: 11, color: "var(--fg-faint)", display: "flex", gap: 6, alignItems: "center" }}><TeamBadge code={p.team} size={15} /> {POS[p.pos]} · £{p.price.toFixed(1)}</div>
              </div>
              <Sparkline data={Array.from({ length: 6 }, (_, i) => Math.max(0, p.form + Math.sin((p.id + i) * 1.4) * 3))} width={64} height={26} />
              <div className="num display" style={{ fontSize: 16, color: "var(--accent)", width: 38, textAlign: "right" }}>{p.x1.toFixed(1)}</div>
            </button>
          ))}
          {list.length === 0 && <p style={{ fontSize: 13, color: "var(--fg-dim)", padding: 8 }}>No players match “{q}”.</p>}
        </div>
      </Card>
      {sel ? <PlayerDetail player={sel} onClose={() => setSel(null)} />
        : <Card title="Player detail"><div style={{ display: "grid", placeItems: "center", minHeight: 280, gap: 10, color: "var(--fg-faint)", textAlign: "center" }}>
            <Icon name="search" size={32} /><p style={{ margin: 0, fontSize: 13, maxWidth: 220 }}>Select a player to see their xP breakdown, recent returns and fixture run.</p>
          </div></Card>}
    </div>
  );
}

window.PerformancePage = PerformancePage;
