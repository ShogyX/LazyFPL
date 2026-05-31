import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Check, Crown, Download, Info, Shield, Sparkles } from "lucide-react";
import Pitch, { type PitchPlayer } from "../components/Pitch";
import { BarChart } from "../components/charts";
import PlayerAvatar, { TeamBadge } from "../components/PlayerAvatar";
import { Button, Card, Conf, CountUp, Hint, Mini, Segmented, Spinner, TextInput } from "../components/ui";
import { api, type CaptainCandidate, type ChipContext, type PlannerResult, type Squad, type TrackedDetail } from "../lib/api";

export default function TeamPlanner() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [entry, setEntry] = useState("");
  const [season, setSeason] = useState("");
  const [gw, setGw] = useState(1);
  useEffect(() => {
    const g = settings.data?.general;
    if (!g) return;
    if (g.entry_id != null && entry === "") setEntry(String(g.entry_id));
    if (g.season && season === "") setSeason(g.season);
    if (g.gw != null) setGw(g.gw);
  }, [settings.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const entryId = entry === "" ? null : Number(entry);
  const version = settings.data?.general.active_model ?? "v1";

  return (
    <div className="fade-up" style={{ display: "grid", gap: "var(--gap)" }}>
      <Controls entry={entry} season={season} gw={gw} onEntry={setEntry} onSeason={setSeason} onGw={setGw} />
      {entryId != null && season
        ? <Loaded entryId={entryId} season={season} gw={gw} version={version} />
        : <Card><Hint>Enter an entry id and season above (or set them in Settings) to load your team, captain pick, transfer and chip plan.</Hint></Card>}
    </div>
  );
}

function Controls(props: { entry: string; season: string; gw: number; onEntry: (v: string) => void; onSeason: (v: string) => void; onGw: (v: number) => void }) {
  const track = useMutation({ mutationFn: (id: number) => api.trackEntry(id) });
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <Mini label="Entry id"><div style={{ width: 120 }}><TextInput inputMode="numeric" value={props.entry} onChange={(e) => props.onEntry(e.target.value)} /></div></Mini>
        <Mini label="Season"><div style={{ width: 110 }}><TextInput placeholder="2025-26" value={props.season} onChange={(e) => props.onSeason(e.target.value)} /></div></Mini>
        <Mini label="GW"><div style={{ width: 72 }}><TextInput type="number" min={1} max={38} value={props.gw} onChange={(e) => props.onGw(Number(e.target.value))} /></div></Mini>
        <Button variant="pri" loading={track.isPending} icon={track.isSuccess ? <Check size={15} /> : <Download size={15} />}
          disabled={props.entry === ""} onClick={() => track.mutate(Number(props.entry))}>
          {track.isSuccess ? "Tracked" : "Track team"}
        </Button>
        {track.isError && <span style={{ fontSize: 12, color: "var(--bad)" }}>{String(track.error)}</span>}
      </div>
    </Card>
  );
}

