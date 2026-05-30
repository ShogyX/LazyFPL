"""Command-line entry point.

    fpl migrate                 # alembic upgrade head
    fpl ingest fpl              # pull bootstrap-static + fixtures
    fpl run <job>               # run a registered orchestrator job once
    fpl budget-report           # per-provider consumption dashboard
    fpl schedule                # start the cron scheduler (blocking)
"""

from __future__ import annotations

import argparse
import json
import sys

from .ingest.api_football import ApiFootballIngestor
from .ingest.availability import AvailabilityIngestor
from .ingest.budget import BudgetTracker
from .ingest.clubelo import ClubEloIngestor
from .ingest.elite import EliteCohortIngestor
from .ingest.fetch import FetchClient
from .ingest.fpl import FplIngestor
from .ingest.providers import PROVIDERS
from .ingest.understat import UnderstatIngestor
from .ingest.vaastav import VaastavIngestor
from .logging_setup import get_logger
from .orchestrator import Job, Orchestrator
from .features.availability import AvailabilityBuilder
from .features.families import FeatureMatrixBuilder
from .features.panel import PanelBuilder
from .backtest import Backtester
from .ingest.entry import EntryIngestor
from .model.freeze import WeightFreezer, freeze_ensemble
from .model.predict import prediction_server
from .model.recommend import RecommendationEngine
from .model.study import PredictiveValidityStudy
from .notify import NotificationService
from .optimise import (
    SquadOptimizer,
    TransferPlanner,
    load_candidates,
    load_horizon_candidates,
    rolling_greedy,
)
from .resolve import CrosswalkBuilder
from .store.advanced import AdvancedStatsBuilder
from .store.dc import DcReconstructor
from .store.facts import FactBuilder
from .store.targets import TargetBuilder

log = get_logger("fpl.cli")


def _current_season(fetch: FetchClient | None = None) -> str:
    """The season the engine is operating in. Derived dynamically from the live
    FPL calendar (GW1 deadline year) so a brand-new season is picked up the
    moment the API publishes it; falls back to the latest known season."""
    if fetch is not None:
        try:
            from datetime import datetime
            boot = fetch.get("fpl", "/bootstrap-static/", cache_ttl=0).payload
            events = boot.get("events", []) if isinstance(boot, dict) else []
            ds = [e.get("deadline_time") for e in events if e.get("deadline_time")]
            if ds:
                y = min(datetime.fromisoformat(d.replace("Z", "+00:00")) for d in ds).year
                return f"{y}-{(y + 1) % 100:02d}"
        except Exception:
            pass
    return VaastavIngestor.SEASONS[-1]


def _current_gw(fetch: FetchClient) -> int | None:
    """Next unfinished gameweek from the FPL bootstrap (the one to predict);
    falls back to the latest finished GW, or None pre-season."""
    boot = fetch.get("fpl", "/bootstrap-static/", cache_ttl=0).payload
    events = boot.get("events", []) if isinstance(boot, dict) else []
    upcoming = [int(e["id"]) for e in events if not e.get("finished") and e.get("id")]
    if upcoming:
        return min(upcoming)
    finished = [int(e["id"]) for e in events if e.get("finished") and e.get("id")]
    return max(finished) if finished else None


def _servable_gws(season: str, want: list[int]) -> list[int]:
    """Of the requested GWs, those that have a built feature panel. If none do,
    fall back to the single latest GW with ``training_rows`` (guards an
    FPL-vs-data mismatch, e.g. a frozen snapshot lagging the live calendar)."""
    from sqlalchemy import func, select
    from .db.engine import get_sessionmaker
    from .db.models import training_rows
    tr = training_rows.c
    with get_sessionmaker()() as s:
        have = {int(r[0]) for r in s.execute(
            select(tr.gw).distinct().where(tr.season == season)).all()}
        servable = [g for g in want if g in have]
        if servable:
            return servable
        latest = s.execute(select(func.max(tr.gw)).where(tr.season == season)).scalar_one_or_none()
        return [int(latest)] if latest is not None else []


