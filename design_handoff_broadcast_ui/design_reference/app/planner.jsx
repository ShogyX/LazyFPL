/* Team Planner page. Interactive: pick captain (armband + projection update live),
   apply the transfer (swaps on the pitch), browse players (detail drawer). */
function PlannerPage() {
  const { SQUAD, byId, CAPTAIN, TRANSFER, CHIPS, PLAYERS, POS } = window.FPL;
  const [view, setView] = React.useState("team");          // team | model
  const [capId, setCapId] = React.useState(SQUAD.starters.find((p) => p.cap).id);
  const [applied, setApplied] = React.useState(false);
  const [selected, setSelected] = React.useState(null);

  // model-suggested XI: best xP per position into 3-4-3
  const modelXI = React.useMemo(() => {
    const by = (pos, n) => PLAYERS.filter((p) => p.pos === pos && p.status === "a").sort((a, b) => b.x1 - a.x1).slice(0, n);
    const st = [...by(1, 1), ...by(2, 3), ...by(3, 4), ...by(4, 3)];
    const capM = st.reduce((a, b) => (b.x1 > byId[a].x1 ? b.id : a), st[0].id);
    const bn = [by(1, 2)[1], by(2, 5)[3], by(3, 5)[4], by(4, 4)[3]].filter(Boolean);
    return {
      starters: st.map((p) => ({ id: p.id, cap: p.id === capM, vice: false })),
      bench: bn.map((p) => ({ id: p.id, cap: false, vice: false })),
    };
  }, []);

  // build starters w/ live captain + applied transfer
  const liveStarters = React.useMemo(() => {
    let s = SQUAD.starters.map((p) => ({ id: p.id, cap: p.id === capId, vice: p.id === capId ? false : p.id === 32 }));
    if (applied) s = s.map((p) => (p.id === TRANSFER.out ? { ...p, id: TRANSFER.in } : p));
    return s;
  }, [capId, applied]);

  const shown = view === "team" ? { starters: liveStarters, bench: SQUAD.bench } : modelXI;
  const xiXp = +shown.starters.reduce((s, p) => s + byId[p.id].x1 * (p.cap ? 2 : 1), 0).toFixed(1);
  const value = applied ? SQUAD.value + (byId[TRANSFER.in].price - byId[TRANSFER.out].price) : SQUAD.value;
  const bank = applied ? TRANSFER.bankAfter : SQUAD.bank;

  return (
    <div className="fade-up" style={{ display: "grid", gap: "var(--gap)" }}>
      <TeamHeader xiXp={xiXp} value={value} bank={bank} />
      <div className="planner-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1.55fr) minmax(320px,1fr)", alignItems: "start" }}>
        {/* pitch column */}
        <Card pad={false}>
          <div className="card-h">
            <h2>{view === "team" ? "Your XI" : "Model-optimal XI"}</h2>
            <div style={{ marginLeft: "auto" }}>
              <Segmented value={view} onChange={setView} options={[{ value: "team", label: "Your team" }, { value: "model", label: "Model XI" }]} />
            </div>
          </div>
          <div className="card-b">
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginBottom: 14 }}>
              <HeadStat label="Projected XI" value={xiXp} decimals={1} accent big />
              <HeadStat label="Formation" text={formationOf(shown.starters)} />
              <HeadStat label={view === "team" ? "Squad value" : "XI cost"} value={view === "team" ? value : costOf(shown.starters)} decimals={1} prefix="£" suffix="m" />
              {view === "team" && <HeadStat label="In the bank" value={bank} decimals={1} prefix="£" suffix="m" />}
            </div>
            <Pitch starters={shown.starters} bench={shown.bench} selected={selected?.id} onSelect={setSelected} />
            <p style={{ margin: "12px 2px 0", fontSize: 12, color: "var(--fg-faint)", display: "flex", alignItems: "center", gap: 6 }}>
              <Icon name="info" size={13} /> Tap any player for their projection breakdown · the captain’s points are doubled.
            </p>
          </div>
        </Card>

        {/* insight rail */}
        <div style={{ display: "grid", gap: "var(--gap)" }}>
          {selected ? (
            <PlayerDetail player={selected} onClose={() => setSelected(null)} />
          ) : (
            <React.Fragment>
              <CaptainCard capId={capId} setCapId={setCapId} onInspect={setSelected} />
              <TransferCard applied={applied} setApplied={setApplied} onInspect={setSelected} />
              <ChipsCard />
            </React.Fragment>
          )}
        </div>
      </div>
    </div>
  );
}