function Loaded({ entryId, season, gw, version }: { entryId: number; season: string; gw: number; version: string }) {
  const tracked = useQuery({ queryKey: ["track", entryId], queryFn: () => api.trackedEntry(entryId), retry: false });
  const squad = useQuery({ queryKey: ["squad", season, gw, version], queryFn: () => api.squad(season, gw, version), retry: false });
  const preds = useQuery({ queryKey: ["predictions", season, gw, version], queryFn: () => api.predictions(season, gw, version, undefined, 1000), retry: false });
  const planner = useQuery({ queryKey: ["planner", entryId, season, gw], queryFn: () => api.planner(entryId, season, gw, { horizon: 6 }), retry: false });

  const [view, setView] = useState<"team" | "model">("team");
  const [capId, setCapId] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  const xpById = useMemo(() => {
    const m = new Map<number, number>();
    preds.data?.players.forEach((p) => m.set(p.element_id, p.xp_next1 ?? 0));
    return m;
  }, [preds.data]);

  if (tracked.isLoading) return <Spinner label="Loading your team…" />;

  // Build pitch players for the active view.
  const teamPitch = tracked.data ? splitTracked(tracked.data, xpById, capId) : null;
  const modelPitch = squad.data ? splitSquad(squad.data) : null;
  const shown = view === "team" ? teamPitch : modelPitch;

  const xiProj = shown ? shown.starters.reduce((s, p) => s + (parseFloat(p.meta || "0") || 0), 0) : 0;

  return (
    <>
      {tracked.data && <TeamHeader d={tracked.data} season={season} xiProj={view === "team" ? xiProj : (squad.data?.xi_xp ?? 0)} />}
      <div className="planner-grid" style={{ display: "grid", gap: "var(--gap)", gridTemplateColumns: "minmax(0,1.55fr) minmax(320px,1fr)", alignItems: "start" }}>
        <Card pad={false}>
          <div className="card-h">
            <h2>{view === "team" ? "Your XI" : "Model-optimal XI"}</h2>
            <div style={{ marginLeft: "auto" }}>
              <Segmented value={view} onChange={(v) => setView(v as "team" | "model")} options={[{ value: "team", label: "Your team" }, { value: "model", label: "Model XI" }]} />
            </div>
          </div>
          <div className="card-b">
            {!shown && <Hint>{view === "team" ? "Track this entry to see your XI." : `No model squad for ${season} GW${gw}.`}</Hint>}
            {shown && (
              <>
                <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginBottom: 14 }}>
                  <HeadStat label="Projected XI" big accent>{(view === "team" ? xiProj : (squad.data?.xi_xp ?? 0)).toFixed(1)}</HeadStat>
                  <HeadStat label="Formation">{formationOf(shown.starters)}</HeadStat>
                  {view === "model" && squad.data && <HeadStat label="XI cost">£{squad.data.total_cost.toFixed(1)}m</HeadStat>}
                  {view === "team" && tracked.data && <HeadStat label="Squad value">£{tracked.data.team_value.toFixed(1)}m</HeadStat>}
                  {view === "team" && tracked.data && <HeadStat label="In the bank">£{tracked.data.bank.toFixed(1)}m</HeadStat>}
                </div>
                <Pitch starters={shown.starters} bench={shown.bench} selected={selected ?? undefined} onSelect={setSelected} />
                <p style={{ margin: "12px 2px 0", fontSize: 12, color: "var(--fg-faint)", display: "flex", alignItems: "center", gap: 6 }}>
                  <Info size={13} /> Tap a player for their breakdown · the captain’s points are doubled.
                </p>
              </>
            )}
          </div>
        </Card>

        <div style={{ display: "grid", gap: "var(--gap)" }}>
          {selected != null
            ? <PlayerDetail elementId={selected} season={season} preds={preds.data?.players ?? []} onClose={() => setSelected(null)} />
            : (
              <>
                <CaptainCard entryId={entryId} season={season} gw={gw} version={version} starters={tracked.data} preds={preds.data?.players ?? []} capId={capId} setCapId={setCapId} />
                <TransferCard planner={planner.data} loading={planner.isLoading} error={planner.error ? String(planner.error) : null} />
                <ChipCard ctx={planner.data?.chip_context ?? null} />
              </>
            )}
        </div>
      </div>
    </>
  );
}

// ---------- header ----------
function TeamHeader({ d, season, xiProj }: { d: TrackedDetail; season: string; xiProj: number }) {
  return (
    <Card pad={false}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", padding: "calc(16px*var(--dens)) var(--pad)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
          <div style={{ width: 46, height: 46, borderRadius: 12, background: "var(--accent)", color: "var(--accent-ink)", display: "grid", placeItems: "center", boxShadow: "0 10px 26px -10px var(--accent-glow)" }}><Shield size={24} /></div>
          <div>
            <div style={{ fontSize: "clamp(18px,2.4vw,23px)", fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1 }}>{d.name ?? `Entry ${d.entry_id}`}</div>
            <div style={{ fontSize: 12.5, color: "var(--fg-dim)", marginTop: 3 }}>Gameweek {d.current_event ?? "?"} · {season} · entry {d.entry_id}</div>
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: "clamp(14px,2.4vw,34px)", flexWrap: "wrap" }}>
          <HeadStat label="Total points">{d.total_points != null ? <CountUp value={d.total_points} /> : "—"}</HeadStat>
          <HeadStat label="Overall rank">{d.overall_rank != null ? <CountUp value={d.overall_rank} /> : "—"}</HeadStat>
          <HeadStat label="Squad value">£{d.team_value.toFixed(1)}m</HeadStat>
          <HeadStat label="Live XI proj." accent>{xiProj.toFixed(1)}</HeadStat>
        </div>
      </div>
    </Card>
  );
}