def refresh_predictions(fetch: FetchClient, *, version: str = "v1",
                        horizon: int = 6) -> dict[int, int] | None:
    """Hands-off pipeline so served predictions stay fresh for the whole
    planning horizon. Detects the current season + next GW from the live FPL
    calendar, pulls/builds that season's data (incl. the upcoming-GW feature
    rows), and predicts every GW from the next one out to ``horizon`` ahead.

    Each stage is wrapped so one failure is logged and skipped rather than
    aborting the scheduler. Returns {gw: n_players} (or None if nothing to do).
    """
    # Always refresh live current-state first (prices, status, fixtures), then
    # derive the season/GW from that fresh calendar.
    for name, fn in (("bootstrap", FplIngestor(fetch).ingest_bootstrap),
                     ("fixtures", FplIngestor(fetch).ingest_fixtures)):
        try:
            fn()
        except Exception as exc:
            log.warning("refresh ingest failed", extra={"stage": name, "error": str(exc)})

    season = _current_season(fetch)
    gw = _current_gw(fetch)
    if gw is None:
        log.info("refresh_predictions: no current GW (pre-season?)")
        return None

    fb = FactBuilder(VaastavIngestor(fetch))
    stages = (
        ("crosswalk", lambda: CrosswalkBuilder(VaastavIngestor(fetch)).build_fpl([season])),
        ("facts", lambda: (fb.build_player_match_stats([season]), fb.build_team_match_stats([season]))),
        ("targets", lambda: TargetBuilder().build(seasons=[season])),
        # include_upcoming -> emit target-less feature rows for the next GWs so
        # the upcoming (unplayed) gameweeks are forecastable, not just past ones.
        ("panel", lambda: PanelBuilder().build(
            seasons=[season], include_upcoming=True, upcoming_season=season,
            upcoming_horizon=horizon + 2)),
    )
    for name, fn in stages:
        try:
            fn()
        except Exception as exc:  # keep the scheduler alive
            log.warning("refresh stage failed", extra={"stage": name, "season": season, "error": str(exc)})

    want = list(range(gw, gw + horizon))
    target_gws = _servable_gws(season, want)
    if target_gws != want:
        log.info("refresh_predictions: serving available GWs",
                 extra={"requested": want, "servable": target_gws})
    if not target_gws:
        log.info("refresh_predictions: no servable GW with feature rows")
        return None

    server = prediction_server(version=version)
    out: dict[int, int] = {}
    for g in target_gws:
        try:
            out[g] = server.predict_gw(season, g).n_players
        except Exception as exc:
            log.warning("predict stage failed", extra={"season": season, "gw": g, "error": str(exc)})
    log.info("refresh_predictions done",
             extra={"season": season, "version": version, "gws": list(out), "by_gw": out})
    return out or None


def _default_recompute(fetch: FetchClient):
    """Build the recompute fired by triggers (price move / news flip / results
    confirmed): regenerate current-GW predictions, refresh the operator entry,
    and emit a fresh recommendation. Triggers fire only on material change, so
    this runs the full pipeline just when something actually moved."""
    from .config import get_settings

    def recompute() -> None:
        refresh_predictions(fetch)
        entry_id = get_settings().fpl_entry_id
        if entry_id is None:
            log.info("recompute: no FPL_FPL_ENTRY_ID configured; skipped entry/recommendation")
            return
        try:
            ing = EntryIngestor(fetch)
            ing.ingest_entry(entry_id)
            roster = set(ing.latest_roster(entry_id))
            gw = _current_gw(fetch)
            if len(roster) == 15 and gw is not None:
                bank, purchase = ing.resolve_budget(entry_id)
                RecommendationEngine().generate(
                    _current_season(fetch), gw, roster, entry_id=entry_id,
                    bank=bank, purchase=purchase)
            log.info("recompute: entry + recommendation refreshed", extra={"entry_id": entry_id})
        except Exception as exc:
            log.warning("recompute entry/recommendation failed",
                        extra={"entry_id": entry_id, "error": str(exc)})

    return recompute


def _elite_refresh(fetch: FetchClient):
    """Forward elite-cohort collection: enumerate the cohort, then capture +
    aggregate picks for the latest finished GW. Enables a season-long elite-EO
    dataset (the predictive-emulation use is iced pending historical picks)."""
    def run() -> None:
        ing = EliteCohortIngestor(fetch)
        ing.enumerate_cohort(max_managers=200)
        boot = fetch.get("fpl", "/bootstrap-static/", cache_ttl=0).payload
        events = boot.get("events", []) if isinstance(boot, dict) else []
        finished = [e["id"] for e in events if e.get("finished")]
        if not finished:
            return
        gw = max(finished)
        ing.ingest_picks(gw)
        ing.aggregate_ownership(gw)
    return run


def build_orchestrator() -> tuple[Orchestrator, FetchClient]:
    from .orchestrator import TriggerEngine

    fetch = FetchClient()
    fpl = FplIngestor(fetch)
    orch = Orchestrator()
    triggers = TriggerEngine(fetch, _default_recompute(fetch))
    # Polite hourly refresh.
    orch.register(Job("fpl_bootstrap", fpl.ingest_bootstrap, cron="0 * * * *"))
    orch.register(Job("fpl_fixtures", fpl.ingest_fixtures, cron="15 * * * *"))
    # Hands-off prediction refresh: rebuild current-GW xP every 6h as a baseline
    # (triggers below also refresh on material change). Keeps serving predictions
    # fresh without manual `fpl predict` runs.
    orch.register(Job("refresh_predictions", lambda: refresh_predictions(fetch),
                      cron="20 */6 * * *"))
    # Concrete continuous triggers (plan 9.3): each detects change + recomputes.
    orch.register(Job("price_watch", triggers.price_watch, cron="30 1 * * *"))
    orch.register(Job("news_lineup_watch", triggers.news_lineup_watch, cron="*/30 * * * *"))
    orch.register(Job("post_match_recompute", triggers.post_match_recompute,
                      cron="*/15 * * * *"))
    # Weekly elite-cohort collection (post-deadline): builds a season-long
    # elite-EO dataset that the recommendation EO overlay consumes.
    orch.register(Job("elite_refresh", _elite_refresh(fetch), cron="0 6 * * 2"))
    return orch, fetch


