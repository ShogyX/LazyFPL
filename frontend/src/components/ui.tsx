import {
  useEffect, useRef, useState, type ButtonHTMLAttributes, type CSSProperties,
  type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
} from "react";
import { ChevronDown, Loader2 } from "lucide-react";

// ---- motion + count-up -----------------------------------------------------
export function motionScale(): number {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion")) || 1;
}

// Animates 0->value (easeOutCubic). Always lands on the real value even if rAF
// is throttled (background tab) via a setTimeout fallback.
export function useCountUp(value: number, dur = 900): number {
  const [disp, setDisp] = useState(value);
  const from = useRef(0);
  useEffect(() => {
    const m = motionScale();
    if (m < 0.02) { setDisp(value); from.current = value; return; }
    const start = performance.now(), a = from.current, b = value;
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / (dur * m));
      setDisp(a + (b - a) * ease(p));
      if (p < 1) raf = requestAnimationFrame(tick); else from.current = b;
    };
    raf = requestAnimationFrame(tick);
    const safety = setTimeout(() => { setDisp(b); from.current = b; }, dur * m + 400);
    return () => { cancelAnimationFrame(raf); clearTimeout(safety); };
  }, [value, dur]);
  return disp;
}

export function CountUp({ value, decimals = 0, prefix = "", suffix = "", className = "" }:
  { value: number; decimals?: number; prefix?: string; suffix?: string; className?: string }) {
  const d = useCountUp(value);
  const txt = prefix + d.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
  return <span className={"num " + className}>{txt}</span>;
}

// ---- Card ------------------------------------------------------------------
export function Card({ title, right, children, className = "", style, pad = true }:
  { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; style?: CSSProperties; pad?: boolean }) {
  return (
    <section className={"card " + className} style={style}>
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

// ---- Segmented (sliding pill) ---------------------------------------------
type Opt = { value: string; label: ReactNode };
export function Segmented({ value, options, onChange, size }:
  { value: string; options: (string | Opt)[]; onChange: (v: string) => void; size?: "sm" }) {
  const opts: Opt[] = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  const wrap = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);
  const idx = opts.findIndex((o) => o.value === value);
  useEffect(() => {
    const btn = wrap.current?.querySelectorAll("button")[idx] as HTMLElement | undefined;
    if (btn) setPill({ left: btn.offsetLeft, width: btn.offsetWidth });
  }, [value, idx, opts.length]);
  return (
    <div className="seg-wrap" style={{ display: "inline-flex" }}>
      <div className="seg" ref={wrap} style={size === "sm" ? { padding: 2 } : undefined}>
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

// ---- Chip ------------------------------------------------------------------
export function Chip({ on, color, children, onClick, title }:
  { on?: boolean; color?: string; children: ReactNode; onClick?: () => void; title?: string }) {
  return (
    <button className="chip" data-on={on ? 1 : 0} onClick={onClick} title={title}
      style={on && color ? { background: color } : undefined}>
      {color && <span className="dot" style={{ background: on ? "var(--accent-ink)" : color }} />}
      {children}
    </button>
  );
}

// ---- Button ----------------------------------------------------------------
export function Button({ variant = "ghost", icon, loading, children, className = "", disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "pri" | "ghost"; icon?: ReactNode; loading?: boolean }) {
  return (
    <button className={`btn btn-${variant} ${className}`} disabled={disabled || loading} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ---- StatTile / MiniBar / StatusDot / FDR pill -----------------------------
export function StatTile({ label, value, sub, accent, delta, decimals = 0, prefix = "", suffix = "", big }:
  { label: string; value: number; sub?: ReactNode; accent?: boolean; delta?: number; decimals?: number; prefix?: string; suffix?: string; big?: boolean }) {
  return (
    <div className="card lift tx" style={{ padding: "calc(15px*var(--dens))", borderRadius: "var(--radius-sm)" }}>
      <div className="eyebrow" style={{ marginBottom: 7 }}>{label}</div>
      <div className="display" style={{ fontSize: big ? "clamp(28px,4vw,40px)" : "clamp(22px,2.6vw,30px)", color: accent ? "var(--accent)" : "var(--fg)" }}>
        <CountUp value={value} decimals={decimals} prefix={prefix} suffix={suffix} />
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

export function MiniBar({ value, max, color = "var(--accent)", height = 6 }:
  { value: number; max: number; color?: string; height?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const [w, setW] = useState(0);
  useEffect(() => { const id = setTimeout(() => setW(pct), 30); return () => clearTimeout(id); }, [pct]);
  return <div className="mbar" style={{ height }}><i className="tx" style={{ width: w + "%", background: color, transitionDuration: "0.7s" }} /></div>;
}

const STATUS: Record<string, [string, string]> = {
  a: ["var(--accent)", "Available"], d: ["var(--warn)", "Doubtful"], i: ["var(--bad)", "Injured"],
  s: ["var(--bad)", "Suspended"], u: ["var(--fg-faint)", "Unavailable"], n: ["var(--bad)", "Unavailable"],
};
export function StatusDot({ status }: { status: string | null | undefined }) {
  if (!status || status === "a") return null;
  const [c, label] = STATUS[status] || STATUS.u;
  return <span title={label} style={{ width: 8, height: 8, borderRadius: 999, background: c, display: "inline-block", boxShadow: `0 0 8px ${c}` }} />;
}

// ---- form fields -----------------------------------------------------------
export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 6 }}>
      <span style={{ fontSize: 13.5, fontWeight: 600 }}>{label}</span>
      {children}
      {hint && <span style={{ fontSize: 12, color: "var(--fg-faint)" }}>{hint}</span>}
    </label>
  );
}

export function Mini({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 4 }}>
      <span className="eyebrow">{label}</span>
      {children}
    </label>
  );
}

const inputStyle: CSSProperties = {
  width: "100%", padding: "9px 11px", borderRadius: 9, border: "1px solid var(--line)",
  background: "var(--surface-2)", color: "var(--fg)", fontSize: 13.5,
};
export function TextInput({ style, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="tx" style={{ ...inputStyle, ...style }} {...rest} />;
}

export function Select({ style, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div style={{ position: "relative" }}>
      <select className="tx" style={{ ...inputStyle, appearance: "none", paddingRight: 32, cursor: "pointer", ...style }} {...rest}>
        {children}
      </select>
      <ChevronDown size={15} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--fg-faint)" }} />
    </div>
  );
}

export function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)} className="tx"
      style={{ position: "relative", width: 44, height: 25, borderRadius: 999, border: "1px solid var(--line)", cursor: "pointer", background: checked ? "var(--accent)" : "var(--surface-3)", flexShrink: 0 }}>
      <span className="tx" style={{ position: "absolute", top: 2, left: checked ? 21 : 2, width: 19, height: 19, borderRadius: 999, background: checked ? "var(--accent-ink)" : "var(--fg-dim)" }} />
    </button>
  );
}

