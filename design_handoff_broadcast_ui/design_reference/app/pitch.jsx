/* Broadcast FPL pitch. Players settle into formation (staggered), captain armband
   pulses, hover reveals a mini stat card, click selects. Exports window.Pitch. */
const POS_ROWS = [1, 2, 3, 4];

function PitchStripes() {
  return (
    <div aria-hidden style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: "inherit" }}>
      {/* mowing stripes */}
      <div style={{ position: "absolute", inset: 0,
        background: "repeating-linear-gradient(0deg, var(--pitch-a) 0 9.5%, var(--pitch-b) 9.5% 19%)" }} />
      {/* lighting sweep */}
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(120% 80% at 50% -10%, rgba(255,255,255,.16), transparent 55%), radial-gradient(120% 90% at 50% 120%, rgba(0,0,0,.36), transparent 60%)" }} />
      {/* markings */}
      <svg viewBox="0 0 100 130" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.5 }}>
        <g fill="none" stroke="#fff" strokeWidth="0.4">
          <rect x="3" y="3" width="94" height="124" rx="1.5" />
          <line x1="3" y1="65" x2="97" y2="65" />
          <circle cx="50" cy="65" r="13" />
          <circle cx="50" cy="65" r="0.9" fill="#fff" />
          <rect x="26" y="3" width="48" height="20" />
          <rect x="38" y="3" width="24" height="8" />
          <rect x="26" y="107" width="48" height="20" />
          <rect x="38" y="119" width="24" height="8" />
        </g>
      </svg>
    </div>
  );
}

function Shirt({ pick, i, selected, onSelect, dim, showMeta = true }) {
  const P = window.FPL.byId[pick.id];
  const motion = useMotion();
  const [hover, setHover] = React.useState(false);
  if (!P) return null;
  const isSel = selected === pick.id;
  return (
    <div
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onClick={() => onSelect && onSelect(P)}
      style={{ position: "relative", width: dim ? 60 : 74, display: "flex", flexDirection: "column", alignItems: "center",
        cursor: "pointer", animation: `popIn ${0.5 / motion}s cubic-bezier(.2,.8,.3,1) ${0.05 + i * 0.04}s both`,
        zIndex: hover ? 30 : 1 }}>
      <div className="tx" style={{ transform: hover ? "translateY(-4px)" : "none", position: "relative" }}>
        <KitAvatar player={P} size={dim ? 42 : 50} dim={dim} />
        {/* captain / vice armband */}
        {pick.cap && (
          <span style={{ position: "absolute", right: -5, top: -5, width: 21, height: 21, borderRadius: 999,
            background: "var(--accent)", color: "var(--accent-ink)", fontWeight: 800, fontSize: 11,
            display: "flex", alignItems: "center", justifyContent: "center", border: "2px solid var(--surface)",
            animation: `pulseRing ${1.8 / motion}s ease-out infinite` }}>C</span>
        )}
        {pick.vice && !pick.cap && (
          <span style={{ position: "absolute", right: -5, top: -5, width: 20, height: 20, borderRadius: 999,
            background: "var(--surface-3)", color: "var(--fg)", fontWeight: 800, fontSize: 10,
            display: "flex", alignItems: "center", justifyContent: "center", border: "2px solid var(--surface)" }}>V</span>
        )}
        {P.status !== "a" && (
          <span style={{ position: "absolute", left: -3, top: -3 }}><StatusDot status={P.status} /></span>
        )}
        {isSel && <span style={{ position: "absolute", inset: -5, borderRadius: 999, border: "2px solid var(--accent)", boxShadow: "0 0 14px var(--accent-glow)" }} />}
      </div>
      {/* name plate */}
      <div style={{ marginTop: 6, width: "100%", textAlign: "center" }}>
        <div style={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 6, padding: "2px 5px",
          fontSize: 11.5, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          boxShadow: "0 4px 10px -6px rgba(0,0,0,.6)" }}>{P.name}</div>
        {showMeta && (
          <div className="num" style={{ marginTop: 2, fontSize: 11, fontWeight: 800, color: "var(--accent)" }}>
            {(P.x1 * (pick.cap ? 2 : 1)).toFixed(1)} <span style={{ color: "var(--fg-faint)", fontWeight: 600 }}>xP</span>
          </div>
        )}
      </div>
      {/* hover mini-card */}
      {hover && (
        <div className="fade-up" style={{ position: "absolute", bottom: "calc(100% + 6px)", left: "50%", transform: "translateX(-50%)",
          width: 168, background: "var(--surface-3)", border: "1px solid var(--line-2)", borderRadius: 10, padding: 10,
          boxShadow: "var(--shadow)", pointerEvents: "none", zIndex: 40 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 7 }}>
            <TeamBadge code={P.team} size={20} />
            <b style={{ fontSize: 13 }}>{P.name}</b>
            <span className="num" style={{ marginLeft: "auto", fontSize: 12, color: "var(--fg-dim)" }}>£{P.price.toFixed(1)}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px 10px", fontSize: 11.5 }}>
            <MiniStat k="xP next" v={P.x1.toFixed(1)} accent />
            <MiniStat k="xP 6gw" v={P.x6.toFixed(1)} />
            <MiniStat k="Form" v={P.form.toFixed(1)} />
            <MiniStat k="Owned" v={P.own.toFixed(0) + "%"} />
          </div>
        </div>
      )}
    </div>
  );
}
function MiniStat({ k, v, accent }) {
  return <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ color: "var(--fg-faint)" }}>{k}</span><span className="num" style={{ fontWeight: 700, color: accent ? "var(--accent)" : "var(--fg)" }}>{v}</span></div>;
}

function Pitch({ starters, bench, selected, onSelect, showMeta = true }) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ position: "relative", borderRadius: "var(--radius)", overflow: "hidden", padding: "20px 10px 14px",
        boxShadow: "inset 0 0 0 1px rgba(255,255,255,.06), inset 0 30px 80px -40px rgba(0,0,0,.5)" }}>
        <PitchStripes />
        <div style={{ position: "relative", display: "grid", gap: "calc(8px + 0.6vw)", paddingBottom: 4 }}>
          {POS_ROWS.map((row) => {
            const inRow = starters.filter((p) => window.FPL.byId[p.id]?.pos === row);
            if (!inRow.length) return null;
            return (
              <div key={row} style={{ display: "flex", justifyContent: "center", gap: "clamp(6px, 2vw, 26px)", flexWrap: "wrap" }}>
                {inRow.map((p, i) => <Shirt key={p.id} pick={p} i={i} selected={selected} onSelect={onSelect} showMeta={showMeta} />)}
              </div>
            );
          })}
        </div>
      </div>
      {bench && bench.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", padding: "10px 14px",
          background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "var(--radius)" }}>
          <span className="eyebrow" style={{ writingMode: "horizontal-tb" }}>Bench</span>
          <div style={{ display: "flex", gap: "clamp(8px,2vw,22px)", flexWrap: "wrap", flex: 1, justifyContent: "center" }}>
            {bench.map((p, i) => <Shirt key={p.id} pick={p} i={i} selected={selected} onSelect={onSelect} dim showMeta={showMeta} />)}
          </div>
        </div>
      )}
    </div>
  );
}

window.Pitch = Pitch;
