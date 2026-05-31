import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { BarChart3, Clock, LayoutGrid, Moon, Settings as SettingsIcon, Sun, Zap } from "lucide-react";
import { AppearanceContext, useAppearance } from "../lib/appearance";

const NAV = [
  { to: "/planner", label: "Team Planner", icon: LayoutGrid },
  { to: "/performance", label: "Model Performance", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Layout() {
  const [appearance, set] = useAppearance();
  // Re-arm + force-settle entrance animations so nothing is stuck hidden.
  useEffect(() => {
    const r = document.documentElement;
    r.classList.remove("anim-settled");
    const id = setTimeout(() => r.classList.add("anim-settled"), 1300);
    return () => clearTimeout(id);
  }, []);

  return (
    <AppearanceContext.Provider value={{ appearance, set }}>
      <div className="shell">
        <Sidebar />
        <div className="main-col">
          <Topbar dark={appearance.theme === "dark"} onToggle={() => set({ theme: appearance.theme === "dark" ? "light" : "dark" })} />
          <main className="content">
            <Outlet />
          </main>
        </div>
      </div>
    </AppearanceContext.Provider>
  );
}

function Sidebar() {
  return (
    <aside className="sidebar">
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "20px 18px 18px" }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: "var(--accent)", color: "var(--accent-ink)", display: "grid", placeItems: "center", boxShadow: "0 8px 20px -8px var(--accent-glow)" }}>
          <Zap size={19} fill="var(--accent-ink)" />
        </div>
        <div>
          <div style={{ fontWeight: 800, letterSpacing: "-0.02em", fontSize: 16, lineHeight: 1 }}>LazyFPL</div>
          <div className="eyebrow" style={{ marginTop: 3 }}>Intelligence Engine</div>
        </div>
      </div>
      <nav style={{ display: "flex", flexDirection: "column", gap: 3, padding: "6px 10px" }}>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className="tx navitem">
            {({ isActive }) => (
              <>
                <Icon size={18} /><span>{label}</span>
                {isActive && <span style={{ marginLeft: "auto", width: 6, height: 6, borderRadius: 999, background: "var(--accent)" }} />}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div style={{ marginTop: "auto", padding: 14 }}>
        <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 12, padding: "12px 13px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
            <span className="livedot" style={{ background: "var(--accent)" }} />
            <span className="eyebrow" style={{ color: "var(--accent)" }}>Auto-refresh on</span>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--fg-dim)", lineHeight: 1.5 }}>Prices, lineups &amp; xP rebuilt continuously from the live FPL feed.</div>
        </div>
      </div>
    </aside>
  );
}

function useCountdown() {
  const target = useRef(Date.now() + 38 * 3600e3);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  let d = Math.max(0, target.current - now);
  const days = Math.floor(d / 86400e3); d -= days * 86400e3;
  const h = Math.floor(d / 3600e3); d -= h * 3600e3;
  const m = Math.floor(d / 60e3); d -= m * 60e3;
  const s = Math.floor(d / 1000);
  return { days, h, m, s };
}

function Topbar({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  const c = useCountdown();
  return (
    <header className="topbar">
      <div style={{ display: "flex", alignItems: "center", gap: 9, paddingRight: 16, borderRight: "1px solid var(--line)", whiteSpace: "nowrap" }}>
        <Clock size={15} style={{ color: "var(--fg-faint)" }} />
        <span className="eyebrow">Next deadline</span>
        <span className="num" style={{ fontWeight: 800, fontSize: 13, letterSpacing: "0.02em" }}>
          {c.days}d {String(c.h).padStart(2, "0")}:{String(c.m).padStart(2, "0")}:<span style={{ color: "var(--accent)" }}>{String(c.s).padStart(2, "0")}</span>
        </span>
      </div>
      <Ticker />
      <button className="btn btn-ghost" onClick={onToggle} title="Toggle theme" style={{ padding: 9, borderRadius: 10 }}>
        {dark ? <Sun size={17} /> : <Moon size={17} />}
      </button>
    </header>
  );
}

// Static-but-representative ticker (auto-scroll, pause on hover). A live feed
// would derive items from predictions status/news + fixtures.
const TICKER: { kind: string; text: string; tone?: string }[] = [
  { kind: "live", text: "LIV 2–0 BUR · 67' · Salah 1G 1A", tone: "live" },
  { kind: "live", text: "MCI 3–1 WOL · 72' · Haaland 2G", tone: "live" },
  { kind: "ft", text: "ARS 1–1 NEW · FT" },
  { kind: "price", text: "▲ Semenyo £7.3 (+0.1)", tone: "up" },
  { kind: "price", text: "▼ B.Fernandes £9.0 (−0.1)", tone: "down" },
  { kind: "news", text: "Eze — knock, 75% GW next", tone: "warn" },
];
function Ticker() {
  const items = [...TICKER, ...TICKER];
  return (
    <div style={{ overflow: "hidden", flex: 1, minWidth: 0, maskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)" }}>
      <div className="ticker-track" style={{ display: "inline-flex", animation: "tickscroll 46s linear infinite" }}>
        {items.map((it, i) => (
          <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "0 18px", borderRight: "1px solid var(--line)", whiteSpace: "nowrap", fontSize: 12.5 }}>
            {it.tone === "live" && <span className="livedot" />}
            <span style={{ color: it.tone === "up" ? "var(--accent)" : it.tone === "down" ? "var(--bad)" : it.tone === "warn" ? "var(--warn)" : "var(--fg-dim)" }}>{it.text}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