export function Slider({ value, min, max, step = 1, onChange, decimals = 0, suffix = "" }:
  { value: number; min: number; max: number; step?: number; onChange: (v: number) => void; decimals?: number; suffix?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} style={{ flex: 1 }} />
      <span className="num" style={{ minWidth: 52, textAlign: "right", fontWeight: 700, fontSize: 13.5, color: "var(--accent)" }}>{value.toFixed(decimals)}{suffix}</span>
    </div>
  );
}

// ---- misc ------------------------------------------------------------------
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--fg-dim)" }}><Loader2 className="h-4 w-4 animate-spin" /> {label}</div>;
}
export function ErrorBox({ message }: { message: string }) {
  return <div style={{ borderRadius: 9, border: "1px solid var(--bad)", background: "var(--surface)", padding: "9px 12px", fontSize: 13, color: "var(--bad)" }}>{message}</div>;
}
export function Hint({ children }: { children: ReactNode }) {
  return <p style={{ margin: 0, fontSize: 13, color: "var(--fg-dim)" }}>{children}</p>;
}
export function Eyebrow({ children }: { children: ReactNode }) { return <span className="eyebrow">{children}</span>; }

// Engine confidence (0-100): green high → amber mid → red low.
export function Conf({ v, label }: { v: number; label?: boolean }) {
  const c = v >= 70 ? "var(--accent)" : v >= 40 ? "var(--warn)" : "var(--bad)";
  return (
    <span title={`Engine confidence ${v}%`} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700 }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: c, boxShadow: `0 0 6px ${c}` }} />
      <span className="num" style={{ color: c }}>{v}%</span>
      {label && <span style={{ color: "var(--fg-faint)", fontWeight: 600 }}>conf</span>}
    </span>
  );
}
