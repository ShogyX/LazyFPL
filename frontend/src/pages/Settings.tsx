import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Save } from "lucide-react";
import { PageHeader, Card } from "../components/Layout";
import { Button, ErrorBox, Field, Select, Spinner, TextInput, Toggle } from "../components/ui";
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
      <PageHeader title="Settings" subtitle="General config, API keys, integrations and model selection." />
      {isLoading && <Spinner label="Loading settings…" />}
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

function SaveButton({ save, onClick }: { save: ReturnType<typeof useSaveGeneral>; onClick: () => void }) {
  return (
    <Button
      className="justify-self-start"
      loading={save.isPending}
      icon={save.isSuccess ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
      onClick={onClick}
    >
      {save.isSuccess ? "Saved" : "Save"}
    </Button>
  );
}

function GeneralCard({ data }: { data: SettingsPayload }) {
  const g = data.general;
  const save = useSaveGeneral();
  const [form, setForm] = useState({ entry_id: g.entry_id ?? "", season: g.season ?? "", horizon: g.horizon, theme: g.theme });
  useEffect(() => { document.documentElement.className = g.theme; }, [g.theme]);

  return (
    <Card title="General">
      <div className="grid gap-3">
        <Field label="Entry id">
          <TextInput value={form.entry_id} inputMode="numeric" onChange={(e) => setForm({ ...form, entry_id: e.target.value })} />
        </Field>
        <Field label="Season (e.g. 2024-25)">
          <TextInput value={form.season} placeholder="2024-25" onChange={(e) => setForm({ ...form, season: e.target.value })} />
        </Field>
        <Field label="Planning horizon (GWs)">
          <TextInput type="number" min={1} max={10} value={form.horizon} onChange={(e) => setForm({ ...form, horizon: Number(e.target.value) })} />
        </Field>
        <Field label="Theme">
          <Select
            value={form.theme}
            onChange={(e) => {
              const theme = e.target.value as "light" | "dark";
              setForm({ ...form, theme });
              document.documentElement.className = theme;
            }}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </Select>
        </Field>
        <SaveButton save={save} onClick={() => save.mutate({
          entry_id: form.entry_id === "" ? null : Number(form.entry_id),
          season: form.season || null, horizon: form.horizon, theme: form.theme,
        })} />
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
          <Select value={model} onChange={(e) => setModel(e.target.value)}>
            {data.models.versions.map((v) => <option key={v} value={v}>{v}</option>)}
          </Select>
        </Field>
        <Field label="Default strategy">
          <Select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            {data.models.strategies.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
        <SaveButton save={save} onClick={() => save.mutate({ active_model: model, active_strategy: strategy })} />
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
  const [smtpHost, setSmtpHost] = useState(g.smtp_host ?? "");
  const [smtpPort, setSmtpPort] = useState(g.smtp_port);
  const [smtpFrom, setSmtpFrom] = useState(g.smtp_from ?? "");
  const [smtpTo, setSmtpTo] = useState(g.smtp_to ?? "");
  return (
    <Card title="Integrations">
      <div className="grid gap-3">
        <Toggle label="Email notifications" hint="Requires SMTP host, sender, recipient + credentials." checked={email} onChange={setEmail} />
        <Toggle label="Push notifications" hint="Requires Pushover token + user below." checked={push} onChange={setPush} />
        <Field label="Notify EV threshold (pts uplift)">
          <TextInput type="number" step="0.1" value={evThreshold} onChange={(e) => setEvThreshold(Number(e.target.value))} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="SMTP host"><TextInput placeholder="smtp.gmail.com" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} /></Field>
          <Field label="SMTP port"><TextInput type="number" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} /></Field>
        </div>
        <Field label="Sender email (From)">
          <TextInput type="email" placeholder="alerts@example.com" value={smtpFrom} onChange={(e) => setSmtpFrom(e.target.value)} />
        </Field>
        <Field label="Recipient email (To)" hint="Where email alerts are delivered — required for email.">
          <TextInput type="email" placeholder="you@example.com" value={smtpTo} onChange={(e) => setSmtpTo(e.target.value)} />
        </Field>
        <SaveButton save={save} onClick={() => save.mutate({
          notify_email: email, notify_push: push, ev_threshold: evThreshold,
          smtp_host: smtpHost || null, smtp_port: smtpPort,
          smtp_from: smtpFrom || null, smtp_to: smtpTo || null,
        })} />
      </div>
    </Card>
  );
}

function SecretsCard({ data, onSaved }: { data: SettingsPayload; onSaved: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (updates: Record<string, string | null>) => api.saveSecrets(updates),
    onSuccess: () => { setValues({}); onSaved(); },
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
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${data.secrets[f.key] ? "bg-positive shadow-[0_0_6px] shadow-positive" : "bg-border"}`}
                title={data.secrets[f.key] ? "set" : "not set"}
              />
              <TextInput
                type="password"
                autoComplete="off"
                placeholder={data.secrets[f.key] ? "•••••• (set — leave blank to keep)" : "not set"}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            </div>
          </Field>
        ))}
        <Button
          className="justify-self-start"
          loading={save.isPending}
          icon={<KeyRound className="h-4 w-4" />}
          disabled={Object.keys(values).length === 0}
          onClick={() => save.mutate(values)}
        >
          Save secrets
        </Button>
      </div>
    </Card>
  );
}
