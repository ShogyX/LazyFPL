/* Settings — grouped, tactile, with a save bar that slides in when dirty. */
function SettingsPage() {
  const { SQUAD, STRATEGIES, SEASON } = window.FPL;
  const init = {
    entry: SQUAD.entry, season: SEASON, horizon: 6, model: "ensemble", strategy: "ensemble",
    ftValue: 1.2, decay: 0.84, eoWeight: 0.3, evThreshold: 2.0,
    notifyEmail: true, notifyPush: false, smtpFrom: "fpl@local", smtpTo: "me@local",
  };
  const [s, setS] = React.useState(init);
  const [saved, setSaved] = React.useState(true);
  const set = (k, v) => { setS((p) => ({ ...p, [k]: v })); setSaved(false); };
  const dirty = !saved;

  return (
    <div className="fade-up" style={{ display: "grid", gap: "var(--gap)", maxWidth: 880, paddingBottom: dirty ? 70 : 0 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "clamp(22px,3vw,30px)", fontWeight: 800, letterSpacing: "-0.025em" }}>Settings</h1>
        <p style={{ margin: "4px 0 0", fontSize: 13.5, color: "var(--fg-dim)" }}>Everything is stored server-side. Secrets are write-only and never returned.</p>
      </div>

      <SettingsCard title="Entry & season" icon="shield">
        <Field label="FPL entry id" hint="Your team’s numeric id from the FPL site URL.">
          <TextField value={s.entry} onChange={(v) => set("entry", v)} mono />
        </Field>
        <Field label="Season" hint="Auto-detected from the live FPL calendar.">
          <TextField value={s.season} onChange={(v) => set("season", v)} mono />
        </Field>
        <Field label="Planning horizon" hint={`Forecast the next ${s.horizon} gameweeks.`}>
          <Slider value={s.horizon} min={1} max={10} onChange={(v) => set("horizon", v)} suffix=" GW" />
        </Field>
      </SettingsCard>

      <SettingsCard title="Model & strategy" icon="chart">
        <Field label="Active model" hint="The predictor serving xP across the app.">
          <SelectField value={s.model} onChange={(v) => set("model", v)} options={[["ensemble", "Ensemble (Hedge)"], ["stacking", "Ridge Stack"], ["perpos", "Per-Position"], ["v1", "Baseline v1"]]} />
        </Field>
        <Field label="Optimiser strategy" hint="How the MILP picks squads & transfers.">
          <SelectField value={s.strategy} onChange={(v) => set("strategy", v)} options={STRATEGIES.map((x) => [x.key, x.name])} />
        </Field>
      </SettingsCard>

      <SettingsCard title="Optimisation" icon="target">
        <Field label="Free-transfer value" hint="Points a banked free transfer is worth to the planner.">
          <Slider value={s.ftValue} min={0} max={3} step={0.1} onChange={(v) => set("ftValue", v)} decimals={1} suffix=" pts" />
        </Field>
        <Field label="Future-GW decay" hint="Down-weights points further out in the horizon.">
          <Slider value={s.decay} min={0.6} max={1} step={0.01} onChange={(v) => set("decay", v)} decimals={2} />
        </Field>
        <Field label="Effective-ownership weight" hint="Higher = more rank-aware (template-leaning) picks.">
          <Slider value={s.eoWeight} min={0} max={1} step={0.05} onChange={(v) => set("eoWeight", v)} decimals={2} />
        </Field>
        <Field label="EV threshold for alerts" hint="Only surface transfers above this expected gain.">
          <Slider value={s.evThreshold} min={0} max={6} step={0.5} onChange={(v) => set("evThreshold", v)} decimals={1} suffix=" pts" />
        </Field>
      </SettingsCard>

      <SettingsCard title="Notifications" icon="bolt">
        <ToggleField label="Email alerts" hint="Price moves, injury flips, transfer recs." value={s.notifyEmail} onChange={(v) => set("notifyEmail", v)} />
        <ToggleField label="Push alerts" hint="Browser push when the recompute changes its mind." value={s.notifyPush} onChange={(v) => set("notifyPush", v)} />
        {s.notifyEmail && (
          <div className="fade-up" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="From"><TextField value={s.smtpFrom} onChange={(v) => set("smtpFrom", v)} mono /></Field>
            <Field label="To"><TextField value={s.smtpTo} onChange={(v) => set("smtpTo", v)} mono /></Field>
          </div>
        )}
      </SettingsCard>

      <SettingsCard title="Secrets" icon="shield" subtitle="Optional enrichment sources. Stored encrypted, override env values.">
        <SecretField label="API-Football key" placeholder="lineups · injuries · referees" />
        <SecretField label="SMTP password" placeholder="for email alerts" set />
      </SettingsCard>

      {/* save bar */}
      <div className="tx" style={{ position: "fixed", left: "50%", bottom: dirty ? 20 : -80, transform: "translateX(-50%)", zIndex: 50,
        display: "flex", alignItems: "center", gap: 14, padding: "11px 14px 11px 18px", borderRadius: 14,
        background: "var(--surface-3)", border: "1px solid var(--line-2)", boxShadow: "var(--shadow)", opacity: dirty ? 1 : 0 }}>
        <span style={{ fontSize: 13, color: "var(--fg-dim)" }}>You have unsaved changes</span>
        <button className="btn btn-ghost" onClick={() => { setS(init); setSaved(true); }}>Reset</button>
        <button className="btn btn-pri" onClick={() => setSaved(true)}><Icon name="check" size={15} /> Save changes</button>
      </div>
    </div>
  );
}

