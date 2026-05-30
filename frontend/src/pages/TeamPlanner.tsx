import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Check, Crown, Download, Sparkles } from "lucide-react";
import { PageHeader, Card } from "../components/Layout";
import Pitch, { type PitchPlayer } from "../components/Pitch";
import { Button, Mini, Spinner, TextInput } from "../components/ui";
import { api, type PlannerResult, type Squad, type TrackedDetail } from "../lib/api";

export default function TeamPlanner() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [entry, setEntry] = useState("");
  const [season, setSeason] = useState("");
  const [gw, setGw] = useState(1);

  // Prefill from saved settings once they load.
  useEffect(() => {
    const g = settings.data?.general;
    if (!g) return;
    if (g.entry_id != null && entry === "") setEntry(String(g.entry_id));
    if (g.season && season === "") setSeason(g.season);
  }, [settings.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const entryId = entry === "" ? null : Number(entry);

  return (
    <>
      <PageHeader
        title="Team Planner"
        subtitle="Enter your entry id; get model suggestions, transfer + chip planning, and expected points."
        actions={
          <ControlBar
            entry={entry}
            season={season}
            gw={gw}
            onEntry={setEntry}
            onSeason={setSeason}
            onGw={setGw}
          />
        }
      />
      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <div className="grid gap-4">
          {entryId != null && <TrackedTeam entryId={entryId} />}
          {season && <ModelSquad season={season} gw={gw} version={settings.data?.general.active_model ?? "v1"} />}
        </div>
        <div className="grid gap-4">
          {entryId != null && season ? (
            <PlannerPanel entry={entryId} season={season} gw={gw} horizon={settings.data?.general.horizon ?? 6} />
          ) : (
            <Card title="Recommendations">
              <p className="text-sm text-muted-fg">Enter an entry id and season to see transfer, captaincy and chip planning.</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function ControlBar(props: {
  entry: string; season: string; gw: number;
  onEntry: (v: string) => void; onSeason: (v: string) => void; onGw: (v: number) => void;
}) {
  const track = useMutation({ mutationFn: (id: number) => api.trackEntry(id) });
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Mini label="Entry id">
        <TextInput style={{ width: 110 }} inputMode="numeric" value={props.entry} onChange={(e) => props.onEntry(e.target.value)} />
      </Mini>
      <Mini label="Season">
        <TextInput style={{ width: 100 }} placeholder="2024-25" value={props.season} onChange={(e) => props.onSeason(e.target.value)} />
      </Mini>
      <Mini label="GW">
        <TextInput style={{ width: 64 }} type="number" min={1} max={38} value={props.gw} onChange={(e) => props.onGw(Number(e.target.value))} />
      </Mini>
      <Button
        loading={track.isPending}
        done={track.isSuccess}
        icon={track.isSuccess ? <Check className="h-4 w-4" /> : <Download className="h-4 w-4" />}
        disabled={props.entry === ""}
        onClick={() => track.mutate(Number(props.entry))}
        title="Pull the latest roster + prices from FPL and save for daily tracking"
      >
        {track.isSuccess ? "Tracked" : "Track"}
      </Button>
      {track.isError && <span className="text-xs text-destructive">{String(track.error)}</span>}
    </div>
  );
}

function TrackedTeam({ entryId }: { entryId: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["track", entryId],
    queryFn: () => api.trackedEntry(entryId),
    retry: false,
  });
  if (isLoading) return <Card title="Your team"><Loading /></Card>;
  if (error) return <Card title="Your team"><Hint>Not tracked yet — press “Track” to pull this entry’s squad.</Hint></Card>;
  if (!data) return null;
  const { starters, bench } = splitTracked(data);
  return (
    <Card title={`Your team — ${data.name ?? entryId} (GW${data.current_event ?? "?"})`}>
      <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <Stat label="Total pts" value={data.total_points} />
        <Stat label="Rank" value={data.overall_rank?.toLocaleString()} />
        <Stat label="Squad value" value={`£${data.team_value.toFixed(1)}m`} />
        <Stat label="Bank" value={`£${data.bank.toFixed(1)}m`} />
      </div>
      <Pitch starters={starters} bench={bench} />
    </Card>
  );
}

function ModelSquad({ season, gw, version }: { season: string; gw: number; version: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["squad", season, gw, version],
    queryFn: () => api.squad(season, gw, version),
    retry: false,
  });
  return (
    <Card title="Model-suggested XI">
      {isLoading && <Loading />}
      {error && <Hint>No model squad for {season} GW{gw}.</Hint>}
      {data && (
        <>
          <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <Stat label="XI xP" value={data.xi_xp.toFixed(1)} />
            <Stat label="Cost" value={`£${data.total_cost.toFixed(1)}m`} />
            <Stat label="Formation" value={Object.entries(data.formation).filter(([k]) => k !== "GK").map(([, v]) => v).join("-")} />
          </div>
          <Pitch {...splitSquad(data)} />
        </>
      )}
    </Card>
  );
}

function PlannerPanel({ entry, season, gw, horizon }: { entry: number; season: string; gw: number; horizon: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["planner", entry, season, gw, horizon],
    queryFn: () => api.planner(entry, season, gw, { horizon }),
    retry: false,
  });
  return (
    <Card title="Recommendations">
      {isLoading && <Loading />}
      {error && <Hint>{String(error).includes("404") ? "Track this entry first to plan transfers." : String(error)}</Hint>}
      {data && <PlannerBody data={data} />}
    </Card>
  );
}

function PlannerBody({ data }: { data: PlannerResult }) {
  const r = data.rationale;
  return (
    <div className="grid gap-4 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <Stat label="Kind" value={data.kind} />
        <Stat label="EV uplift" value={data.ev_uplift != null ? `${data.ev_uplift.toFixed(2)} pts` : "—"} />
        <Stat label="Confidence" value={data.confidence != null ? `${(data.confidence * 100).toFixed(0)}%` : "—"} />
        <Stat label="Horizon" value={`${r.horizon} GW`} />
      </div>

      <div className="flex items-center gap-2 rounded-md border border-border bg-bg px-3 py-2">
        <Crown className="h-4 w-4 text-accent" />
        <span className="font-medium text-fg">Captain:</span>
        <span>{r.captain.name}</span>
        <span className="tnum ml-auto text-muted-fg">{r.captain.xp_next.toFixed(2)} xP</span>
      </div>

      <div>
        <div className="mb-1 flex items-center gap-2 font-medium text-fg">
          <ArrowRightLeft className="h-4 w-4 text-primary" /> Transfers{r.gw0_hit ? ` (−${r.gw0_hit * 4} hit)` : ""}
        </div>
        {r.transfers_in.length === 0 ? (
          <p className="text-muted-fg">No transfer — hold is optimal.</p>
        ) : (
          <ul className="grid gap-1">
            {r.transfers_in.map((tin, i) => (
              <li key={tin.id} className="flex items-center gap-2">
                <span className="text-destructive">{r.transfers_out[i]?.name ?? "—"}</span>
                <ArrowRightLeft className="h-3 w-3 text-muted-fg" />
                <span className="text-positive">{tin.name}</span>
                <span className="tnum ml-auto text-muted-fg">{tin.xp_next.toFixed(2)} xP</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex items-center gap-2 text-muted-fg">
        <Sparkles className="h-4 w-4" />
        <span>Plan net xP {r.plan_net_xp.toFixed(1)}{r.hold_net_xp != null ? ` vs hold ${r.hold_net_xp.toFixed(1)}` : ""}.</span>
      </div>
    </div>
  );
}

// ---- helpers ----
function splitTracked(d: TrackedDetail): { starters: PitchPlayer[]; bench: PitchPlayer[] } {
  const map = (p: TrackedDetail["picks"][number]): PitchPlayer => ({
    id: p.element_id, name: p.name ?? String(p.element_id), position: p.position,
    code: p.code, captain: p.captain, vice: p.vice,
  });
  const starters = d.picks.filter((p) => (p.slot ?? 99) <= 11).map(map);
  const bench = d.picks.filter((p) => (p.slot ?? 0) > 11).map(map);
  return { starters, bench };
}

function splitSquad(s: Squad): { starters: PitchPlayer[]; bench: PitchPlayer[] } {
  const map = (p: Squad["picks"][number]): PitchPlayer => ({
    id: p.element_id, name: p.name, position: p.position, code: p.code,
    captain: p.captain, vice: p.vice,
    meta: `£${p.price.toFixed(1)} · ${p.xp.toFixed(1)}`,
  });
  return {
    starters: s.picks.filter((p) => p.start).map(map),
    bench: s.picks.filter((p) => !p.start).map(map),
  };
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="grid">
      <span className="text-[11px] uppercase tracking-wide text-muted-fg">{label}</span>
      <span className="tnum font-medium text-fg">{value ?? "—"}</span>
    </span>
  );
}

const Loading = Spinner;
function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-fg">{children}</p>;
}
