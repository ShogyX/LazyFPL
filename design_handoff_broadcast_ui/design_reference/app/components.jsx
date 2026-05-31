/* Shared UI kit for the LazyFPL redesign. Exports to window. */
const { useState, useEffect, useRef, useCallback, useMemo } = React;

/* ---------------- hooks ---------------- */
function useInView(opts) {
  const ref = useRef(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (!ref.current || seen) return;
    const io = new IntersectionObserver((es) => {
      es.forEach((e) => { if (e.isIntersecting) { setSeen(true); io.disconnect(); } });
    }, opts || { threshold: 0.25 });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [seen]);
  return [ref, seen];
}

function useMotion() {
  // read --motion (0..1) to gate animations
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion")) || 1;
}

/* ---------------- CountUp ---------------- */
function CountUp({ value, decimals = 0, prefix = "", suffix = "", dur = 900, className = "", start = true }) {
  const [disp, setDisp] = useState(start ? 0 : value);
  const fromRef = useRef(0);
  const raf = useRef(0);
  useEffect(() => {
    if (!start) { setDisp(value); return; }
    const motion = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion")) || 1;
    if (motion < 0.02) { setDisp(value); return; }
    const from = fromRef.current;
    const to = value;
    const t0 = performance.now();
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    cancelAnimationFrame(raf.current);
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / (dur * motion));
      setDisp(from + (to - from) * ease(p));
      if (p < 1) raf.current = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    raf.current = requestAnimationFrame(tick);
    // fallback: guarantee the final value lands even if rAF is throttled/paused
    const safety = setTimeout(() => { setDisp(to); fromRef.current = to; }, dur * motion + 400);
    return () => { cancelAnimationFrame(raf.current); clearTimeout(safety); };
  }, [value, start]);
  const txt = prefix + Number(disp).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
  return <span className={"num " + className}>{txt}</span>;
}

/* ---------------- Card ---------------- */
function Card({ title, right, children, className = "", style, pad = true, ...rest }) {
  return (
    <section className={"card " + className} style={style} {...rest}>
      {(title || right) && (
        <div className="card-h">
          {title && <h2>{title}</h2>}
          {right && <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>{right}</div>}
        </div>
      )}
      {pad ? <div className="card-b">{children}</div> : children}
    </section>
  );
}

