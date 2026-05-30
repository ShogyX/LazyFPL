import { ChevronDown, Loader2 } from "lucide-react";
import type { ReactNode, SelectHTMLAttributes, InputHTMLAttributes, ButtonHTMLAttributes } from "react";

// Shared, consistently-styled primitives. Everything uses the design-system
// tokens (CSS vars) and a fast 150ms transition so the UI feels snappy.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-bg";

type Variant = "primary" | "secondary" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-on-primary hover:brightness-110 active:brightness-95 shadow-sm",
  secondary: "border border-border bg-surface text-fg hover:bg-muted",
  ghost: "text-muted-fg hover:bg-muted hover:text-fg",
};

export function Button({
  variant = "primary", icon, loading, done, children, className = "", disabled, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant; icon?: ReactNode; loading?: boolean; done?: boolean;
}) {
  return (
    <button
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition duration-150 disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98] ${VARIANTS[variant]} ${FOCUS} ${className}`}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative inline-flex w-full">
      <select
        className={`w-full cursor-pointer appearance-none rounded-md border border-border bg-bg px-3 py-2 pr-9 text-sm text-fg transition duration-150 hover:border-primary/50 ${FOCUS} ${className}`}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" aria-hidden />
    </div>
  );
}

export function TextInput({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-fg placeholder:text-muted-fg/70 transition duration-150 hover:border-primary/50 ${FOCUS} ${className}`}
      {...rest}
    />
  );
}

export function Toggle({ checked, onChange, label, hint }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3">
      <span>
        <span className="block text-sm font-medium text-fg">{label}</span>
        {hint && <span className="block text-xs text-muted-fg">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition duration-150 ${FOCUS} ${checked ? "bg-primary" : "bg-muted"}`}
      >
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-on-primary shadow transition-all duration-150 ${checked ? "left-[18px]" : "left-0.5"}`} />
      </button>
    </label>
  );
}

export function Chip({ active, color, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean; color?: string;
}) {
  return (
    <button
      className={`rounded-full border px-2.5 py-1 text-xs font-medium transition duration-150 active:scale-95 ${FOCUS} ${
        active ? "border-transparent text-on-primary shadow-sm" : "border-border text-muted-fg hover:border-primary/50 hover:text-fg"
      }`}
      style={active && color ? { background: color } : undefined}
      {...rest}
    />
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-fg">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className}`} />;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="grid gap-1">
      <span className="text-sm font-medium text-fg">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-fg">{hint}</span>}
    </label>
  );
}

export function Mini({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-fg">{label}</span>
      {children}
    </label>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-md border border-destructive bg-surface px-3 py-2 text-sm text-destructive">{message}</div>;
}