def cmd_migrate(_: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    if args.source != "fpl":
        log.error("unknown ingest source", extra={"source": args.source})
        return 2
    fetch = FetchClient()
    try:
        fpl = FplIngestor(fetch)
        boot = fpl.ingest_bootstrap()
        fixtures = fpl.ingest_fixtures()
    finally:
        fetch.close()
    print(json.dumps({
        "snapshot_id": boot.snapshot_id, "deduped": boot.deduped,
        "teams": boot.teams, "players": boot.players, "fixtures": fixtures,
    }))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    orch, fetch = build_orchestrator()
    try:
        result = orch.run_once(args.job)
    finally:
        fetch.close()
    print(json.dumps({"job": args.job, "ok": True, "result": str(result)}))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    seasons = args.seasons or None
    fetch = FetchClient()
    try:
        vaastav = VaastavIngestor(fetch)
        if args.action == "acquire":
            res = vaastav.acquire(seasons=seasons)
            summary = {
                "files_total": len(res.files),
                "files_ok": len(res.ok()),
                "rows_total": sum(f.rows for f in res.ok()),
            }
            if args.clubelo:
                summary["clubelo_clubs"] = ClubEloIngestor(fetch).ingest()
            print(json.dumps(summary, indent=2))
        elif args.action == "coverage":
            print(json.dumps(vaastav.coverage(), indent=2))
    finally:
        fetch.close()
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    fetch = FetchClient()
    try:
        vaastav = VaastavIngestor(fetch)
        builder = CrosswalkBuilder(vaastav)
        rows = builder.build_fpl(seasons=args.seasons or None)
        coverage = builder.fpl_coverage(seasons=args.seasons or None)
    finally:
        fetch.close()
    print(json.dumps({"crosswalk_rows": rows, "fpl_coverage": coverage}, indent=2))
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    fetch = FetchClient()
    try:
        builder = FactBuilder(VaastavIngestor(fetch))
        players = [r.__dict__ for r in builder.build_player_match_stats(args.seasons or None)]
        teams = [r.__dict__ for r in builder.build_team_match_stats(args.seasons or None)]
        recon = builder.reconcile(args.seasons or None)
    finally:
        fetch.close()
    print(json.dumps({"player_match": players, "team_match": teams,
                      "reconcile": recon}, indent=2, default=str))
    return 0


def cmd_elite(args: argparse.Namespace) -> int:
    """Elite cohort: enumerate top managers, pull picks, aggregate EO."""
    fetch = FetchClient()
    try:
        ing = EliteCohortIngestor(fetch)
        if args.action == "enumerate":
            res = ing.enumerate_cohort(max_managers=args.max_managers)
            out = {"league": res.league, "managers": res.managers}
        elif args.action == "picks":
            out = {"event": args.event, "rows": ing.ingest_picks(args.event)}
        else:  # aggregate
            res = ing.aggregate_ownership(args.event)
            out = {"event": res.event, "managers": res.n_managers,
                   "elements": res.elements}
    finally:
        fetch.close()
    print(json.dumps(out, indent=2))
    return 0


def cmd_availability(_: argparse.Namespace) -> int:
    """Snapshot FPL availability (status/news/chance), detecting flips."""
    fetch = FetchClient()
    try:
        res = AvailabilityIngestor(fetch).snapshot_from_bootstrap()
    finally:
        fetch.close()
    print(json.dumps({"scanned": res.scanned, "flips": res.flips}))
    return 0


def cmd_apifootball(args: argparse.Namespace) -> int:
    """API-Football free-tier: lineups (per fixture), injuries, referees."""
    fetch = FetchClient()
    try:
        ing = ApiFootballIngestor(fetch)
        if args.action == "lineups":
            n = ing.ingest_lineups(args.fixture)
        elif args.action == "injuries":
            n = ing.ingest_injuries(args.season_year)
        else:  # referees
            n = ing.ingest_referees(args.season_year)
    finally:
        fetch.close()
    print(json.dumps({"action": args.action, "rows": n}))
    return 0


def cmd_advanced(args: argparse.Namespace) -> int:
    """Understat advanced-stats pipeline: acquire raw pages, then normalise."""
    fetch = FetchClient()
    try:
        understat = UnderstatIngestor(fetch)
        seasons = args.seasons or list(UnderstatIngestor.SEASONS)
        if args.action == "acquire":
            out = []
            for season in seasons:
                res = understat.acquire_season(season, max_matches=args.max_matches)
                out.append({"season": season,
                            "league_ok": bool(res.league and res.league.status == 200),
                            "matches_ok": len(res.ok_matches())})
            print(json.dumps({"understat": out}, indent=2))
        elif args.action == "build":
            builder = AdvancedStatsBuilder(understat, CrosswalkBuilder(VaastavIngestor(fetch)))
            results = [r.__dict__ for r in builder.build_understat(seasons)]
            print(json.dumps({"understat_build": results}, indent=2, default=str))
    finally:
        fetch.close()
    return 0


def cmd_dc(args: argparse.Namespace) -> int:
    recon = DcReconstructor()
    built = [r.__dict__ for r in recon.build(seasons=args.seasons or None)]
    validation = {}
    for season in (args.seasons or [r["season"] for r in built]):
        v = recon.validate_against_official(season)
        if v.n:
            validation[season] = v.__dict__
    print(json.dumps({"built": built, "validation": validation}, indent=2, default=str))
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    builder = TargetBuilder()
    built = [r.__dict__ for r in builder.build(seasons=args.seasons or None)]
    repro = {r["season"]: builder.reproduction(r["season"]).__dict__ for r in built}
    print(json.dumps({"built": built, "reproduction": repro}, indent=2, default=str))
    return 0


def cmd_features(args: argparse.Namespace) -> int:
    seasons = args.seasons or None
    if args.action == "availability":
        rows = AvailabilityBuilder().build(seasons=seasons)
        by_season: dict[str, int] = {}
        for r in rows:
            by_season[r.season] = by_season.get(r.season, 0) + 1
        print(json.dumps({"metrics_x_seasons": len(rows), "seasons": by_season}, indent=2))
    elif args.action == "panel":
        built = [r.__dict__ for r in PanelBuilder().build(seasons=seasons)]
        print(json.dumps({"built": built}, indent=2))
    elif args.action == "audit":
        season = seasons[0] if seasons else None
        pb = PanelBuilder()
        print(json.dumps({
            "by_construction": pb.leakage_audit(season=season),
            "independent": pb.independent_leakage_audit(season=season),
        }, indent=2, default=str))
    elif args.action == "matrix":
        season = (seasons or [None])[0]
        m = FeatureMatrixBuilder().assemble(season, args.position)
        families = {f: {"metrics": list(spec.metrics), "sources": list(spec.sources),
                        "n_feature_keys": len(spec.feature_keys)}
                    for f, spec in m.families.items()}
        print(json.dumps({"season": season, "position": args.position,
                          "n_rows": len(m.rows), "families": families}, indent=2))
    return 0


def cmd_study(args: argparse.Namespace) -> int:
    study = PredictiveValidityStudy(study_version=args.version)
    positions = [args.position] if args.position else (1, 2, 3, 4)
    results = study.run(positions=positions, seasons=args.seasons or None)
    print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    freezer = WeightFreezer(study_version=args.study_version, registry_version=args.version)
    cells = freezer.freeze(holdout_season=args.holdout)
    print(json.dumps({"version": args.version,
                      "cells": [c.__dict__ for c in cells]}, indent=2, default=str))
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    if args.component:
        from .model.components import ComponentPredictor
        res = ComponentPredictor(model_version=args.version).predict_gw(args.season, args.gw)
    else:
        res = prediction_server(version=args.version).predict_gw(args.season, args.gw)
    print(json.dumps(res.__dict__, indent=2, default=str))
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """Run the full current-GW prediction pipeline once (facts -> targets ->
    panel -> predict). The scheduler runs this automatically; this is the manual
    equivalent."""
    fetch = FetchClient()
    try:
        season = _current_season(fetch)
        by_gw = refresh_predictions(fetch, version=args.version, horizon=args.horizon)
    finally:
        fetch.close()
    print(json.dumps({"season": season, "predicted_by_gw": by_gw}, default=str))
    return 0 if by_gw else 1


def cmd_freeze_ensemble(args: argparse.Namespace) -> int:
    eval_gws = (list(range(args.eval_from, args.eval_to + 1))
                if args.eval_from and args.eval_to else None)
    out = freeze_ensemble(registry_version=args.version, train_season=args.train_season,
                          choice=args.choice, eval_season=args.eval_season, eval_gws=eval_gws)
    print(json.dumps(out, indent=2, default=str))
    return 0


def _pos(k: int) -> str:
    return ("GK", "DEF", "MID", "FWD")[k - 1]


def cmd_optimise(args: argparse.Namespace) -> int:
    if args.what == "transfers":
        return _cmd_transfers(args)
    candidates = load_candidates(args.season, args.gw, model_version=args.version)
    sol = SquadOptimizer(budget=args.budget).solve(candidates)
    starters = sorted([p for p in sol.picks if p.is_start],
                      key=lambda p: (p.position, -p.xp))
    bench = sorted([p for p in sol.picks if not p.is_start], key=lambda p: p.position)
    print(json.dumps({
        "status": sol.status, "n_candidates": len(candidates),
        "total_cost": sol.total_cost / 10, "xi_xp": sol.xi_xp,
        "formation": {("GK", "DEF", "MID", "FWD")[k - 1]: v
                      for k, v in sol.formation.items()},
        "starting_xi": [
            {"name": p.name, "pos": ("GK", "DEF", "MID", "FWD")[p.position - 1],
             "price": p.price / 10, "xp": round(p.xp, 2),
             "C": p.is_captain, "V": p.is_vice} for p in starters],
        "bench": [{"name": p.name, "pos": ("GK", "DEF", "MID", "FWD")[p.position - 1],
                   "price": p.price / 10, "xp": round(p.xp, 2)} for p in bench],
    }, indent=2))
    return 0


def _cmd_transfers(args: argparse.Namespace) -> int:
    gws = list(range(args.from_gw, args.from_gw + args.horizon))
    # initial squad = optimal squad for the first horizon GW
    gw1 = load_candidates(args.season, gws[0], model_version=args.version)
    init = SquadOptimizer().solve(gw1)
    if not init.feasible:
        print(json.dumps({"status": "no_initial_squad"}))
        return 1
    initial_ids = {p.id for p in init.picks}
    names = {p.id: p.name for p in init.picks}

    cands = load_horizon_candidates(args.season, gws, model_version=args.version,
                                    include_ids=initial_ids)
    names.update({c.id: c.name for c in cands})
    planner = TransferPlanner()
    plan = planner.plan(initial_ids, cands, initial_ft=args.ft, horizon=args.horizon)
    greedy_net, _ = rolling_greedy(planner, initial_ids, cands,
                                   initial_ft=args.ft, horizon=args.horizon)

    print(json.dumps({
        "status": plan.status,
        "horizon": plan.horizon,
        "net_xp": plan.net_xp,
        "gross_xp": plan.gross_xp,
        "total_hits": plan.total_hits,
        "rolling_greedy_net_xp": greedy_net,
        "uplift_vs_greedy": round(plan.net_xp - greedy_net, 3),
        "path": [{
            "gw": gws[g.gw_index], "ft": g.ft_available, "hit": g.hit,
            "captain": names.get(g.captain, g.captain),
            "in": [names.get(i, i) for i in g.transfers_in],
            "out": [names.get(i, i) for i in g.transfers_out],
            "xi_xp": g.xi_xp,
        } for g in plan.gws],
    }, indent=2))
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    fetch = FetchClient()
    try:
        ingestor = EntryIngestor(fetch)
        res = ingestor.ingest_entry(args.entry)
        # Authed pull (exact selling/purchase prices + live bank) when a cookie
        # is configured; degrades gracefully and flags re-auth otherwise.
        my = ingestor.ingest_my_team(args.entry)
    finally:
        fetch.close()
    out = {"entry_id": res.entry_id, "name": res.name,
           "current_event": res.current_event,
           "team_value": (res.team_value or 0) / 10,
           "new_transfers": res.new_transfers,
           "roster_size": len(res.roster),
           "authed": my.authenticated}
    if my.authenticated:
        out["authed_bank"] = (my.bank or 0) / 10
        out["authed_picks"] = my.picks
    elif my.needs_reauth:
        out["needs_reauth"] = True
        out["auth_reason"] = my.reason
    print(json.dumps(out, indent=2))
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    bank: int | None = None
    purchase: dict[int, int] | None = None
    if args.entry:
        ingestor = EntryIngestor(FetchClient())
        roster = set(ingestor.latest_roster(args.entry))
        if not roster:
            print(json.dumps({"error": "no tracked roster; run `track` first"}))
            return 1
        # Real bank + per-player purchase costs -> value-aware budget. As held
        # players appreciate, the planner's affordable range grows; as they
        # drop, it shrinks. Without this the model would lock to a flat £100m.
        bank, purchase = ingestor.resolve_budget(args.entry)
    else:  # demo path: use the optimiser's squad as the current roster
        sol = SquadOptimizer().solve(load_candidates(args.season, args.from_gw,
                                                     model_version=args.version))
        roster = {p.id for p in sol.picks}

    # Elite-cohort effective ownership overlay: when --eo-weight is set, use the
    # latest elite EO for the GW as the ownership signal (template-protect /
    # differential-chase). Falls back silently to pure xP if no cohort data.
    eo_override = None
    if args.eo_weight:
        from .ingest.elite import latest_elite_eo
        eo_override = latest_elite_eo(args.from_gw) or None

    engine = RecommendationEngine(model_version=args.version)
    rec = engine.generate(args.season, args.from_gw, roster,
                          horizon=args.horizon, initial_ft=args.ft,
                          entry_id=args.entry, bank=bank, purchase=purchase,
                          eo_override=eo_override, eo_weight=args.eo_weight)

    out = {"kind": rec.kind, "ev_uplift": rec.ev, "confidence": rec.confidence,
           "captain": rec.rationale["captain"]["name"],
           "transfers_in": [t["name"] for t in rec.rationale["transfers_in"]],
           "transfers_out": [t["name"] for t in rec.rationale["transfers_out"]],
           "gw0_hit": rec.rationale["gw0_hit"],
           "eo_weight": args.eo_weight,
           "elite_eo_players": len(eo_override) if eo_override else 0}
    if args.notify:
        svc = NotificationService.from_settings(ev_threshold=args.ev_threshold)
        subject = f"FPL GW{args.from_gw}: captain {out['captain']}"
        short = f"C: {out['captain']}; IN {out['transfers_in']} OUT {out['transfers_out']}"
        detail = json.dumps(rec.rationale, indent=2)
        out["notified"] = svc.notify(rec.kind, subject, short, ev=rec.ev,
                                     confidence=rec.confidence, detail=detail)
    print(json.dumps(out, indent=2))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from .model.analysis import PredictorAnalysis
    from .model.predictors import default_predictors

    gws = list(range(args.from_gw, args.to_gw + 1))
    rep = PredictorAnalysis().analyse(args.season, gws, default_predictors())
    print(json.dumps({
        "season": args.season, "gws": f"{args.from_gw}-{args.to_gw}",
        "rows": rep.n_rows, "n_gws": rep.n_gws,
        "overall_ic": dict(sorted(rep.overall_ic.items(),
                                  key=lambda kv: kv[1], reverse=True)),
        "fraction_best": dict(sorted(rep.fraction_best.items(),
                                     key=lambda kv: kv[1], reverse=True)),
        "most_complementary_pair": rep.most_complementary_pair,
        "mean_pairwise_signal_corr": _mean_offdiag(rep.signal_correlation),
        "mean_per_gw_ic_corr": _mean_offdiag(rep.per_gw_ic_correlation),
    }, indent=2, default=str))
    return 0


def _mean_offdiag(matrix: dict) -> float | None:
    vals = [v for a, row in matrix.items() for b, v in row.items()
            if a != b and v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _prior_season(season: str) -> str:
    """'2024-25' -> '2023-24' (the natural causal training season)."""
    y = int(season.split("-")[0])
    return f"{y - 1}-{str(y)[2:]}"


def _build_backtest_predictors(season: str, from_gw: int, *, with_ensembles: bool,
                               with_component: bool, with_stack: bool,
                               train_season: str | None,
                               include_model: bool = True) -> dict:
    """Assemble the predictor set for a backtest (shared by single + multi).

    ``include_model=False`` drops the frozen ``model:v1`` (and keeps it out of
    the blends) — used for a leakage-free cross-season read, since v1 was fit on
    some of the seasons being evaluated.
    """
    from .model.analysis import PredictorAnalysis
    from .model.predictors import build_ensembles, default_predictors

    def _train_window():
        if train_season and train_season != season:
            return train_season, list(range(1, 39))
        return season, list(range(1, max(from_gw, 2)))

    preds = default_predictors(include_model=include_model)
    # Component model first so it feeds the ensembles/stack as a base signal
    # (carries xG/clean-sheet/minutes information the form signals lack).
    if with_component:
        from .model.components import ComponentScorePredictor
        preds["component:c1"] = ComponentScorePredictor()
    if with_ensembles:
        ts, tg = _train_window()
        rep = PredictorAnalysis().analyse(ts, tg, preds)
        preds = {**preds, **build_ensembles(rep, preds)}
    if with_stack:
        from .model.stacking import fit_stack
        ts, tg = _train_window()
        base = default_predictors(include_model=include_model)
        if with_component:
            from .model.components import ComponentScorePredictor
            base["component:c1"] = ComponentScorePredictor()
        # Augment the meta-learner with causal context features (opponent
        # strength + trailing minutes) so it can condition its weights.
        stack = fit_stack(base, ts, tg,
                          meta_features=("opp_def", "opp_att", "minutes__mean_5"))
        preds[stack.name] = stack
    return preds


def cmd_backtest(args: argparse.Namespace) -> int:
    gws = list(range(args.from_gw, args.to_gw + 1))
    preds = _build_backtest_predictors(
        args.season, args.from_gw, with_ensembles=args.with_ensembles,
        with_component=args.with_component, with_stack=args.with_stack,
        train_season=args.train_season, include_model=not args.no_model)
    if args.predictors:
        wanted = set(args.predictors)
        preds = {k: v for k, v in preds.items() if k in wanted}
        if not preds:
            print(json.dumps({"error": "no matching predictors"}))
            return 2
    results = Backtester(model_version=args.version, ft_value=args.ft_value,
                         free_hit=args.free_hit).compare(args.season, gws, preds)
    ranking = sorted(results.values(), key=lambda r: r.net_with_chips, reverse=True)
    print(json.dumps({
        "season": args.season, "gws": f"{args.from_gw}-{args.to_gw}",
        "ranking": [{"approach": r.strategy, "points": r.total_points,
                     "hits": r.total_hits, "net": r.net_points,
                     "chip_bonus": r.chip_bonus, "net_with_chips": r.net_with_chips}
                    for r in ranking],
        "best": ranking[0].strategy if ranking else None,
        "best_chips": ranking[0].chips if ranking else None,
    }, indent=2))
    return 0


def cmd_backtest_multi(args: argparse.Namespace) -> int:
    """Backtest the same configuration across several eval seasons (each trained
    on the prior season) to gauge robustness vs single-season luck."""
    gws = list(range(args.from_gw, args.to_gw + 1))
    focus = args.focus
    rows: list[dict] = []
    for season in args.seasons:
        train = args.train_season or _prior_season(season)
        preds = _build_backtest_predictors(
            season, args.from_gw, with_ensembles=True,
            with_component=args.with_component, with_stack=args.with_stack,
            train_season=train, include_model=not args.no_model)
        results = Backtester(model_version=args.version,
                             ft_value=args.ft_value).compare(season, gws, preds)
        ranking = sorted(results.values(), key=lambda r: r.net_with_chips, reverse=True)
        fr = next((r for r in ranking if r.strategy == focus), None)
        rows.append({
            "season": season, "train": train,
            "best": ranking[0].strategy if ranking else None,
            "best_net_with_chips": ranking[0].net_with_chips if ranking else None,
            "focus_net": fr.net_points if fr else None,
            "focus_net_with_chips": fr.net_with_chips if fr else None,
        })
    nets = [r["focus_net_with_chips"] for r in rows if r["focus_net_with_chips"]]
    print(json.dumps({
        "focus": focus, "seasons": rows,
        "focus_mean": round(sum(nets) / len(nets), 1) if nets else None,
        "focus_min": min(nets) if nets else None,
        "focus_max": max(nets) if nets else None,
    }, indent=2))
    return 0


def cmd_odds(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .ingest.odds_providers import auth_for
    from .odds import OddsStore

    if args.action == "status":
        s = get_settings()
        providers = ["api_football", "oddsapi_io", "sharpapi", "sgo", "oddspapi", "betfair"]
        print(json.dumps({"enabled": {p: auth_for(p, s)[2] for p in providers}}, indent=2))
    elif args.action == "consensus":
        res = OddsStore().build_consensus(args.event, args.market)
        print(json.dumps({"event": args.event, "market": args.market,
                          "n_sources": res.n_sources, "sharp_present": res.sharp_present,
                          "probs": {k: round(v, 4) for k, v in res.probs.items()}},
                         indent=2))
    return 0


def cmd_budget_report(_: argparse.Namespace) -> int:
    tracker = BudgetTracker()
    report = {}
    for name in PROVIDERS:
        report[name] = {
            "limits": PROVIDERS[name].limits.configured(),
            "usage": tracker.usage(name),
            "remaining": tracker.remaining(name),
        }
    print(json.dumps(report, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run("fpl_engine.api.app:app", host=args.host, port=args.port)
    return 0


def cmd_schedule(_: argparse.Namespace) -> int:
    import time

    orch, fetch = build_orchestrator()
    orch.start()
    log.info("scheduler started; ctrl-c to exit")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("scheduler stopping")
    finally:
        fetch.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fpl", description="FPL Intelligence Engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="run DB migrations to head").set_defaults(fn=cmd_migrate)

    ing = sub.add_parser("ingest", help="run an ingestor")
    ing.add_argument("source", choices=["fpl"])
    ing.set_defaults(fn=cmd_ingest)

    run = sub.add_parser("run", help="run a registered job once")
    run.add_argument("job")
    run.set_defaults(fn=cmd_run)

    hist = sub.add_parser("history", help="historical acquisition / coverage")
    hist.add_argument("action", choices=["acquire", "coverage"])
    hist.add_argument("--seasons", nargs="*", help="limit to these seasons")
    hist.add_argument("--clubelo", action="store_true", help="also ingest ClubElo")
    hist.set_defaults(fn=cmd_history)

    res = sub.add_parser("resolve", help="build FPL identity crosswalk")
    res.add_argument("--seasons", nargs="*")
    res.set_defaults(fn=cmd_resolve)

    facts = sub.add_parser("facts", help="build normalised per-match fact tables")
    facts.add_argument("--seasons", nargs="*")
    facts.set_defaults(fn=cmd_facts)

    el = sub.add_parser("elite", help="elite cohort: enumerate / picks / aggregate EO")
    el.add_argument("action", choices=["enumerate", "picks", "aggregate"])
    el.add_argument("--max-managers", type=int, default=500)
    el.add_argument("--event", type=int, default=None, help="GW for picks/aggregate")
    el.set_defaults(fn=cmd_elite)

    sub.add_parser("availability",
                   help="snapshot FPL status/news/chance (flip detection)").set_defaults(
        fn=cmd_availability)

    af = sub.add_parser("apifootball", help="API-Football lineups / injuries / referees")
    af.add_argument("action", choices=["lineups", "injuries", "referees"])
    af.add_argument("--fixture", help="API-Football fixture id (lineups)")
    af.add_argument("--season-year", type=int, default=None,
                    help="season start year, e.g. 2024 (injuries/referees)")
    af.set_defaults(fn=cmd_apifootball)

    adv = sub.add_parser("advanced",
                         help="Understat advanced stats: acquire raw pages then normalise")
    adv.add_argument("action", choices=["acquire", "build"])
    adv.add_argument("--seasons", nargs="*")
    adv.add_argument("--max-matches", type=int, default=None,
                     help="cap matches per season (partial/test runs)")
    adv.set_defaults(fn=cmd_advanced)

    dc = sub.add_parser("dc", help="reconstruct Defensive Contribution + validate")
    dc.add_argument("--seasons", nargs="*")
    dc.set_defaults(fn=cmd_dc)

    tgt = sub.add_parser("targets", help="build rule-invariant targets + reproduction check")
    tgt.add_argument("--seasons", nargs="*")
    tgt.set_defaults(fn=cmd_targets)

    feat = sub.add_parser("features", help="feature engineering (availability/panel/audit/matrix)")
    feat.add_argument("action", choices=["availability", "panel", "audit", "matrix"])
    feat.add_argument("--seasons", nargs="*")
    feat.add_argument("--position", type=int, choices=[1, 2, 3, 4], default=3)
    feat.set_defaults(fn=cmd_features)

    st = sub.add_parser("study", help="run predictive-validity study")
    st.add_argument("--seasons", nargs="*")
    st.add_argument("--position", type=int, choices=[1, 2, 3, 4])
    st.add_argument("--version", default="v1-dev")
    st.set_defaults(fn=cmd_study)

    fz = sub.add_parser("freeze", help="shrinkage + holdout + freeze weights")
    fz.add_argument("--holdout", help="holdout season (default: last)")
    fz.add_argument("--study-version", default="v1-dev")
    fz.add_argument("--version", default="v1")
    fz.set_defaults(fn=cmd_freeze)

    pr = sub.add_parser("predict", help="serve xP from frozen weights (v1 or ensemble v2)")
    pr.add_argument("--season", required=True)
    pr.add_argument("--gw", type=int, required=True)
    pr.add_argument("--version", default="v1")
    pr.add_argument("--component", action="store_true",
                    help="use the §C.1 bottom-up component predictor (minutes-gated)")
    pr.set_defaults(fn=cmd_predict)

    rf = sub.add_parser("refresh", help="run the full current-GW pipeline once (ingest->facts->targets->panel->predict for the next N GWs)")
    rf.add_argument("--version", default="v1")
    rf.add_argument("--horizon", type=int, default=6, help="predict the next N GWs")
    rf.set_defaults(fn=cmd_refresh)

    fe = sub.add_parser("freeze-ensemble", help="freeze an ensemble as a versioned model")
    fe.add_argument("--version", default="v2")
    fe.add_argument("--train-season", default="2024-25")
    fe.add_argument("--choice", default="rank_top3",
                    help="ic_weighted | rank_top3 | per_position | ict_heavy")
    fe.add_argument("--eval-season")
    fe.add_argument("--eval-from", type=int)
    fe.add_argument("--eval-to", type=int)
    fe.set_defaults(fn=cmd_freeze_ensemble)

    op = sub.add_parser("optimise", help="run the optimiser")
    op.add_argument("what", choices=["squad", "transfers"])
    op.add_argument("--season", required=True)
    op.add_argument("--gw", type=int, default=1, help="GW for squad optimisation")
    op.add_argument("--from-gw", type=int, default=1, help="first GW for transfer plan")
    op.add_argument("--horizon", type=int, default=6)
    op.add_argument("--ft", type=int, default=1, help="free transfers available now")
    op.add_argument("--version", default="v1")
    op.add_argument("--budget", type=int, default=1000)
    op.set_defaults(fn=cmd_optimise)

    tk = sub.add_parser("track", help="ingest a tracked FPL entry + detect transfers")
    tk.add_argument("entry", type=int)
    tk.set_defaults(fn=cmd_track)

    rc = sub.add_parser("recommend", help="generate transfer/captain recommendation")
    rc.add_argument("--season", required=True)
    rc.add_argument("--from-gw", type=int, required=True)
    rc.add_argument("--entry", type=int, help="tracked entry id (else demo squad)")
    rc.add_argument("--horizon", type=int, default=6)
    rc.add_argument("--ft", type=int, default=1)
    rc.add_argument("--version", default="v1")
    rc.add_argument("--eo-weight", type=float, default=0.0,
                    help="elite-EO overlay: >0 protect template, <0 chase differentials")
    rc.add_argument("--notify", action="store_true")
    rc.add_argument("--ev-threshold", type=float, default=1.0)
    rc.set_defaults(fn=cmd_recommend)

    bt = sub.add_parser("backtest", help="replay a season vs baselines")
    bt.add_argument("--season", required=True)
    bt.add_argument("--from-gw", type=int, required=True)
    bt.add_argument("--to-gw", type=int, required=True)
    bt.add_argument("--version", default="v1")
    bt.add_argument("--predictors", nargs="*",
                    help="subset of predictors to compare (default: all)")
    bt.add_argument("--with-ensembles", action="store_true",
                    help="add IC-weighted / ICT-heavy / rank / per-position blends")
    bt.add_argument("--with-component", action="store_true",
                    help="add the §C.1 bottom-up component predictor")
    bt.add_argument("--ft-value", type=float, default=0.0,
                    help="free-transfer opportunity cost (transfer-planning discipline)")
    bt.add_argument("--with-stack", action="store_true",
                    help="add a per-position Ridge stacking meta-learner")
    bt.add_argument("--no-model", action="store_true",
                    help="drop the frozen model:v1 (leakage-free read on its train seasons)")
    bt.add_argument("--free-hit", action="store_true",
                    help="measure + add the Free Hit chip (one-week optimal squad)")
    bt.add_argument("--train-season", help="season to train ensemble weights on")
    bt.set_defaults(fn=cmd_backtest)

    btm = sub.add_parser("backtest-multi",
                         help="backtest across several eval seasons (robustness)")
    btm.add_argument("--seasons", nargs="+",
                     default=["2022-23", "2023-24", "2024-25"],
                     help="eval seasons (each trained on the prior season)")
    btm.add_argument("--from-gw", type=int, default=1)
    btm.add_argument("--to-gw", type=int, default=38)
    btm.add_argument("--version", default="v1")
    btm.add_argument("--focus", default="points_blend",
                     help="approach to track across seasons")
    btm.add_argument("--with-component", action="store_true")
    btm.add_argument("--with-stack", action="store_true")
    btm.add_argument("--no-model", action="store_true",
                     help="drop the frozen model:v1 (leakage-free cross-season read)")
    btm.add_argument("--ft-value", type=float, default=0.0)
    btm.add_argument("--train-season", help="override the per-season prior-season default")
    btm.set_defaults(fn=cmd_backtest_multi)

    an = sub.add_parser("analyze", help="predictor correlation / complementarity report")
    an.add_argument("--season", required=True)
    an.add_argument("--from-gw", type=int, required=True)
    an.add_argument("--to-gw", type=int, required=True)
    an.set_defaults(fn=cmd_analyze)

    od = sub.add_parser("odds", help="odds provider status / build consensus")
    od.add_argument("action", choices=["status", "consensus"])
    od.add_argument("--event")
    od.add_argument("--market", default="1x2")
    od.set_defaults(fn=cmd_odds)

    sub.add_parser("budget-report", help="per-provider consumption").set_defaults(
        fn=cmd_budget_report
    )
    sub.add_parser("schedule", help="start the cron scheduler (blocking)").set_defaults(
        fn=cmd_schedule
    )

    srv = sub.add_parser("serve", help="run the read API (uvicorn)")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