function SettingsCard({ title, subtitle, icon, children }) {
  return (
    <Card pad={false}>
      <div className="card-h">
        <span style={{ color: "var(--accent)" }}><Icon name={icon} size={17} /></span>
        <h2>{title}</h2>
      </div>
      <div className="card-b" style={{ display: "grid", gap: 16 }}>
        {subtitle && <p style={{ margin: "-2px 0 0", fontSize: 12.5, color: "var(--fg-faint)" }}>{subtitle}</p>}
        {children}
      </div>
    </Card>
  );
}

function Field({ label, hint, children }) {
  return (
    <label style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(160px,260px)", gap: 16, alignItems: "center" }}>
      <span>
        <span style={{ display: "block", fontSize: 13.5, fontWeight: 600 }}>{label}</span>
        {hint && <span style={{ display: "block", fontSize: 12, color: "var(--fg-faint)", marginTop: 2 }}>{hint}</span>}
      </span>
      <span>{children}</span>
    </label>
  );
}

function TextField({ value, onChange, mono }) {
  return <input value={value} onChange={(e) => onChange(e.target.value)} className={mono ? "mono" : ""}
    style={{ width: "100%", padding: "9px 11px", borderRadius: 9, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--fg)", fontSize: 13.5 }} />;
}

function SelectField({ value, onChange, options }) {
  return (
    <div style={{ position: "relative" }}>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%", appearance: "none", padding: "9px 32px 9px 11px", borderRadius: 9, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--fg)", fontSize: 13.5, cursor: "pointer" }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--fg-faint)" }}><Icon name="chevD" size={15} /></span>
    </div>
  );
}

function Slider({ value, min, max, step = 1, onChange, decimals = 0, suffix = "" }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)}
        style={{ flex: 1, accentColor: "var(--accent)" }} />
      <span className="num" style={{ minWidth: 52, textAlign: "right", fontWeight: 700, fontSize: 13.5, color: "var(--accent)" }}>{value.toFixed(decimals)}{suffix}</span>
    </div>
  );
}

function ToggleField({ label, hint, value, onChange }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
      <span>
        <span style={{ display: "block", fontSize: 13.5, fontWeight: 600 }}>{label}</span>
        {hint && <span style={{ display: "block", fontSize: 12, color: "var(--fg-faint)", marginTop: 2 }}>{hint}</span>}
      </span>
      <button onClick={() => onChange(!value)} className="tx" style={{ position: "relative", width: 44, height: 25, borderRadius: 999, border: "1px solid var(--line)", cursor: "pointer", background: value ? "var(--accent)" : "var(--surface-3)", flexShrink: 0 }}>
        <span className="tx" style={{ position: "absolute", top: 2, left: value ? 21 : 2, width: 19, height: 19, borderRadius: 999, background: value ? "var(--accent-ink)" : "var(--fg-dim)" }} />
      </button>
    </div>
  );
}

function SecretField({ label, placeholder, set }) {
  const [val, setVal] = React.useState("");
  const [stored, setStored] = React.useState(set || false);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(200px,300px)", gap: 16, alignItems: "center" }}>
      <span>
        <span style={{ display: "block", fontSize: 13.5, fontWeight: 600 }}>{label}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: stored ? "var(--accent)" : "var(--fg-faint)", marginTop: 2 }}>
          {stored ? <React.Fragment><Icon name="check" size={12} /> stored</React.Fragment> : "not set"}
        </span>
      </span>
      <div style={{ display: "flex", gap: 8 }}>
        <input type="password" value={val} onChange={(e) => setVal(e.target.value)} placeholder={placeholder} className="mono"
          style={{ flex: 1, padding: "9px 11px", borderRadius: 9, border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--fg)", fontSize: 13 }} />
        <button className="btn btn-ghost" disabled={!val} onClick={() => { setStored(true); setVal(""); }} style={{ opacity: val ? 1 : 0.5 }}>Set</button>
      </div>
    </div>
  );
}

window.SettingsPage = SettingsPage;
