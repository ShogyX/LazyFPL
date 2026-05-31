/* App shell: sidebar nav, live ticker, deadline countdown, theme toggle, Tweaks. */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "dark": true,
  "accent": "green",
  "density": "regular",
  "motion": "full"
}/*EDITMODE-END*/;

const ACCENT_HUE = { green: 152, cyan: 196, violet: 285, magenta: 338, coral: 32, amber: 74 };
const DENSITY_MULT = { compact: 0.9, regular: 1, comfy: 1.12 };
const MOTION_MULT = { full: 1, calm: 0.55, off: 0.001 };

function applyTweaks(t) {
  const r = document.documentElement;
  r.setAttribute("data-theme", t.dark ? "dark" : "light");
  r.style.setProperty("--accent-h", ACCENT_HUE[t.accent] ?? 152);
  r.style.setProperty("--dens", DENSITY_MULT[t.density] ?? 1);
  r.style.setProperty("--motion", MOTION_MULT[t.motion] ?? 1);
}

/* ---- deadline countdown ---- */
function useCountdown() {
  const target = React.useRef(Date.now() + 38 * 3600e3 + 23 * 60e3);
  const [now, setNow] = React.useState(Date.now());
  React.useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  let d = Math.max(0, target.current - now), days = Math.floor(d / 86400e3); d -= days * 86400e3;
  const h = Math.floor(d / 3600e3); d -= h * 3600e3; const m = Math.floor(d / 60e3); d -= m * 60e3; const s = Math.floor(d / 1000);
  return { days, h, m, s };
}

/* ---- live ticker ---- */
function Ticker() {
  const { TICKER, byId } = window.FPL;
  const render = (it, i) => {
    if (it.kind === "live" || it.kind === "ft") {
      return (
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "0 18px", borderRight: "1px solid var(--line)", whiteSpace: "nowrap" }}>
          {it.kind === "live" ? <span className="livedot" /> : <span style={{ fontSize: 10, fontWeight: 800, color: "var(--fg-faint)" }}>FT</span>}
          <TeamBadge code={it.a} size={17} /><b className="num">{it.as}</b>
          <span style={{ color: "var(--fg-faint)" }}>–</span>
          <b className="num">{it.bs}</b><TeamBadge code={it.b} size={17} />
          <span className="num" style={{ color: it.kind === "live" ? "var(--bad)" : "var(--fg-faint)", fontSize: 11, fontWeight: 700 }}>{it.min}</span>
          <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>{it.note}</span>
        </span>
      );
    }
    if (it.kind === "price") {
      return (
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "0 18px", borderRight: "1px solid var(--line)", whiteSpace: "nowrap" }}>
          <Icon name={it.dir === "up" ? "up" : "down"} size={13} style={{ color: it.dir === "up" ? "var(--accent)" : "var(--bad)" }} />
          <b style={{ fontSize: 12.5 }}>{it.name}</b>
          <span className="num" style={{ fontSize: 12, color: "var(--fg-dim)" }}>{it.val}</span>
          <span className={"num " + (it.dir === "up" ? "up" : "down")} style={{ fontSize: 11, fontWeight: 700 }}>{it.note}</span>
        </span>
      );
    }
    return (
      <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "0 18px", borderRight: "1px solid var(--line)", whiteSpace: "nowrap" }}>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--warn)" }} />
        <b style={{ fontSize: 12.5 }}>{it.name}</b><span style={{ fontSize: 12, color: "var(--fg-dim)" }}>{it.note}</span>
      </span>
    );
  };
  const items = [...TICKER, ...TICKER];
  return (
    <div className="ticker-mask" style={{ overflow: "hidden", flex: 1, minWidth: 0, maskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)" }}>
      <div className="ticker-track" style={{ display: "inline-flex", animation: "tickscroll 46s linear infinite" }}>
        {items.map(render)}
      </div>
    </div>
  );
}

/* ---- sidebar ---- */
const NAV = [
  { key: "planner", label: "Team Planner", icon: "pitch" },
  { key: "performance", label: "Model Performance", icon: "chart" },
  { key: "settings", label: "Settings", icon: "gear" },
];