function HeadStat({ label, children, accent, big }: { label: string; children: React.ReactNode; accent?: boolean; big?: boolean }) {
  return (
    <div style={{ minWidth: 78 }}>
      <div className="eyebrow" style={{ marginBottom: 5 }}>{label}</div>
      <div className="display num" style={{ fontSize: big ? "clamp(24px,3vw,32px)" : "clamp(18px,2.2vw,24px)", color: accent ? "var(--accent)" : "var(--fg)" }}>{children}</div>
    </div>
  );
}

// ---------- captain ----------
function CaptainCard({ entryId, season, gw, version, starters, preds, capId, setCapId }: {
  entryId: number; season: string; gw: number; version: string;
  starters: TrackedDetail | undefined; preds: { element_id: number; name: string; team: string | null; code: number | null; position: string | null; xp_next1: number | null; confidence?: number | null }[];
  capId: number | null; setCapId: (id: number) => void;
}) {
  // Distributional captaincy: Monte-Carlo EV + ceiling/floor/haul from the engine.
  const cap = useQuery({ queryKey: ["captaincy", entryId, season, gw, version], queryFn: () => api.captaincy(entryId, season, gw, version), retry: false });
  const dist = useMemo(() => {
    const m = new Map<number, CaptainCandidate>();
    cap.data?.candidates.forEach((c) => m.set(c.element_id, c));
    return m;
  }, [cap.data]);

  const xp = (id: number) => dist.get(id)?.ev ?? preds.find((p) => p.element_id === id)?.xp_next1 ?? 0;
  const meta = (id: number) => { const d = dist.get(id); const p = preds.find((q) => q.element_id === id); return { name: d?.name ?? p?.name, team: d?.team ?? p?.team, code: d?.code ?? p?.code, position: d?.position ?? p?.position, confidence: p?.confidence }; };
  // candidates ranked by engine EV: prefer the distribution list, else starters/preds by xP.
  const ids = dist.size ? cap.data!.candidates.map((c) => c.element_id)
    : starters ? starters.picks.filter((p) => (p.slot ?? 99) <= 11).map((p) => p.element_id) : preds.slice(0, 6).map((p) => p.element_id);
  const cands = [...ids].sort((a, b) => xp(b) - xp(a)).slice(0, 5);
  const pickId = capId ?? starters?.picks.find((p) => p.captain)?.element_id ?? cands[0];
  if (!pickId) return <Card title="Captain"><Hint>No prediction data for this gameweek yet.</Hint></Card>;
  const pm = meta(pickId); const pd = dist.get(pickId);
  const ceil = Math.max(...cands.map((id) => xp(id) * 2.4), 1);
  return (
    <Card title="Captain" right={<span className="tag tag-good"><Crown size={12} /> Pick</span>}>
      <div style={{ display: "flex", alignItems: "center", gap: 13, marginBottom: 14 }}>
        <div style={{ position: "relative" }}>
          <PlayerAvatar player={{ name: pm.name ?? "", team: pm.team, position: pm.position, code: pm.code }} size={56} />
          <span style={{ position: "absolute", right: -4, bottom: -4, width: 22, height: 22, borderRadius: 999, background: "var(--accent)", color: "var(--accent-ink)", fontWeight: 800, fontSize: 12, display: "grid", placeItems: "center", border: "2px solid var(--surface)" }}>C</span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 18, fontWeight: 800 }}>{pm.name}</div>
          <div style={{ fontSize: 12.5, color: "var(--fg-dim)", display: "flex", alignItems: "center", gap: 7 }}><TeamBadge code={pm.team} size={18} /> {pm.position}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="display" style={{ fontSize: 30, color: "var(--accent)" }}><CountUp value={xp(pickId) * 2} decimals={1} /></div>
          <div className="eyebrow">capt. xP</div>
        </div>
      </div>
      {pd && (
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <DistStat label="Ceiling" value={`${(pd.ceiling * 2).toFixed(0)}`} accent />
          <DistStat label="Floor" value={`${(pd.floor * 2).toFixed(0)}`} />
          <DistStat label="Haul" value={`${Math.round(pd.haul * 100)}%`} />
        </div>
      )}
      <div style={{ display: "grid", gap: 6 }}>
        {cands.map((id) => {
          const m = meta(id); const on = id === pickId; const d = dist.get(id);
          return (
            <button key={id} onClick={() => setCapId(id)} className="tx"
              style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", alignItems: "center", gap: 10, textAlign: "left", padding: "8px 10px", borderRadius: 10, cursor: "pointer", border: "1px solid " + (on ? "var(--accent)" : "var(--line)"), background: on ? "var(--accent-faint)" : "var(--surface-2)" }}>
              <PlayerAvatar player={{ name: m.name ?? "", team: m.team, position: m.position, code: m.code }} size={30} ring={false} />
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontWeight: 700, fontSize: 13 }}>{m.name}</span>
                  {m.confidence != null && <Conf v={m.confidence} />}
                  {d && <span className="num" style={{ fontSize: 10.5, color: "var(--fg-faint)" }}>▲{(d.ceiling * 2).toFixed(0)} · {Math.round(d.haul * 100)}%</span>}
                </div>
                <div style={{ marginTop: 3, height: 6, position: "relative" }}>
                  <div className="mbar" style={{ position: "absolute", inset: 0 }}><i style={{ width: `${(xp(id) * 2 / ceil) * 100}%`, background: "linear-gradient(90deg, var(--line-2), var(--accent))" }} /></div>
                </div>
              </div>
              <div className="num" style={{ fontWeight: 800, fontSize: 15, color: on ? "var(--accent)" : "var(--fg)", width: 34, textAlign: "right" }}>{xp(id).toFixed(1)}</div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function DistStat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{ flex: 1, padding: "7px 9px", borderRadius: 9, border: "1px solid var(--line)", background: "var(--surface-2)", textAlign: "center" }}>
      <div className="display num" style={{ fontSize: 17, color: accent ? "var(--accent)" : "var(--fg)" }}>{value}</div>
      <div className="eyebrow" style={{ marginTop: 2 }}>{label}</div>
    </div>
  );
}