function formationOf(starters) {
  const c = { 2: 0, 3: 0, 4: 0 };
  starters.forEach((p) => { const pos = window.FPL.byId[p.id].pos; if (c[pos] != null) c[pos]++; });
  return `${c[2]}-${c[3]}-${c[4]}`;
}
function costOf(starters) { return +starters.reduce((s, p) => s + window.FPL.byId[p.id].price, 0).toFixed(1); }

/* ---- header KPIs ---- */
function TeamHeader({ xiXp, value, bank }) {
  const { SQUAD } = window.FPL;
  return (
    <Card pad={false}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", padding: "calc(16px*var(--dens)) var(--pad)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
          <div style={{ width: 46, height: 46, borderRadius: 12, background: "var(--accent)", color: "var(--accent-ink)", display: "grid", placeItems: "center", boxShadow: "0 10px 26px -10px var(--accent-glow)" }}>
            <Icon name="shield" size={24} stroke={2} />
          </div>
          <div>
            <div style={{ fontSize: "clamp(18px,2.4vw,23px)", fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1 }}>{SQUAD.name}</div>
            <div style={{ fontSize: 12.5, color: "var(--fg-dim)", marginTop: 3 }}>Gameweek {SQUAD.gw} · {window.FPL.SEASON} · entry {SQUAD.entry}</div>
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: "clamp(14px,2.4vw,34px)", flexWrap: "wrap" }}>
          <HeadStat label="Total points" value={SQUAD.totalPoints} />
          <HeadStat label="GW points" value={SQUAD.gwPoints} delta={+15} />
          <HeadStat label="Overall rank" value={SQUAD.rank} sub={`top ${SQUAD.rankPct}%`} />
          <HeadStat label="Live XI proj." value={xiXp} decimals={1} accent />
        </div>
      </div>
    </Card>
  );
}

function HeadStat({ label, value, text, decimals = 0, prefix = "", suffix = "", accent, delta, sub, big }) {
  return (
    <div style={{ minWidth: 78 }}>
      <div className="eyebrow" style={{ marginBottom: 5 }}>{label}</div>
      <div className="display" style={{ fontSize: big ? "clamp(24px,3vw,32px)" : "clamp(18px,2.2vw,24px)", color: accent ? "var(--accent)" : "var(--fg)" }}>
        {text != null ? text : <CountUp value={value} decimals={decimals} prefix={prefix} suffix={suffix} />}
      </div>
      {(sub || delta != null) && (
        <div style={{ marginTop: 4, fontSize: 11.5, color: "var(--fg-dim)", display: "flex", gap: 6, alignItems: "center" }}>
          {delta != null && <span className={delta >= 0 ? "up" : "down"} style={{ fontWeight: 700 }}>{delta >= 0 ? "▲" : "▼"}{Math.abs(delta)}</span>}
          {sub}
        </div>
      )}
    </div>
  );
}