function Sidebar({ active, setActive }) {
  return (
    <aside className="sidebar">
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "20px 18px 18px" }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: "var(--accent)", color: "var(--accent-ink)", display: "grid", placeItems: "center", boxShadow: "0 8px 20px -8px var(--accent-glow)" }}>
          <Icon name="bolt" size={19} stroke={2} fill="var(--accent-ink)" />
        </div>
        <div>
          <div style={{ fontWeight: 800, letterSpacing: "-0.02em", fontSize: 16, lineHeight: 1 }}>LazyFPL</div>
          <div className="eyebrow" style={{ marginTop: 3 }}>Intelligence Engine</div>
        </div>
      </div>
      <nav style={{ display: "flex", flexDirection: "column", gap: 3, padding: "6px 10px" }}>
        {NAV.map((n) => {
          const on = active === n.key;
          return (
            <button key={n.key} onClick={() => setActive(n.key)} className="tx navitem" data-on={on ? 1 : 0}>
              <Icon name={n.icon} size={18} /><span>{n.label}</span>
              {on && <span style={{ marginLeft: "auto", width: 6, height: 6, borderRadius: 999, background: "var(--accent)" }} />}
            </button>
          );
        })}
      </nav>
      <div style={{ marginTop: "auto", padding: 14 }}>
        <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 12, padding: "12px 13px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
            <span className="livedot" style={{ background: "var(--accent)" }} />
            <span className="eyebrow" style={{ color: "var(--accent)" }}>Auto-refresh on</span>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--fg-dim)", lineHeight: 1.5 }}>Prices, lineups & xP rebuilt continuously from the live FPL feed.</div>
        </div>
      </div>
    </aside>
  );
}

/* ---- topbar ---- */
function Topbar({ dark, onToggleTheme }) {
  const c = useCountdown();
  return (
    <header className="topbar">
      <div style={{ display: "flex", alignItems: "center", gap: 9, paddingRight: 16, borderRight: "1px solid var(--line)", whiteSpace: "nowrap" }}>
        <Icon name="clock" size={15} style={{ color: "var(--fg-faint)" }} />
        <span className="eyebrow">GW34 deadline</span>
        <span className="num" style={{ fontWeight: 800, fontSize: 13, letterSpacing: "0.02em" }}>
          {c.days}d {String(c.h).padStart(2, "0")}:{String(c.m).padStart(2, "0")}:<span style={{ color: "var(--accent)" }}>{String(c.s).padStart(2, "0")}</span>
        </span>
      </div>
      <Ticker />
      <button className="btn btn-ghost theme-btn" onClick={onToggleTheme} title="Toggle theme" style={{ padding: 9, borderRadius: 10 }}>
        <Icon name={dark ? "sun" : "moon"} size={17} />
      </button>
    </header>
  );
}

/* ---- root ---- */
function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [active, setActive] = React.useState(() => localStorage.getItem("lazyfpl-tab") || "planner");
  React.useEffect(() => applyTweaks(t), [t]);
  React.useEffect(() => localStorage.setItem("lazyfpl-tab", active), [active]);
  // re-arm entrance animations on each page, then force-settle so content is never
  // stuck hidden if the animation clock is throttled (background tab / capture).
  React.useEffect(() => {
    const r = document.documentElement;
    r.classList.remove("anim-settled");
    const id = setTimeout(() => r.classList.add("anim-settled"), 1300);
    return () => clearTimeout(id);
  }, [active]);

  const Page = active === "planner" ? PlannerPage : active === "performance" ? PerformancePage : SettingsPage;
  const swatch = (k) => `oklch(0.78 0.17 ${ACCENT_HUE[k]})`;

  return (
    <div className="shell">
      <Sidebar active={active} setActive={setActive} />
      <div className="main-col">
        <Topbar dark={t.dark} onToggleTheme={() => setTweak("dark", !t.dark)} />
        <main className="content" key={active}>
          <Page />
        </main>
      </div>

      <TweaksPanel>
        <TweakSection label="Appearance" />
        <TweakRadio label="Theme" value={t.dark ? "dark" : "light"} options={["dark", "light"]} onChange={(v) => setTweak("dark", v === "dark")} />
        <div className="twk-row">
          <div className="twk-lbl"><span>Accent</span></div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
            {Object.keys(ACCENT_HUE).map((k) => (
              <button key={k} onClick={() => setTweak("accent", k)} title={k}
                style={{ width: 26, height: 26, borderRadius: 8, cursor: "pointer", background: swatch(k),
                  border: t.accent === k ? "2px solid #fff" : "2px solid transparent",
                  boxShadow: t.accent === k ? "0 0 0 2px rgba(0,0,0,.3)" : "0 1px 3px rgba(0,0,0,.25)" }} />
            ))}
          </div>
        </div>
        <TweakSection label="Feel" />
        <TweakRadio label="Density" value={t.density} options={["compact", "regular", "comfy"]} onChange={(v) => setTweak("density", v)} />
        <TweakRadio label="Motion" value={t.motion} options={["full", "calm", "off"]} onChange={(v) => setTweak("motion", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
