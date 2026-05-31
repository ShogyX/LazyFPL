import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BarChart3, Clock, LayoutGrid, Moon, Settings as SettingsIcon, Sun, Zap } from "lucide-react";
import { AppearanceContext, useAppearance } from "../lib/appearance";
import { api } from "../lib/api";

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

function useCountdown(deadlineISO: string | null | undefined) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  if (!deadlineISO) return null;
  let d = Math.max(0, new Date(deadlineISO).getTime() - now);
  const days = Math.floor(d / 86400e3); d -= days * 86400e3;
  const h = Math.floor(d / 3600e3); d -= h * 3600e3;
  const m = Math.floor(d / 60e3); d -= m * 60e3;
  const s = Math.floor(d / 1000);
  return { days, h, m, s };
}

function Topbar({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  const dl = useQuery({ queryKey: ["deadline"], queryFn: api.deadline, staleTime: 60_000, retry: false });
  const c = useCountdown(dl.data?.deadline_time);
  return (
    <header className="topbar">
      <div style={{ display: "flex", alignItems: "center", gap: 9, paddingRight: 16, borderRight: "1px solid var(--line)", whiteSpace: "nowrap" }}>
        <Clock size={15} style={{ color: "var(--fg-faint)" }} />
        <span className="eyebrow">{dl.data?.gw ? `GW${dl.data.gw} deadline` : "Deadline"}</span>
        {c
          ? <span className="num" style={{ fontWeight: 800, fontSize: 13, letterSpacing: "0.02em" }}>
              {c.days}d {String(c.h).padStart(2, "0")}:{String(c.m).padStart(2, "0")}:<span style={{ color: "var(--accent)" }}>{String(c.s).padStart(2, "0")}</span>
            </span>
          : <span className="num" style={{ fontSize: 13, color: "var(--fg-faint)" }}>—</span>}
      </div>
      <Ticker />
      <button className="btn btn-ghost" onClick={onToggle} title="Toggle theme" style={{ padding: 9, borderRadius: 10 }}>
        {dark ? <Sun size={17} /> : <Moon size={17} />}
      </button>
    </header>
  );
}

// Live ticker from the FPL feed (scores, price moves, news). Auto-scrolls;
// pauses on hover (CSS). Falls back to empty quietly if the feed is unavailable.
function Ticker() {
  const { data } = useQuery({ queryKey: ["ticker"], queryFn: () => api.ticker(24), staleTime: 45_000, refetchInterval: 60_000, retry: false });
  const items = data?.items ?? [];
  if (!items.length) return <div style={{ flex: 1 }} />;
  const doubled = [...items, ...items];
  return (
    <div style={{ overflow: "hidden", flex: 1, minWidth: 0, maskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent)" }}>
      <div className="ticker-track" style={{ display: "inline-flex", animation: "tickscroll 46s linear infinite" }}>
        {doubled.map((it, i) => (
          <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "0 18px", borderRight: "1px solid var(--line)", whiteSpace: "nowrap", fontSize: 12.5 }}>
            {it.kind === "live" && <span className="livedot" />}
            {(it.kind === "live" || it.kind === "ft") && (
              <span style={{ color: "var(--fg-dim)" }}>
                {it.kind === "ft" && <b style={{ color: "var(--fg-faint)", marginRight: 4 }}>FT</b>}
                {it.a} <b className="num" style={{ color: "var(--fg)" }}>{it.as_}–{it.bs}</b> {it.b}
                {it.min && <span className="num" style={{ marginLeft: 6, color: it.kind === "live" ? "var(--bad)" : "var(--fg-faint)" }}>{it.min}</span>}
              </span>
            )}
            {it.kind === "price" && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: it.dir === "up" ? "var(--accent)" : "var(--bad)" }}>
                {it.dir === "up" ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
                <b style={{ color: "var(--fg)" }}>{it.name}</b> <span className="num" style={{ color: "var(--fg-dim)" }}>{it.val}</span> <span className="num">{it.delta}</span>
              </span>
            )}
            {it.kind === "news" && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "var(--warn)" }}>
                <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--warn)" }} />
                <b style={{ color: "var(--fg)" }}>{it.name}</b> <span style={{ color: "var(--fg-dim)" }}>{it.note}</span>
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}