/* ---- captain card: interactive candidate list ---- */
function CaptainCard({ capId, setCapId, onInspect }) {
  const { CAPTAIN, byId } = window.FPL;
  const cands = CAPTAIN.candidates;
  const picked = byId[capId];
  return (
    <Card title="Captain" right={<span className="tag tag-good"><Icon name="crown" size={12} /> Pick</span>}>
      <div style={{ display: "flex", alignItems: "center", gap: 13, marginBottom: 14 }}>
        <div style={{ position: "relative" }}>
          <KitAvatar player={picked} size={56} />
          <span style={{ position: "absolute", right: -4, bottom: -4, width: 22, height: 22, borderRadius: 999, background: "var(--accent)", color: "var(--accent-ink)", fontWeight: 800, fontSize: 12, display: "grid", placeItems: "center", border: "2px solid var(--surface)" }}>C</span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.01em" }}>{picked.name}</div>
          <div style={{ fontSize: 12.5, color: "var(--fg-dim)", display: "flex", alignItems: "center", gap: 7 }}>
            <TeamBadge code={picked.team} size={18} /> {cands.find((c) => c.id === capId)?.fix}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="display" style={{ fontSize: 30, color: "var(--accent)" }}><CountUp value={(cands.find((c) => c.id === capId)?.xp || picked.x1) * 2} decimals={1} /></div>
          <div className="eyebrow">capt. xP</div>
        </div>
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {cands.map((c) => {
          const P = byId[c.id]; const on = c.id === capId;
          return (
            <button key={c.id} onClick={() => setCapId(c.id)} className="tx"
              style={{ display: "grid", gridTemplateColumns: "auto 1fr auto auto", alignItems: "center", gap: 10, textAlign: "left",
                padding: "8px 10px", borderRadius: 10, cursor: "pointer",
                border: "1px solid " + (on ? "var(--accent)" : "var(--line)"),
                background: on ? "var(--accent-faint)" : "var(--surface-2)" }}>
              <KitAvatar player={P} size={30} ring={false} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>{P.name}</div>
                <div style={{ fontSize: 11, color: "var(--fg-faint)", display: "flex", gap: 6, alignItems: "center" }}>{c.fix} <FDRpill value={c.fdr}>{c.fdr}</FDRpill></div>
              </div>
              <div style={{ width: 64 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--fg-faint)" }}><span>{c.floor}</span><span>{c.ceiling}</span></div>
                <div style={{ position: "relative", height: 6, marginTop: 2 }}>
                  <div className="mbar" style={{ position: "absolute", inset: 0 }}><i style={{ width: "100%", background: "linear-gradient(90deg, var(--line-2), var(--accent))" }} /></div>
                  <span style={{ position: "absolute", top: -2, left: `${(c.xp / c.ceiling) * 100}%`, width: 3, height: 10, background: "var(--fg)", borderRadius: 2, transform: "translateX(-50%)" }} />
                </div>
              </div>
              <div className="num" style={{ fontWeight: 800, fontSize: 15, color: on ? "var(--accent)" : "var(--fg)", width: 34, textAlign: "right" }}>{c.xp.toFixed(1)}</div>
            </button>
          );
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--fg-faint)", display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name="target" size={13} /> Bars show floor→ceiling; the tick marks expected. EO-adjusted for rank.
      </div>
    </Card>
  );
}

/* ---- transfer card ---- */
function TransferCard({ applied, setApplied, onInspect }) {
  const { TRANSFER, byId } = window.FPL;
  const [open, setOpen] = React.useState(false);
  const out = byId[TRANSFER.out], inn = byId[TRANSFER.in];
  return (
    <Card title="Transfer" right={<span className="tag tag-good">+{TRANSFER.upliftHorizon.toFixed(1)} xP / {TRANSFER.horizon}gw</span>}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <SwapSide P={out} dir="out" onClick={() => onInspect(out)} />
        <div style={{ display: "grid", placeItems: "center", gap: 4 }}>
          <div style={{ width: 34, height: 34, borderRadius: 999, background: "var(--surface-3)", display: "grid", placeItems: "center", color: "var(--accent)" }}><Icon name="swap" size={17} /></div>
          <span className="num" style={{ fontSize: 10.5, color: "var(--fg-faint)" }}>{TRANSFER.hit ? `−${TRANSFER.hit * 4}` : "free"}</span>
        </div>
        <SwapSide P={inn} dir="in" onClick={() => onInspect(inn)} />
      </div>
      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <Meter label="GW uplift" value={TRANSFER.upliftGw} suffix=" xP" decimals={1} />
        <Meter label="Confidence" value={Math.round(TRANSFER.confidence * 100)} suffix="%" pct={TRANSFER.confidence * 100} />
      </div>
      <p style={{ margin: 0, fontSize: 12.5, color: "var(--fg-dim)", lineHeight: 1.5 }}>{TRANSFER.reason}</p>
      <div style={{ display: "flex", gap: 8, marginTop: 13 }}>
        <button className={"btn " + (applied ? "btn-ghost" : "btn-pri")} onClick={() => setApplied(!applied)} style={{ flex: 1, justifyContent: "center" }}>
          {applied ? <React.Fragment><Icon name="check" size={15} /> Applied to pitch</React.Fragment> : <React.Fragment><Icon name="swap" size={15} /> Apply transfer</React.Fragment>}
        </button>
        <button className="btn btn-ghost" onClick={() => setOpen(!open)}>Alternatives <Icon name={open ? "chevD" : "chevR"} size={15} /></button>
      </div>
      {open && (
        <div className="fade-up" style={{ display: "grid", gap: 6, marginTop: 10 }}>
          {TRANSFER.alternatives.map((a, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12.5, padding: "7px 10px", background: "var(--surface-2)", borderRadius: 8, border: "1px solid var(--line)" }}>
              <span>{a.label}</span><span className="num up" style={{ fontWeight: 700 }}>+{a.uplift.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
function SwapSide({ P, dir, onClick }) {
  return (
    <button onClick={onClick} className="tx lift" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "10px 6px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--surface-2)", cursor: "pointer" }}>
      <span className="tag" style={{ background: dir === "in" ? "var(--accent-faint)" : "color-mix(in srgb,var(--bad) 14%,transparent)", color: dir === "in" ? "var(--accent)" : "var(--bad)" }}>{dir === "in" ? "IN" : "OUT"}</span>
      <KitAvatar player={P} size={40} />
      <div style={{ fontWeight: 700, fontSize: 13 }}>{P.name}</div>
      <div className="num" style={{ fontSize: 11, color: "var(--fg-dim)" }}>£{P.price.toFixed(1)} · {P.x6.toFixed(1)} xP6</div>
    </button>
  );
}
function Meter({ label, value, suffix = "", decimals = 0, pct }) {
  return (
    <div style={{ flex: 1, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "9px 11px" }}>
      <div className="eyebrow" style={{ marginBottom: 4 }}>{label}</div>
      <div className="display" style={{ fontSize: 20, color: "var(--accent)" }}><CountUp value={value} decimals={decimals} suffix={suffix} /></div>
      {pct != null && <div style={{ marginTop: 6 }}><MiniBar value={pct} max={100} /></div>}
    </div>
  );
}

/* ---- chips timeline ---- */
function ChipsCard() {
  const { CHIPS } = window.FPL;
  const [sel, setSel] = React.useState(CHIPS[0].key);
  const cur = CHIPS.find((c) => c.key === sel);
  return (
    <Card title="Chip strategy">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        {CHIPS.map((c) => {
          const on = c.key === sel; const used = c.status === "used";
          return (
            <button key={c.key} onClick={() => setSel(c.key)} className="tx" style={{ textAlign: "left", padding: "10px 11px", borderRadius: 10, cursor: "pointer",
              border: "1px solid " + (on ? "var(--accent)" : "var(--line)"), background: on ? "var(--accent-faint)" : "var(--surface-2)", opacity: used ? 0.6 : 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 700, fontSize: 13 }}>{c.name}</span>
                {used ? <span className="tag tag-flat">used</span> : <span className="num" style={{ fontSize: 11, color: "var(--accent)", fontWeight: 700 }}>{c.best}</span>}
              </div>
              {!used && <div className="num" style={{ fontSize: 11.5, color: "var(--fg-dim)", marginTop: 3 }}>+{c.ev.toFixed(1)} EV</div>}
            </button>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "10px 12px", background: "var(--surface-2)", borderRadius: 10, border: "1px solid var(--line)" }}>
        <Icon name="spark" size={16} style={{ color: "var(--accent)", flexShrink: 0, marginTop: 1 }} />
        <p style={{ margin: 0, fontSize: 12.5, color: "var(--fg-dim)", lineHeight: 1.5 }}>{cur.note}</p>
      </div>
    </Card>
  );
}

/* ---- player detail drawer ---- */
function PlayerDetail({ player, onClose }) {
  const { POS, TEAMS, FDR } = window.FPL;
  // synth recent points (last 8 gw) around form
  const recent = React.useMemo(() => Array.from({ length: 8 }, (_, i) => Math.max(0, Math.round(player.form + Math.sin((player.id + i) * 1.3) * 3.5 + (i === 7 ? player.last - player.form : 0)))), [player.id]);
  const fixtures = React.useMemo(() => Array.from({ length: 5 }, (_, i) => { const codes = Object.keys(TEAMS).filter((t) => t !== player.team); const opp = codes[(player.id + i * 3) % codes.length]; return { opp, home: (player.id + i) % 2 === 0, fdr: Math.max(1, Math.min(5, Math.round(FDR[opp]))) }; }), [player.id]);
  return (
    <Card pad={false} className="fade-up">
      <div className="card-h">
        <button className="btn btn-ghost" onClick={onClose} style={{ padding: "6px 10px" }}><Icon name="chevR" size={15} style={{ transform: "scaleX(-1)" }} /> Back</button>
        <h2 style={{ marginLeft: 4 }}>Player</h2>
      </div>
      <div className="card-b">
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
          <KitAvatar player={player} size={62} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em" }}>{player.name}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--fg-dim)", marginTop: 4 }}>
              <TeamBadge code={player.team} size={18} /> {TEAMS[player.team].name} · {POS[player.pos]}
              {player.status !== "a" && <span className="tag tag-warn">{player.status === "d" ? "Doubtful" : "Out"}</span>}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="display num" style={{ fontSize: 24 }}>£{player.price.toFixed(1)}</div>
            <div className="eyebrow">{player.own.toFixed(0)}% owned</div>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, marginBottom: 16 }}>
          {[["xP next", player.x1.toFixed(1), true], ["xP 6gw", player.x6.toFixed(1)], ["Form", player.form.toFixed(1)], ["Pred mins", player.mins]].map(([k, v, a]) => (
            <div key={k} style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 9, padding: "9px 10px" }}>
              <div className="eyebrow" style={{ marginBottom: 3 }}>{k}</div>
              <div className="display num" style={{ fontSize: 19, color: a ? "var(--accent)" : "var(--fg)" }}>{v}</div>
            </div>
          ))}
        </div>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Last 8 GW returns</div>
        <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px", marginBottom: 16 }}>
          <BarChart height={120} data={recent.map((p, i) => ({ gw: 27 + i, pts: p }))} xKey="gw" series={[{ key: "pts", label: "Points", color: "var(--accent)" }]} legend={false} />
        </div>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Next 5 fixtures</div>
        <div style={{ display: "flex", gap: 6 }}>
          {fixtures.map((f, i) => (
            <div key={i} style={{ flex: 1, textAlign: "center", padding: "8px 4px", borderRadius: 9, ...fdrBg(f.fdr) }}>
              <div className="num" style={{ fontWeight: 800, fontSize: 13 }}>{f.opp}</div>
              <div style={{ fontSize: 10, opacity: 0.8, marginTop: 2 }}>{f.home ? "H" : "A"}</div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
function fdrBg(fdr) { const [bg, fg] = window.FDR_COLOR(fdr); return { background: bg, color: fg, border: "1px solid var(--line)" }; }

window.PlannerPage = PlannerPage;
window.PlayerDetail = PlayerDetail;
