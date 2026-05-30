"""Build optimiser candidates by joining predictions to current FPL prices."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import players, predictions_player_gw
from ..model.minutes import availability_multiplier
from .squad import Candidate
from .transfer import PlayerH


def load_candidates(
    season: str, gw: int, *, model_version: str = "v1",
    sm: sessionmaker[Session] | None = None, only_available: bool = True,
    eo_override: dict[int, float] | None = None,
) -> list[Candidate]:
    """Join serving predictions with normalised player prices/teams.

    Prices/teams come from ``normalised.players`` (current FPL state), matched
    by element id — valid for the current season's predictions. When
    ``eo_override`` is given (e.g. elite-cohort EO), it replaces global
    ``selected_by_percent`` as the ownership signal for the EO overlay.

    Availability gate (``only_available``): each candidate's xP is scaled by an
    availability multiplier from FPL status — injured/suspended/unavailable -> 0
    (dropped here, never selected), doubtful -> 0.5, available -> 1.0 — so we
    never field or transfer in a player known not to play.
    """
    sm = sm or get_sessionmaker()
    p = predictions_player_gw.c
    pl = players.c
    with sm() as s:
        rows = s.execute(
            select(pl.id, p.element_type, pl.now_cost, pl.team_id, p.xp_next1,
                   p.pred_minutes, pl.web_name, pl.status, p.player_key,
                   pl.selected_by_percent)
            .select_from(predictions_player_gw.join(players, p.element_id == pl.id))
            .where(p.model_version == model_version, p.season == season, p.gw == gw)
        ).all()

    out: list[Candidate] = []
    for r in rows:
        if r.now_cost is None or r.xp_next1 is None or r.team_id is None:
            continue
        mult = availability_multiplier(r.status, None) if only_available else 1.0
        if only_available and mult <= 0.0:
            continue  # injured / suspended / unavailable -> never selectable
        mins = float(r.pred_minutes) if r.pred_minutes is not None else 0.0
        eo = eo_override.get(r.id) if eo_override else None
        out.append(Candidate(
            id=r.id, position=r.element_type, price=int(r.now_cost), team_id=r.team_id,
            xp=float(r.xp_next1) * mult, p_play=min(1.0, max(0.0, mins / 90.0)),
            name=r.web_name or str(r.id), player_key=r.player_key,
            ownership=float(eo if eo is not None else (r.selected_by_percent or 0.0)),
        ))
    return out


def load_horizon_candidates(
    season: str, gws: list[int], *, model_version: str = "v1",
    sm: sessionmaker[Session] | None = None, pool_size: int = 60,
    include_ids: set[int] | None = None, only_available: bool = True,
    eo_override: dict[int, float] | None = None,
) -> list[PlayerH]:
    """Build a per-GW xP matrix for the transfer planner over ``gws``.

    Returns the top ``pool_size`` players by total horizon xP, always including
    any ``include_ids`` (e.g. the current squad) that have prices/predictions.
    When ``eo_override`` is given it replaces global ``selected_by_percent`` as
    the ownership signal for the EO overlay (e.g. elite-cohort EO).

    Availability gate (``only_available``): every GW's xP is scaled by the FPL
    status multiplier, so injured/suspended players (->0) are never transferred
    in or started. A held injured player stays in the pool (via ``include_ids``)
    but with ~0 xP, so the planner naturally transfers it out.
    """
    sm = sm or get_sessionmaker()
    include_ids = include_ids or set()
    p = predictions_player_gw.c
    pl = players.c
    with sm() as s:
        rows = s.execute(
            select(pl.id, p.gw, p.element_type, pl.now_cost, pl.team_id, p.xp_next1,
                   p.pred_minutes, pl.web_name, pl.status, p.player_key,
                   pl.selected_by_percent)
            .select_from(predictions_player_gw.join(players, p.element_id == pl.id))
            .where(p.model_version == model_version, p.season == season, p.gw.in_(gws))
        ).all()

    gw_order = {g: k for k, g in enumerate(gws)}
    by_id: dict[int, dict] = {}
    for r in rows:
        if r.now_cost is None or r.team_id is None:
            continue
        d = by_id.setdefault(r.id, {
            "position": r.element_type, "price": int(r.now_cost), "team_id": r.team_id,
            "name": r.web_name or str(r.id), "status": r.status, "player_key": r.player_key,
            "ownership": float(r.selected_by_percent or 0.0),
            "xp": [0.0] * len(gws), "mins": [],
        })
        if r.xp_next1 is not None:
            d["xp"][gw_order[r.gw]] = float(r.xp_next1)
        if r.pred_minutes is not None:
            d["mins"].append(float(r.pred_minutes))

    # Availability gate: scale every GW's xP by the status multiplier so the
    # ranking and the planner both see ~0 for players known not to play.
    for d in by_id.values():
        d["mult"] = availability_multiplier(d["status"], None) if only_available else 1.0
        d["xp"] = [x * d["mult"] for x in d["xp"]]

    ranked = sorted(by_id.items(), key=lambda kv: sum(kv[1]["xp"]), reverse=True)
    keep: dict[int, dict] = {}
    for pid, d in ranked:
        # Drop definitely-out players (mult 0) unless held (so they're sellable).
        admissible = (not only_available) or d["mult"] > 0.0 or pid in include_ids
        if admissible and (len(keep) < pool_size or pid in include_ids):
            keep[pid] = d

    out: list[PlayerH] = []
    for pid, d in keep.items():
        p_play = (sum(d["mins"]) / len(d["mins"]) / 90.0) if d["mins"] else 0.0
        eo = eo_override.get(pid) if eo_override else None
        out.append(PlayerH(
            id=pid, position=d["position"], price=d["price"], team_id=d["team_id"],
            xp=d["xp"], p_play=min(1.0, max(0.0, p_play)), name=d["name"],
            ownership=eo if eo is not None else d["ownership"]))
    return out