// ---------- transfer ----------
function TransferCard({ planner, loading, error }: { planner?: PlannerResult; loading: boolean; error: string | null }) {
  if (loading) return <Card title="Transfer"><Spinner /></Card>;
  if (error || !planner) return <Card title="Transfer"><Hint>{error?.includes("404") ? "Track this entry first to plan transfers." : (error ?? "No recommendation available.")}</Hint></Card>;
  const r = planner.rationale;
  return (
    <Card title="Transfer" right={r.uplift != null ? <span className="tag tag-good">+{r.uplift.toFixed(1)} xP / {r.horizon}gw</span> : undefined}>
      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <Meter label="EV uplift" value={planner.ev_uplift ?? 0} suffix=" pts" decimals={1} />
        <Meter label="Confidence" value={Math.round((planner.confidence ?? 0) * 100)} suffix="%" pct={(planner.confidence ?? 0) * 100} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span className="tag tag-good"><Crown size={11} /> {r.captain.name}</span>
        <span className="num" style={{ marginLeft: "auto", fontSize: 12, color: "var(--fg-dim)" }}>{r.captain.xp_next.toFixed(2)} xP</span>
      </div>
      {r.transfers_in.length === 0
        ? <Hint>No transfer — hold is optimal{r.gw0_hit ? ` (−${r.gw0_hit * 4} would be a hit)` : ""}.</Hint>
        : (
          <div style={{ display: "grid", gap: 6 }}>
            {r.transfers_in.map((tin, i) => (
              <div key={tin.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "7px 10px", background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 8 }}>
                <span className="down">{r.transfers_out[i]?.name ?? "—"}</span>
                <ArrowRightLeft size={13} style={{ color: "var(--fg-faint)" }} />
                <span className="up">{tin.name}</span>
                <span className="num" style={{ marginLeft: "auto", color: "var(--fg-dim)" }}>{tin.xp_next.toFixed(2)} xP</span>
              </div>
            ))}
          </div>
        )}
      <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--fg-dim)" }}>
        <Sparkles size={14} style={{ color: "var(--accent)" }} />
        Plan net xP {r.plan_net_xp.toFixed(1)}{r.hold_net_xp != null ? ` vs hold ${r.hold_net_xp.toFixed(1)}` : ""}{r.gw0_hit ? ` · −${r.gw0_hit * 4} hit` : ""}.
      </div>
    </Card>
  );
}
function Meter({ label, value, suffix = "", decimals = 0, pct }: { label: string; value: number; suffix?: string; decimals?: number; pct?: number }) {
  return (
    <div style={{ flex: 1, background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "9px 11px" }}>
      <div className="eyebrow" style={{ marginBottom: 4 }}>{label}</div>
      <div className="display" style={{ fontSize: 20, color: "var(--accent)" }}><CountUp value={value} decimals={decimals} suffix={suffix} /></div>
      {pct != null && <div style={{ marginTop: 6 }} className="mbar"><i style={{ width: `${Math.min(100, pct)}%`, background: "var(--accent)" }} /></div>}
    </div>
  );
}