/* ---------------- Segmented (sliding pill) ---------------- */
function Segmented({ value, options, onChange, size }) {
  // options: [{value,label}] or [string]
  const opts = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  const wrapRef = useRef(null);
  const [pill, setPill] = useState(null);
  const idx = opts.findIndex((o) => o.value === value);
  useEffect(() => {
    const wrap = wrapRef.current; if (!wrap) return;
    const btn = wrap.querySelectorAll("button")[idx];
    if (btn) setPill({ left: btn.offsetLeft, width: btn.offsetWidth });
  }, [value, idx, opts.length]);
  return (
    <div className="seg-wrap" style={{ display: "inline-flex" }}>
      <div className="seg" ref={wrapRef} style={size === "sm" ? { padding: 2 } : null}>
        {pill && <span className="seg-pill tx" style={{ left: pill.left, width: pill.width, top: 3, bottom: 3 }} />}
        {opts.map((o) => (
          <button key={o.value} data-on={o.value === value ? 1 : 0} onClick={() => onChange(o.value)}
            style={{ position: "relative", padding: size === "sm" ? "5px 10px" : undefined, fontSize: size === "sm" ? 12 : undefined }}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------------- Chip ---------------- */
function Chip({ on, color, children, onClick, title }) {
  return (
    <button className="chip" data-on={on ? 1 : 0} onClick={onClick} title={title}
      style={on && color ? { background: color } : undefined}>
      {color && <span className="dot" style={{ background: on ? "var(--accent-ink)" : color }} />}
      {children}
    </button>
  );
}

/* ---------------- KitAvatar ---------------- */
const POS_RING = { 1: "var(--s3)", 2: "var(--s1)", 3: "var(--s0)", 4: "var(--s5)" };
function isLight(hex) {
  const c = hex.replace("#", ""); if (c.length < 6) return false;
  const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) > 165;
}
function KitAvatar({ player, size = 46, ring = true, dim }) {
  const T = window.FPL.TEAMS[player.team] || { kit: "#444", trim: "#fff", ink: "#fff" };
  const light = isLight(T.kit);
  const ink = light ? (T.trim && !isLight(T.trim) ? T.trim : "#10161f") : "#fff";
  const initials = player.name.replace(/[^A-Za-z ]/g, "").slice(0, 3).toUpperCase();
  const ringC = ring ? POS_RING[player.pos] : "transparent";
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%", position: "relative", flexShrink: 0,
      background: `radial-gradient(120% 120% at 50% 18%, color-mix(in srgb, ${T.kit} 78%, #fff 22%), ${T.kit})`,
      boxShadow: ring ? `0 0 0 2px var(--surface), 0 0 0 ${Math.max(2, size*0.05)}px ${ringC}` : "none",
      display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden",
      opacity: dim ? 0.62 : 1,
    }}>
      {/* collar arc */}
      <span style={{ position: "absolute", top: -size*0.34, left: "50%", transform: "translateX(-50%)",
        width: size*0.5, height: size*0.5, borderRadius: "50%", background: T.trim, opacity: 0.5 }} />
      <span style={{ fontWeight: 800, fontSize: size * 0.30, letterSpacing: "-0.04em", color: ink, position: "relative", lineHeight: 1 }}>{initials}</span>
    </div>
  );
}

/* ---------------- TeamBadge (small) ---------------- */
function TeamBadge({ code, size = 22 }) {
  const T = window.FPL.TEAMS[code] || { kit: "#555", trim: "#fff" };
  return (
    <span style={{ width: size, height: size, borderRadius: 6, background: T.kit, color: isLight(T.kit) ? "#10161f" : "#fff",
      display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: size * 0.4, fontWeight: 800,
      letterSpacing: "-0.03em", boxShadow: `inset 0 0 0 1.5px ${T.trim}55` }}>{code}</span>
  );
}

/* ---------------- FDR pill ---------------- */
const FDR_COLOR = (v) => {
  if (v <= 2) return ["color-mix(in srgb, var(--s0) 22%, transparent)", "var(--s0)"];
  if (v <= 2.6) return ["color-mix(in srgb, var(--s0) 14%, transparent)", "var(--s0)"];
  if (v <= 3.2) return ["var(--surface-3)", "var(--fg-dim)"];
  if (v <= 3.7) return ["color-mix(in srgb, var(--warn) 16%, transparent)", "var(--warn)"];
  return ["color-mix(in srgb, var(--bad) 16%, transparent)", "var(--bad)"];
};
function FDRpill({ value, children }) {
  const [bg, fg] = FDR_COLOR(value);
  return <span className="num" style={{ background: bg, color: fg, padding: "2px 7px", borderRadius: 6, fontSize: 12, fontWeight: 700 }}>{children ?? value.toFixed(1)}</span>;
}

/* ---------------- StatTile ---------------- */
function StatTile({ label, value, sub, accent, delta, decimals = 0, prefix = "", suffix = "", start = true, big }) {
  return (
    <div className="card lift tx" style={{ padding: "calc(15px*var(--dens))", borderRadius: "var(--radius-sm)" }}>
      <div className="eyebrow" style={{ marginBottom: 7 }}>{label}</div>
      <div className="display" style={{ fontSize: big ? "clamp(28px,4vw,40px)" : "clamp(22px,2.6vw,30px)", color: accent ? "var(--accent)" : "var(--fg)" }}>
        <CountUp value={value} decimals={decimals} prefix={prefix} suffix={suffix} start={start} />
      </div>
      {(sub || delta != null) && (
        <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--fg-dim)" }}>
          {delta != null && <span className={"num " + (delta >= 0 ? "up" : "down")} style={{ fontWeight: 700 }}>{delta >= 0 ? "▲" : "▼"} {Math.abs(delta)}</span>}
          {sub && <span>{sub}</span>}
        </div>
      )}
    </div>
  );
}

