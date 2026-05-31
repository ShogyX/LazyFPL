import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Bell, Check, KeyRound, Palette, Shield, Target } from "lucide-react";
import { Card, Field, Select, Slider, Spinner, TextInput, Toggle } from "../components/ui";
import { ACCENT_HUE, accentSwatch, useAppearanceCtx, type Accent, type Density, type Motion } from "../lib/appearance";
import { api, type GeneralSettings, type SettingsPayload } from "../lib/api";

const SECRETS = [
  { key: "api_football_key", label: "API-Football key", hint: "lineups · injuries · referees" },
  { key: "fpl_session_cookie", label: "FPL session cookie", hint: "authed /my-team prices & bank" },
  { key: "smtp_password", label: "SMTP password", hint: "for email alerts" },
  { key: "pushover_token", label: "Pushover token", hint: "for push alerts" },
];

export default function Settings() {
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  return (
    <div className="fade-up" style={{ display: "grid", gap: "var(--gap)", maxWidth: 1120 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "clamp(22px,3vw,30px)", fontWeight: 800, letterSpacing: "-0.025em" }}>Settings</h1>
        <p style={{ margin: "4px 0 0", fontSize: 13.5, color: "var(--fg-dim)" }}>Stored server-side. Secrets are write-only and never returned.</p>
      </div>
      {isLoading && <Spinner label="Loading settings…" />}
      {error && <Card><span style={{ color: "var(--bad)" }}>{String(error)}</span></Card>}
      <div className="settings-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "repeat(2, minmax(0,1fr))", alignItems: "start" }}>
        <AppearanceCard />
        {data && <Form data={data} />}
      </div>
    </div>
  );
}

function Section({ title, icon, subtitle, children }: { title: string; icon: React.ReactNode; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card pad={false}>
      <div className="card-h"><span style={{ color: "var(--accent)" }}>{icon}</span><h2>{title}</h2></div>
      <div className="card-b" style={{ display: "grid", gap: 16 }}>
        {subtitle && <p style={{ margin: "-2px 0 0", fontSize: 12.5, color: "var(--fg-faint)" }}>{subtitle}</p>}
        {children}
      </div>
    </Card>
  );
}

function AppearanceCard() {
  const { appearance, set } = useAppearanceCtx();
  return (
    <Section title="Appearance" icon={<Palette size={17} />}>
      <Field label="Theme">
        <Select value={appearance.theme} onChange={(e) => set({ theme: e.target.value as "dark" | "light" })}>
          <option value="dark">Dark</option><option value="light">Light</option>
        </Select>
      </Field>
      <Field label="Accent">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {(Object.keys(ACCENT_HUE) as Accent[]).map((k) => (
            <button key={k} title={k} onClick={() => set({ accent: k })}
              style={{ width: 28, height: 28, borderRadius: 8, cursor: "pointer", background: accentSwatch(k),
                border: appearance.accent === k ? "2px solid var(--fg)" : "2px solid transparent" }} />
          ))}
        </div>
      </Field>
      <Field label="Density">
        <Select value={appearance.density} onChange={(e) => set({ density: e.target.value as Density })}>
          <option value="compact">Compact</option><option value="regular">Regular</option><option value="comfy">Comfy</option>
        </Select>
      </Field>
      <Field label="Motion">
        <Select value={appearance.motion} onChange={(e) => set({ motion: e.target.value as Motion })}>
          <option value="full">Full</option><option value="calm">Calm</option><option value="off">Off</option>
        </Select>
      </Field>
    </Section>
  );
}