// ---------- chips: engine schedule (TC from xP, BB/FH from DGW/blank, WC from drift) ----------
function ChipCard({ ctx }: { ctx: ChipContext | null }) {
  const chips = ctx?.chips ?? [];
  const [sel, setSel] = useState<string | null>(null);
  const cur = chips.find((c) => c.key === (sel ?? chips[0]?.key));
  if (!ctx) return <Card title="Chip strategy"><Hint>Track this entry to plan chips.</Hint></Card>;
  return (
    <Card title="Chip strategy">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        {chips.map((c) => {
          const on = c.key === (sel ?? chips[0]?.key);
          return (
            <button key={c.key} onClick={() => setSel(c.key)} className="tx" style={{ textAlign: "left", padding: "10px 11px", borderRadius: 10, cursor: "pointer", border: "1px solid " + (on ? "var(--accent)" : "var(--line)"), background: on ? "var(--accent-faint)" : "var(--surface-2)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontWeight: 700, fontSize: 13 }}>{c.name}</span>
                {c.best_gw != null && <span className="num" style={{ fontSize: 11, color: "var(--accent)", fontWeight: 700 }}>GW{c.best_gw}</span>}
              </div>
              <div className="num" style={{ fontSize: 11.5, color: "var(--fg-dim)", marginTop: 3 }}>+{c.ev.toFixed(1)} EV</div>
            </button>
          );
        })}
      </div>
      {cur && (
        <div style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "10px 12px", background: "var(--surface-2)", borderRadius: 10, border: "1px solid var(--line)", marginBottom: 10 }}>
          <Sparkles size={16} style={{ color: "var(--accent)", flexShrink: 0, marginTop: 1 }} />
          <p style={{ margin: 0, fontSize: 12.5, color: "var(--fg-dim)", lineHeight: 1.5 }}>{cur.note}</p>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: ctx.transfer_mode === "normal" ? "var(--fg-faint)" : "var(--accent)" }}>
        <ArrowRightLeft size={13} /> <span>{ctx.guidance}</span>
      </div>
    </Card>
  );
}