/* ---------------- MiniBar ---------------- */
function MiniBar({ value, max, color = "var(--accent)", height = 6 }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const [w, setW] = useState(0);
  useEffect(() => { const id = setTimeout(() => setW(pct), 30); return () => clearTimeout(id); }, [pct]);
  return <div className="mbar" style={{ height }}><i className="tx" style={{ width: w + "%", background: color, transitionDuration: "0.7s" }} /></div>;
}

/* ---------------- StatusDot ---------------- */
function StatusDot({ status }) {
  const map = { a: ["var(--accent)", "Available"], d: ["var(--warn)", "Doubtful"], i: ["var(--bad)", "Injured"], s: ["var(--bad)", "Suspended"], u: ["var(--fg-faint)", "Unavailable"] };
  const [c, label] = map[status] || map.a;
  if (status === "a") return null;
  return <span title={label} style={{ width: 8, height: 8, borderRadius: 999, background: c, display: "inline-block", boxShadow: `0 0 8px ${c}` }} />;
}

/* ---------------- Icon ---------------- */
const ICONS = {
  pitch: "M4 4h16v16H4z M4 12h16 M9 4a3 3 0 0 0 6 0 M9 20a3 3 0 0 1 6 0",
  chart: "M4 19V5 M4 19h16 M8 16v-5 M12 16V8 M16 16v-8 M20 16v-3",
  gear: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M19.4 13a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 2.6 14H2.5a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 2.6h0A1.7 1.7 0 0 0 11 2.5a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  crown: "M3 7l4 5 5-7 5 7 4-5-2 12H5L3 7z",
  swap: "M7 4 3 8l4 4 M3 8h13 M17 20l4-4-4-4 M21 16H8",
  spark: "M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4L12 3z M5 16l.8 2 .2.8.8.2 2 .8-2 .8-.8.2-.2.8-.8 2-.8-2-.2-.8-2-.8 2-.8.8-.2.2-.8z",
  sun: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M21 21l-4.3-4.3",
  flame: "M12 2c1 4-2 5-2 8a2 2 0 0 0 4 0c0-1 1-1 1 0a5 5 0 1 1-8.5-3.5C9 7 11 6 12 2z",
  target: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
  bolt: "M13 2 4 14h6l-1 8 9-12h-6l1-8z",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 8h.01 M11 12h1v4h1",
  shield: "M12 3l8 3v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-3z",
  trophy: "M7 4h10v3a5 5 0 0 1-10 0V4z M7 6H4v1a3 3 0 0 0 3 3 M17 6h3v1a3 3 0 0 1-3 3 M9 14h6 M10 18h4 M12 11v3",
  check: "M5 12l5 5L20 7",
  x: "M6 6l12 12 M18 6 6 18",
  up: "M12 19V5 M6 11l6-6 6 6",
  down: "M12 5v14 M18 13l-6 6-6-6",
  chevR: "M9 6l6 6-6 6",
  chevD: "M6 9l6 6 6-6",
  filter: "M3 5h18 M6 12h12 M10 19h4",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  dot: "M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
};
function Icon({ name, size = 18, stroke = 1.9, fill, style, className }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill || "none"} stroke="currentColor"
      strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={style} className={className} aria-hidden>
      {ICONS[name].split(" M").map((d, i) => <path key={i} d={(i ? "M" : "") + d} />)}
    </svg>
  );
}

/* ---------------- Tooltip wrapper (simple) ---------------- */
function InfoDot({ text }) {
  return (
    <span title={text} style={{ display: "inline-flex", color: "var(--fg-faint)", cursor: "help", verticalAlign: "middle" }}>
      <Icon name="info" size={14} />
    </span>
  );
}

Object.assign(window, {
  useInView, useMotion, CountUp, Card, Segmented, Chip, KitAvatar, TeamBadge,
  FDRpill, FDR_COLOR, StatTile, MiniBar, StatusDot, Icon, InfoDot, isLight, POS_RING,
});