function Form({ data }: { data: SettingsPayload }) {
  const qc = useQueryClient();
  const g = data.general;
  const [draft, setDraft] = useState<GeneralSettings>(g);
  const [dirty, setDirty] = useState(false);
  const set = <K extends keyof GeneralSettings>(k: K, v: GeneralSettings[K]) => { setDraft((p) => ({ ...p, [k]: v })); setDirty(true); };

  const save = useMutation({
    mutationFn: () => api.saveSettings(draft),
    onSuccess: () => { setDirty(false); qc.invalidateQueries({ queryKey: ["settings"] }); },
  });

  const [secretVals, setSecretVals] = useState<Record<string, string>>({});
  const saveSecret = useMutation({
    mutationFn: (k: string) => api.saveSecrets({ [k]: secretVals[k] }),
    onSuccess: (_d, k) => { setSecretVals((p) => ({ ...p, [k]: "" })); qc.invalidateQueries({ queryKey: ["settings"] }); },
  });

  return (
    <>
      <Section title="Entry & season" icon={<Shield size={17} />}>
        <Field label="FPL entry id" hint="Your team's numeric id from the FPL site URL.">
          <TextInput className="mono" inputMode="numeric" value={draft.entry_id ?? ""} onChange={(e) => set("entry_id", e.target.value === "" ? null : Number(e.target.value))} />
        </Field>
        <Field label="Season" hint="e.g. 2024-25 (auto-detected live in production).">
          <TextInput className="mono" value={draft.season ?? ""} onChange={(e) => set("season", e.target.value || null)} />
        </Field>
        <Field label="Planning horizon" hint={`Forecast the next ${draft.horizon} gameweeks.`}>
          <Slider value={draft.horizon} min={1} max={10} onChange={(v) => set("horizon", v)} suffix=" GW" />
        </Field>
      </Section>

      <Section title="Model & strategy" icon={<BarChart3 size={17} />}>
        <Field label="Served model version" hint="The predictor serving xP across the app.">
          <Select value={draft.active_model} onChange={(e) => set("active_model", e.target.value)}>
            {data.models.versions.map((v) => <option key={v} value={v}>{v}</option>)}
          </Select>
        </Field>
        <Field label="Default strategy" hint="Default predictor/ensemble surfaced in comparisons.">
          <Select value={draft.active_strategy} onChange={(e) => set("active_strategy", e.target.value)}>
            {data.models.strategies.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
      </Section>

      <Section title="Optimisation" icon={<Target size={17} />}>
        <Field label="Free-transfer value" hint="Points a banked free transfer is worth to the planner.">
          <Slider value={draft.ft_value} min={0} max={3} step={0.1} onChange={(v) => set("ft_value", v)} decimals={1} suffix=" pts" />
        </Field>
        <Field label="Future-GW decay" hint="Down-weights points further out in the horizon.">
          <Slider value={draft.decay_base} min={0.6} max={1} step={0.01} onChange={(v) => set("decay_base", v)} decimals={2} />
        </Field>
        <Field label="Effective-ownership weight" hint="Higher = more rank-aware (template-leaning).">
          <Slider value={draft.eo_weight} min={0} max={1} step={0.05} onChange={(v) => set("eo_weight", v)} decimals={2} />
        </Field>
        <Field label="EV threshold for alerts" hint="Only surface transfers above this expected gain.">
          <Slider value={draft.ev_threshold} min={0} max={6} step={0.5} onChange={(v) => set("ev_threshold", v)} decimals={1} suffix=" pts" />
        </Field>
      </Section>

      <Section title="Notifications" icon={<Bell size={17} />}>
        <Row label="Email alerts" hint="Price moves, injury flips, transfer recs."><Toggle checked={draft.notify_email} onChange={(v) => set("notify_email", v)} /></Row>
        <Row label="Push alerts" hint="Browser push when the recompute changes its mind."><Toggle checked={draft.notify_push} onChange={(v) => set("notify_push", v)} /></Row>
        {draft.notify_email && (
          <div className="fade-up" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="SMTP host"><TextInput value={draft.smtp_host ?? ""} placeholder="smtp.gmail.com" onChange={(e) => set("smtp_host", e.target.value || null)} /></Field>
            <Field label="SMTP port"><TextInput type="number" value={draft.smtp_port} onChange={(e) => set("smtp_port", Number(e.target.value))} /></Field>
            <Field label="Sender (From)"><TextInput type="email" value={draft.smtp_from ?? ""} placeholder="alerts@example.com" onChange={(e) => set("smtp_from", e.target.value || null)} /></Field>
            <Field label="Recipient (To)"><TextInput type="email" value={draft.smtp_to ?? ""} placeholder="you@example.com" onChange={(e) => set("smtp_to", e.target.value || null)} /></Field>
          </div>
        )}
      </Section>

      <Section title="Secrets" icon={<KeyRound size={17} />} subtitle="Write-only; stored server-side, override env values.">
        {SECRETS.map((s) => (
          <div key={s.key} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(200px,300px)", gap: 16, alignItems: "center" }}>
            <span>
              <span style={{ display: "block", fontSize: 13.5, fontWeight: 600 }}>{s.label}</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: data.secrets[s.key] ? "var(--accent)" : "var(--fg-faint)", marginTop: 2 }}>
                {data.secrets[s.key] ? <><Check size={12} /> stored</> : s.hint}
              </span>
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <TextInput type="password" autoComplete="off" placeholder={data.secrets[s.key] ? "•••• (set)" : "not set"} value={secretVals[s.key] ?? ""} onChange={(e) => setSecretVals((p) => ({ ...p, [s.key]: e.target.value }))} />
              <button className="btn btn-ghost" disabled={!secretVals[s.key] || saveSecret.isPending} onClick={() => saveSecret.mutate(s.key)}>Set</button>
            </div>
          </div>
        ))}
      </Section>

      <div className="tx" style={{ position: "fixed", left: "50%", bottom: dirty ? 20 : -80, transform: "translateX(-50%)", zIndex: 50,
        display: "flex", alignItems: "center", gap: 14, padding: "11px 14px 11px 18px", borderRadius: 14, background: "var(--surface-3)", border: "1px solid var(--line-2)", boxShadow: "var(--shadow)", opacity: dirty ? 1 : 0, pointerEvents: dirty ? "auto" : "none" }}>
        <span style={{ fontSize: 13, color: "var(--fg-dim)" }}>You have unsaved changes</span>
        <button className="btn btn-ghost" onClick={() => { setDraft(g); setDirty(false); }}>Reset</button>
        <button className="btn btn-pri" disabled={save.isPending} onClick={() => save.mutate()}><Check size={15} /> {save.isSuccess && !dirty ? "Saved" : "Save changes"}</button>
      </div>
    </>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
      <span>
        <span style={{ display: "block", fontSize: 13.5, fontWeight: 600 }}>{label}</span>
        {hint && <span style={{ display: "block", fontSize: 12, color: "var(--fg-faint)", marginTop: 2 }}>{hint}</span>}
      </span>
      {children}
    </div>
  );
}
