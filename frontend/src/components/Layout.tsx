import { NavLink, Outlet } from "react-router-dom";
import { LayoutDashboard, ClipboardList, Settings as SettingsIcon, Activity } from "lucide-react";

const NAV = [
  { to: "/planner", label: "Team Planner", icon: ClipboardList },
  { to: "/performance", label: "Model Performance", icon: LayoutDashboard },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Layout() {
  return (
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      <aside className="border-b border-border bg-surface md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-4 py-4 text-primary">
          <Activity className="h-5 w-5" aria-hidden />
          <span className="font-semibold tracking-tight">FPL Engine</span>
        </div>
        <nav className="flex gap-1 px-2 pb-2 md:flex-col">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-3 py-2 text-sm transition cursor-pointer ` +
                (isActive
                  ? "bg-primary text-on-primary"
                  : "text-muted-fg hover:bg-muted hover:text-fg")
              }
            >
              <Icon className="h-4 w-4" aria-hidden />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted-fg">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, className = "" }: {
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-card border border-border bg-surface ${className}`}>
      {title && (
        <h2 className="border-b border-border px-4 py-2.5 text-sm font-semibold text-fg">{title}</h2>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}