// ---------- player detail ----------
function PlayerDetail({ elementId, season, preds, onClose }: {
  elementId: number; season: string;
  preds: { element_id: number; name: string; team: string | null; code: number | null; position: string | null; xp_next1: number | null; xp_next6: number | null; pred_minutes: number | null; confidence: number | null; price: number; status: string | null }[];
  onClose: () => void;
}) {
  const p = preds.find((x) => x.element_id === elementId);
  const hist = useQuery({ queryKey: ["history", elementId, season], queryFn: () => api.playerHistory(elementId, season), retry: false });
  if (!p) return <Card title="Player" pad={false}><div className="card-b"><Hint>No data.</Hint></div></Card>;
  return (
    <Card pad={false} className="fade-up">
      <div className="card-h">
        <Button onClick={onClose} style={{ padding: "6px 10px" }} icon={<ArrowRightLeft size={14} style={{ transform: "scaleX(-1)" }} />}>Back</Button>
        <h2 style={{ marginLeft: 4 }}>Player</h2>
      </div>
      <div className="card-b">
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
          <PlayerAvatar player={{ name: p.name, team: p.team, position: p.position, code: p.code }} size={62} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em" }}>{p.name}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--fg-dim)", marginTop: 4 }}>
              <TeamBadge code={p.team} size={18} /> {p.position}
              {p.status && p.status !== "a" && <span className="tag tag-warn">{p.status === "d" ? "Doubtful" : "Out"}</span>}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="display num" style={{ fontSize: 24 }}>£{p.price.toFixed(1)}</div>
            {p.confidence != null && <div style={{ marginTop: 4 }}><Conf v={p.confidence} label /></div>}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, marginBottom: 16 }}>
          {[["xP next", p.xp_next1?.toFixed(1) ?? "—", true], ["xP 6gw", p.xp_next6?.toFixed(1) ?? "—", false], ["Pred mins", p.pred_minutes?.toFixed(0) ?? "—", false], ["Confidence", p.confidence != null ? `${p.confidence}%` : "—", false]].map(([k, v, a]) => (
            <div key={k as string} style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 9, padding: "9px 10px" }}>
              <div className="eyebrow" style={{ marginBottom: 3 }}>{k}</div>
              <div className="display num" style={{ fontSize: 19, color: a ? "var(--accent)" : "var(--fg)" }}>{v}</div>
            </div>
          ))}
        </div>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Gameweek returns — {season}</div>
        {hist.isLoading && <Spinner />}
        {hist.data && hist.data.history.length > 0
          ? <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px" }}>
              <BarChart height={120} data={hist.data.history.map((h) => ({ gw: h.gw, pts: h.points }))} xKey="gw" series={[{ key: "pts", label: "Points", color: "var(--accent)" }]} legend={false} />
            </div>
          : <Hint>No {season} history for this player.</Hint>}
      </div>
    </Card>
  );
}

// ---------- helpers ----------
function formationOf(starters: PitchPlayer[]) {
  const c: Record<string, number> = { DEF: 0, MID: 0, FWD: 0 };
  starters.forEach((p) => { if (p.position && c[p.position] != null) c[p.position]++; });
  return `${c.DEF}-${c.MID}-${c.FWD}`;
}

function splitTracked(d: TrackedDetail, xp: Map<number, number>, capId: number | null): { starters: PitchPlayer[]; bench: PitchPlayer[] } {
  const map = (p: TrackedDetail["picks"][number]): PitchPlayer => {
    const isCap = capId != null ? p.element_id === capId : p.captain;
    const x = xp.get(p.element_id) ?? 0;
    return { id: p.element_id, name: p.name ?? String(p.element_id), position: p.position, code: p.code, team: p.team,
      captain: isCap, vice: capId != null ? false : p.vice, meta: (x * (isCap ? 2 : 1)).toFixed(1), hover: { x1: x } };
  };
  return {
    starters: d.picks.filter((p) => (p.slot ?? 99) <= 11).map(map),
    bench: d.picks.filter((p) => (p.slot ?? 0) > 11).map(map),
  };
}
function splitSquad(s: Squad): { starters: PitchPlayer[]; bench: PitchPlayer[] } {
  const map = (p: Squad["picks"][number]): PitchPlayer => ({
    id: p.element_id, name: p.name, position: p.position, code: p.code, team: p.team,
    captain: p.captain, vice: p.vice, meta: p.xp.toFixed(1), hover: { x1: p.xp, price: p.price },
  });
  return { starters: s.picks.filter((p) => p.start).map(map), bench: s.picks.filter((p) => !p.start).map(map) };
}
