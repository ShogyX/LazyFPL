"""Read API over the serving layer (plan 10.2).

Exposes predictions, on-demand squad optimisation, stored recommendations,
backtest results and consensus odds so an operator (or a frontend) can view the
engine's output end-to-end. Read-only; queries the NORMALISED/SERVING tables.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, or_, select

from ..db.engine import get_sessionmaker
from ..db.models import (
    backtest_runs,
    player_match_stats,
    players,
    predictions_player_gw,
    recommendations,
    teams,
    tracked_entries,
    tracked_picks,
    true_probabilities,
)
from ..optimise import SquadOptimizer, load_candidates
from . import analytics, live, settings_store

_POS = ("GK", "DEF", "MID", "FWD")


def _pos(et: int | None) -> str | None:
    return _POS[et - 1] if et in (1, 2, 3, 4) else None


def create_app() -> FastAPI:
    app = FastAPI(title="FPL Intelligence Engine API", version="1.0")
    sm = get_sessionmaker()
    squad_cache: dict[tuple, dict] = {}  # memoise the per-request MILP solve

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/predictions")
    def predictions(season: str, gw: int, version: str = "v1",
                    position: int | None = Query(None, ge=1, le=4),
                    limit: int = Query(50, ge=1, le=1000)) -> dict:
        p, pl, t = predictions_player_gw.c, players.c, teams.c
        stmt = (
            select(p.element_id, pl.web_name, p.element_type, p.xp_next1,
                   p.xp_next6, p.pred_minutes, pl.now_cost, pl.status, pl.code, t.short_name)
            .select_from(
                predictions_player_gw.join(players, p.element_id == pl.id)
                .join(teams, pl.team_id == t.id, isouter=True))
            .where(p.model_version == version, p.season == season, p.gw == gw)
            .order_by(p.xp_next1.desc().nulls_last())
        )
        if position:
            stmt = stmt.where(p.element_type == position)
        stmt = stmt.limit(limit)
        with sm() as s:
            rows = s.execute(stmt).all()
        return {"season": season, "gw": gw, "model_version": version,
                "players": [{
                    "element_id": r.element_id, "name": r.web_name,
                    "position": _pos(r.element_type), "team": r.short_name,
                    "code": r.code,
                    "xp_next1": _f(r.xp_next1), "xp_next6": _f(r.xp_next6),
                    "pred_minutes": _f(r.pred_minutes),
                    "price": (r.now_cost or 0) / 10, "status": r.status,
                } for r in rows]}

    @app.get("/squad")
    def squad(season: str, gw: int, version: str = "v1",
              budget: int = Query(1000, ge=300, le=2000),
              eo_weight: float = Query(0.0, ge=-10.0, le=10.0)) -> dict:
        key = (season, gw, version, budget, eo_weight)
        if key in squad_cache:
            return squad_cache[key]
        cands = load_candidates(season, gw, model_version=version)
        if not cands:
            raise HTTPException(404, "no predictions for that season/gw/version")
        sol = SquadOptimizer(budget=budget, eo_weight=eo_weight).solve(cands)
        if not sol.feasible:
            raise HTTPException(422, f"optimiser status: {sol.status}")
        meta = _player_meta(sm, [p.id for p in sol.picks])
        result = {
            "season": season, "gw": gw, "status": sol.status,
            "total_cost": sol.total_cost / 10, "xi_xp": sol.xi_xp,
            "formation": {_POS[k - 1]: v for k, v in sol.formation.items()},
            "picks": [{
                "element_id": p.id, "name": p.name, "position": _pos(p.position),
                "code": meta.get(p.id, (None, None))[0],
                "team": meta.get(p.id, (None, None))[1],
                "price": p.price / 10, "xp": round(p.xp, 2), "start": p.is_start,
                "captain": p.is_captain, "vice": p.is_vice,
            } for p in sorted(sol.picks, key=lambda x: (not x.is_start, x.position))],
        }
        if len(squad_cache) < 256:
            squad_cache[key] = result
        return result

    @app.get("/recommendations")
    def recs(entry: int | None = None, season: str | None = None,
             limit: int = Query(20, ge=1, le=200)) -> dict:
        r = recommendations.c
        stmt = select(r).order_by(desc(r.created_at)).limit(limit)
        if entry is not None:
            stmt = stmt.where(r.entry_id == entry)
        if season:
            stmt = stmt.where(r.season == season)
        with sm() as s:
            rows = s.execute(stmt).mappings().all()
        return {"recommendations": [dict(row) for row in rows]}

    @app.get("/backtests")
    def backtests(season: str | None = None,
                  limit: int = Query(50, ge=1, le=500)) -> dict:
        b = backtest_runs.c
        stmt = select(b.id, b.season, b.strategy, b.start_gw, b.end_gw,
                      b.total_points, b.total_hits, b.net_points, b.created_at)\
            .order_by(desc(b.created_at)).limit(limit)
        if season:
            stmt = stmt.where(b.season == season)
        with sm() as s:
            rows = s.execute(stmt).mappings().all()
        return {"backtests": [dict(row) for row in rows]}

    @app.get("/odds/consensus")
    def odds_consensus(event: str, market: str = "1x2") -> dict:
        t = true_probabilities.c
        with sm() as s:
            latest = s.execute(
                select(func.max(t.captured_at)).where(
                    t.event_ref == event, t.market == market)
            ).scalar_one_or_none()
            if latest is None:
                raise HTTPException(404, "no consensus for that event/market")
            rows = s.execute(
                select(t.selection, t.true_prob, t.n_sources, t.sharp_present)
                .where(t.event_ref == event, t.market == market,
                       t.captured_at == latest)
            ).all()
        if not rows:  # race: rows deleted between the two queries
            raise HTTPException(404, "no consensus for that event/market")
        return {"event": event, "market": market,
                "probabilities": {r.selection: _f(r.true_prob) for r in rows},
                "n_sources": rows[0].n_sources, "sharp_present": rows[0].sharp_present}

    @app.get("/players/{element_id}/history")
    def player_history(element_id: int, season: str,
                       limit: int = Query(60, ge=1, le=60)) -> dict:
        m = player_match_stats.c
        with sm() as s:
            rows = s.execute(
                select(m.gw, m.total_points, m.minutes, m.goals_scored,
                       m.assists, m.bonus, m.value)
                .where(m.season == season, m.element_id == element_id)
                .order_by(m.gw).limit(limit)
            ).all()
        return {"element_id": element_id, "season": season,
                "history": [{
                    "gw": r.gw, "points": r.total_points, "minutes": r.minutes,
                    "goals": r.goals_scored, "assists": r.assists,
                    "bonus": r.bonus, "price": (r.value or 0) / 10,
                } for r in rows]}

    # ---- F1: Settings (general config + masked secrets) -----------------
    @app.get("/settings")
    def get_settings_endpoint() -> dict:
        return {
            "general": settings_store.read_general(),
            "secrets": settings_store.secret_presence(),
            "models": _available_models(),
        }

    @app.put("/settings")
    def put_settings(updates: dict = Body(...)) -> dict:
        return {"general": settings_store.write_general(updates)}

    @app.put("/settings/secrets")
    def put_secrets(updates: dict = Body(...)) -> dict:
        # Values arrive as plaintext, are stored server-side, and only a masked
        # presence map is ever returned — secrets never leave the server.
        return {"secrets": settings_store.write_secrets(updates)}

    @app.get("/models")
    def models() -> dict:
        return _available_models()

    def _available_models() -> dict:
        p = predictions_player_gw.c
        b = backtest_runs.c
        with sm() as s:
            versions = [r[0] for r in s.execute(
                select(p.model_version).distinct().order_by(p.model_version)).all()]
            strategies = [r[0] for r in s.execute(
                select(b.strategy).distinct().order_by(b.strategy)).all()]
        general = settings_store.read_general()
        return {"versions": versions, "strategies": strategies,
                "active_model": general.get("active_model"),
                "active_strategy": general.get("active_strategy")}

    # ---- F4: model comparison from backtests ----------------------------
    @app.get("/models/compare")
    def models_compare(season: str | None = None,
                       strategy: list[str] | None = Query(None),
                       version: str = "v1") -> dict:
        b = backtest_runs.c
        stmt = select(b.id, b.model_version, b.season, b.strategy, b.start_gw,
                      b.end_gw, b.total_points, b.total_hits, b.net_points,
                      b.per_gw, b.created_at).where(b.model_version == version)\
            .order_by(b.season, b.strategy, desc(b.created_at))
        if season:
            stmt = stmt.where(b.season == season)
        if strategy:
            stmt = stmt.where(b.strategy.in_(strategy))
        with sm() as s:
            rows = s.execute(stmt).all()
        # Keep the latest run per (season, strategy) — backtests are re-run.
        seen: set[tuple] = set()
        runs = []
        for r in rows:
            key = (r.season, r.strategy)
            if key in seen:
                continue
            seen.add(key)
            per_gw = [{"gw": g.get("gw"), "points": g.get("points"),
                       "hit": g.get("hit"), "captain": g.get("captain")}
                      for g in (r.per_gw or [])]
            runs.append({
                "id": r.id, "season": r.season, "strategy": r.strategy,
                "start_gw": r.start_gw, "end_gw": r.end_gw,
                "total_points": r.total_points, "total_hits": r.total_hits,
                "net_points": r.net_points, "per_gw": per_gw,
            })
        return {"model_version": version, "runs": runs}

    # ---- F4: player search across the squad with latest per-model xP ----
    @app.get("/players/search")
    def players_search(q: str, season: str | None = None,
                       limit: int = Query(25, ge=1, le=100)) -> dict:
        pl, t, p = players.c, teams.c, predictions_player_gw.c
        like = f"%{q.lower()}%"
        stmt = (
            select(pl.id, pl.web_name, pl.first_name, pl.second_name,
                   pl.element_type, pl.now_cost, pl.status, pl.code, t.short_name)
            .select_from(players.join(teams, pl.team_id == t.id, isouter=True))
            .where(or_(func.lower(pl.web_name).like(like),
                       func.lower(func.concat(pl.first_name, " ", pl.second_name)).like(like)))
            .order_by(pl.total_points.desc().nulls_last())
            .limit(limit)
        )
        with sm() as s:
            rows = s.execute(stmt).all()
            out = []
            for r in rows:
                # Latest xP for this element across stored model versions.
                xp_stmt = (
                    select(p.model_version, p.season, p.gw, p.xp_next1, p.xp_next6)
                    .where(p.element_id == r.id)
                    .order_by(p.season.desc(), p.gw.desc())
                )
                if season:
                    xp_stmt = xp_stmt.where(p.season == season)
                preds: dict[str, dict] = {}
                for x in s.execute(xp_stmt).all():
                    if x.model_version in preds:
                        continue  # first = latest by ordering
                    preds[x.model_version] = {
                        "season": x.season, "gw": x.gw,
                        "xp_next1": _f(x.xp_next1), "xp_next6": _f(x.xp_next6)}
                out.append({
                    "element_id": r.id, "name": r.web_name,
                    "full_name": f"{r.first_name or ''} {r.second_name or ''}".strip(),
                    "team": r.short_name, "position": _pos(r.element_type),
                    "code": r.code, "price": (r.now_cost or 0) / 10, "status": r.status,
                    "predictions": preds,
                })
        return {"query": q, "players": out}

    # ---- F3: tracked entries (daily-tracked teams) ----------------------
    @app.get("/track")
    def track_list(limit: int = Query(50, ge=1, le=200)) -> dict:
        e = tracked_entries.c
        with sm() as s:
            rows = s.execute(
                select(e.entry_id, e.player_name, e.current_event, e.bank,
                       e.team_value, e.total_points, e.overall_rank, e.updated_at)
                .order_by(desc(e.updated_at)).limit(limit)
            ).all()
        return {"entries": [{
            "entry_id": r.entry_id, "name": r.player_name,
            "current_event": r.current_event, "bank": (r.bank or 0) / 10,
            "team_value": (r.team_value or 0) / 10, "total_points": r.total_points,
            "overall_rank": r.overall_rank, "updated_at": _iso(r.updated_at),
        } for r in rows]}

    @app.get("/track/{entry_id}")
    def track_get(entry_id: int) -> dict:
        e, tp = tracked_entries.c, tracked_picks.c
        with sm() as s:
            head = s.execute(
                select(e).where(e.entry_id == entry_id)).mappings().first()
            if head is None:
                raise HTTPException(404, "entry not tracked; POST /track first")
            event = head["current_event"]
            picks = s.execute(
                select(tp.element_id, tp.slot, tp.multiplier, tp.is_captain,
                       tp.is_vice, players.c.web_name, players.c.element_type,
                       players.c.code, teams.c.short_name)
                .select_from(tracked_picks
                    .join(players, tp.element_id == players.c.id, isouter=True)
                    .join(teams, players.c.team_id == teams.c.id, isouter=True))
                .where(tp.entry_id == entry_id, tp.event == event)
                .order_by(tp.slot)
            ).all()
        return {
            "entry_id": entry_id, "name": head["player_name"],
            "current_event": event, "bank": (head["bank"] or 0) / 10,
            "team_value": (head["team_value"] or 0) / 10,
            "total_points": head["total_points"], "overall_rank": head["overall_rank"],
            "picks": [{
                "element_id": p.element_id, "name": p.web_name,
                "position": _pos(p.element_type), "code": p.code, "team": p.short_name,
                "slot": p.slot, "multiplier": p.multiplier, "captain": p.is_captain,
                "vice": p.is_vice,
            } for p in picks],
        }

    @app.post("/track/{entry_id}")
    def track_save(entry_id: int) -> dict:
        # Live ingest: pulls the entry's roster/transfers (and authed prices if a
        # cookie is configured) and persists for daily tracking.
        from ..ingest.entry import EntryIngestor
        from ..ingest.fetch import FetchClient
        fetch = FetchClient()
        try:
            ing = EntryIngestor(fetch)
            res = ing.ingest_entry(entry_id)
            my = ing.ingest_my_team(entry_id)
        except Exception as exc:  # network / auth failure -> surface cleanly
            raise HTTPException(502, f"entry ingest failed: {exc}") from exc
        finally:
            fetch.close()
        return {
            "entry_id": res.entry_id, "name": res.name,
            "current_event": res.current_event,
            "team_value": (res.team_value or 0) / 10,
            "roster_size": len(res.roster), "new_transfers": res.new_transfers,
            "authed": my.authenticated, "needs_reauth": getattr(my, "needs_reauth", False),
        }

    # ---- F3: entry-aware planner (suggestions + transfers + captain) ----
    @app.get("/planner")
    def planner(entry: int, season: str, gw: int, version: str = "v1",
                horizon: int = Query(6, ge=1, le=10),
                ft: int = Query(1, ge=0, le=5),
                eo_weight: float = Query(0.0, ge=-10.0, le=10.0)) -> dict:
        from ..ingest.entry import EntryIngestor
        from ..ingest.fetch import FetchClient
        from ..model.recommend import RecommendationEngine
        fetch = FetchClient()
        try:
            ing = EntryIngestor(fetch)
            roster = set(ing.latest_roster(entry))
            if not roster:
                raise HTTPException(404, "no tracked roster; POST /track/{entry} first")
            bank, purchase = ing.resolve_budget(entry)
        finally:
            fetch.close()
        eo_override = None
        if eo_weight:
            from ..ingest.elite import latest_elite_eo
            eo_override = latest_elite_eo(gw) or None
        try:
            rec = RecommendationEngine(model_version=version).generate(
                season, gw, roster, horizon=horizon, initial_ft=ft,
                entry_id=entry, bank=bank, purchase=purchase,
                eo_override=eo_override, eo_weight=eo_weight)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "entry_id": entry, "season": season, "gw": gw,
            "kind": rec.kind, "ev_uplift": _f(rec.ev),
            "confidence": _f(rec.confidence),
            "bank": (bank or 0) / 10 if bank is not None else None,
            "rationale": rec.rationale,
        }

    # ---- F4+: predicted-vs-actual analytics --------------------------------
    @app.get("/accuracy")
    def accuracy(season: str, version: str = "v1") -> dict:
        # Per-GW rank IC / RMSE / MAE, per-position IC and a calibration curve,
        # all from stored predictions joined to realised points.
        return analytics.prediction_accuracy(season, version)

    @app.get("/optimal-xi")
    def optimal_xi(season: str, version: str = "v1",
                   budget: int = Query(1000, ge=300, le=2000)) -> dict:
        return analytics.optimal_xi_history(season, version, budget)

    @app.get("/hedge-weights")
    def hedge_weights_endpoint(eval_season: str, train_season: str | None = None,
                               lo: int = Query(1, ge=1, le=38),
                               hi: int = Query(38, ge=1, le=38)) -> dict:
        # Heavy on first call (replays a season of frames); memoised thereafter.
        return analytics.hedge_weights(eval_season, train_season, lo, hi)

    # ---- live FPL feed (topbar + ticker) --------------------------------
    @app.get("/live/deadline")
    def live_deadline() -> dict:
        return live.deadline()

    @app.get("/live/ticker")
    def live_ticker(limit: int = Query(24, ge=1, le=60)) -> dict:
        return live.ticker(limit)

    # ---- engine-informed chip suggestions -------------------------------
    @app.get("/chips")
    def chips(season: str, gw: int, horizon: int = Query(8, ge=1, le=20)) -> dict:
        return live.chips(season, gw, horizon)

    return app


def _frontend_dist() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_served_app() -> FastAPI:
    """Production single-origin app: the read API mounted under ``/api`` plus the
    built React SPA served at the root (with client-side routing fallback).

    One uvicorn process on 0.0.0.0 then serves the whole app — no separate web
    server, no CORS. Falls back to the bare API if the frontend isn't built.
    The frontend calls ``/api/*`` (see ``frontend/src/lib/api.ts``), so the API
    and SPA never collide on shared paths like ``/settings`` or ``/planner``.
    """
    api = create_app()
    dist = _frontend_dist()
    if not (dist / "index.html").is_file():
        return api

    served = FastAPI(title="FPL Intelligence Engine", version="1.0")
    served.mount("/api", api)

    @served.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        target = (dist / full_path).resolve()
        if full_path and dist in target.parents and target.is_file():
            return FileResponse(target)
        return FileResponse(dist / "index.html")

    return served


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _iso(v) -> str | None:
    return v.isoformat() if v is not None else None


def _player_meta(sm, ids: list[int]) -> dict[int, tuple[int | None, str | None]]:
    """{element_id: (photo_code, team_short)} for rendering player images."""
    if not ids:
        return {}
    pl, t = players.c, teams.c
    with sm() as s:
        rows = s.execute(
            select(pl.id, pl.code, t.short_name)
            .select_from(players.join(teams, pl.team_id == t.id, isouter=True))
            .where(pl.id.in_(set(ids)))
        ).all()
    return {int(r.id): (r.code, r.short_name) for r in rows}


# `app` is the bare read API (routes at root) — used in dev behind the Vite proxy
# and by the test suite. `served_app` adds the SPA at root with the API under
# /api for a single-origin production deploy.
app = create_app()
served_app = create_served_app()
