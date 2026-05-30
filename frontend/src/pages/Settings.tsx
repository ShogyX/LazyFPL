import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Loader2, Save } from "lucide-react";
import { PageHeader, Card } from "../components/Layout";
import { api, type GeneralSettings, type SettingsPayload } from "../lib/api";

const SECRET_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "fpl_session_cookie", label: "FPL session cookie", hint: "Enables authed /my-team (exact prices & bank)." },
  { key: "api_football_key", label: "API-Football key", hint: "Lineups / injuries / referees." },
  { key: "sharpapi_key", label: "SharpAPI key", hint: "Odds (iced)." },
  { key: "oddsapi_io_key", label: "odds-api.io key", hint: "Odds (iced)." },
  { key: "pushover_token", label: "Pushover token", hint: "Push notifications." },
  { key: "pushover_user", label: "Pushover user", hint: "Push notifications." },
  { key: "smtp_username", label: "SMTP username", hint: "Email notifications." },
  { key: "smtp_password", label: "SMTP password", hint: "Email notifications." },
];

export default function Settings() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="General config, API keys, integrations and model selection."
      />
      {isLoading && <Loading />}
      {error && <ErrorBox message={String(error)} />}
      {data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <GeneralCard data={data} />
          <ModelCard data={data} />
          <IntegrationsCard data={data} />
          <SecretsCard data={data} onSaved={() => qc.invalidateQueries({ queryKey: ["settings"] })} />
        </div>
      )}
    </>
  );
}

function useSaveGeneral() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: Partial<GeneralSettings>) => api.saveSettings(updates),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

function GeneralCard({ data }: { data: SettingsPayload }) {
  const g = data.general;
  const save = useSaveGeneral();
  const [form, setForm] = useState({
    entry_id: g.entry_id ?? "",
    season: g.season ?? "",
    horizon: g.horizon,
    theme: g.theme,
  });
  useEffect(() => {
    document.documentElement.className = g.theme;
  }, [g.theme]);

  return (
    <Card title="General">
      <div className="grid gap-3">
        <Field label="Entry id">
          <input
            className={inputCls}
            value={form.entry_id}
            inputMode="numeric"
            onChange={(e) => setForm({ ...form, entry_id: e.target.value })}
          />
        </Field>
        <Field label="Season (e.g. 2024-25)">
          <input className={inputCls} value={form.season} onChange={(e) => setForm({ ...form, season: e.target.value })} />
        </Field>
        <Field label="Planning horizon (GWs)">
          <input
            type="number"
            min={1}
            max={10}
            className={inputCls}
            value={form.horizon}
            onChange={(e) => setForm({ ...form, horizon: Number(e.target.value) })}
          />
        </Field>
        <Field label="Theme">
          <select
            className={inputCls}
            value={form.theme}
            onChange={(e) => {
              const theme = e.target.value as "light" | "dark";
              setForm({ ...form, theme });
              document.documentElement.className = theme;
            }}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </Field>
        <SaveButton
          pending={save.isPending}
          done={save.isSuccess}
          onClick={() =>
            save.mutate({
              entry_id: form.entry_id === "" ? null : Number(form.entry_id),
              season: form.season || null,
              horizon: form.horizon,
              theme: form.theme,
            })
          }
        />
      </div>
    </Card>
  );
}

function ModelCard({ data }: { data: SettingsPayload }) {
  const save = useSaveGeneral();
  const [model, setModel] = useState(data.general.active_model);
  const [strategy, setStrategy] = useState(data.general.active_strategy);
  return (
    <Card title="Models">
      <div className="grid gap-3">
        <p className="text-sm text-muted-fg">
          Choose the served model version and the default predictor/ensemble strategy used for
          suggestions and the Model Performance defaults.
        </p>
        <Field label="Served model version">
          <select className={inputCls} value={model} onChange={(e) => setModel(e.target.value)}>
            {data.models.versions.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </Field>
        <Field label="Default strategy">
          <select className={inputCls} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            {data.models.strategies.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </Field>
        <SaveButton
          pending={save.isPending}
          done={save.isSuccess}
          onClick={() => save.mutate({ active_model: model, active_strategy: strategy })}
        />
      </div>
    </Card>
  );
}

function IntegrationsCard({ data }: { data: SettingsPayload }) {
  const save = useSaveGeneral();
  const g = data.general;
  const [email, setEmail] = useState(g.notify_email);
  const [push, setPush] = useState(g.notify_push);
  const [evThreshold, setEvThreshold] = useState(g.ev_threshold);
  return (
    <Card title="Integrations">
      <div className="grid gap-3">
        <Toggle label="Email notifications" hint="Requires SMTP credentials below." checked={email} onChange={setEmail} />
        <Toggle label="Push notifications" hint="Requires Pushover token + user below." checked={push} onChange={setPush} />
        <Field label="Notify EV threshold (pts uplift)">
          <input
            type="number"
            step="0.1"
            className={inputCls}
            value={evThreshold}
            onChange={(e) => setEvThreshold(Number(e.target.value))}
          />
        </Field>
        <SaveButton
          pending={save.isPending}
          done={save.isSuccess}
          onClick={() => save.mutate({ notify_email: email, notify_push: push, ev_threshold: evThreshold })}
        />
      </div>
    </Card>
  );
}

function SecretsCard({ data, onSaved }: { data: SettingsPayload; onSaved: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (updates: Record<string, string | null>) => api.saveSecrets(updates),
    onSuccess: () => {
      setValues({});
      onSaved();
    },
  });

  return (
    <Card title="API keys & credentials">
      <div className="grid gap-3">
        <p className="text-sm text-muted-fg">
          Stored server-side; values are write-only and never returned. A green dot means a secret
          is set (from this form or the environment).
        </p>
        {SECRET_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${data.secrets[f.key] ? "bg-positive" : "bg-border"}`}
                title={data.secrets[f.key] ? "set" : "not set"}
              />
              <input
                type="password"
                autoComplete="off"
                placeholder={data.secrets[f.key] ? "•••••• (set — leave blank to keep)" : "not set"}
                className={inputCls}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            </div>
          </Field>
        ))}
        <button
          className={btnCls}
          disabled={save.isPending || Object.keys(values).length === 0}
          onClick={() => save.mutate(values)}
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          Save secrets
        </button>
      </div>
    </Card>
  );
}

// ---- shared bits ----
const inputCls =
  "w-full rounded-md border border-border bg-bg px-3 py-1.5 text-sm text-fg outline-none focus:ring-2 focus:ring-ring";
const btnCls =
  "inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-on-primary transition hover:opacity-90 disabled:opacity-50";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1">
      <span className="text-sm font-medium text-fg">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-fg">{hint}</span>}
    </label>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start justify-between gap-3">
      <span>
        <span className="block text-sm font-medium text-fg">{label}</span>
        {hint && <span className="block text-xs text-muted-fg">{hint}</span>}
      </span>
      <input type="checkbox" className="mt-1 h-4 w-4 accent-[var(--color-primary)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function SaveButton({ pending, done, onClick }: { pending: boolean; done: boolean; onClick: () => void }) {
  return (
    <button className={`${btnCls} justify-self-start`} disabled={pending} onClick={onClick}>
      {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : done ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
      {done ? "Saved" : "Save"}
    </button>
  );
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-fg">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading settings…
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-md border border-destructive bg-surface px-3 py-2 text-sm text-destructive">{message}</div>;
}
