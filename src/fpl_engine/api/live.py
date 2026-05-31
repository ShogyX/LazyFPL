"""Live FPL feed + chip suggestions for the dashboard topbar/ticker and the
Team Planner chip card.

The ticker and deadline read the official FPL API (bootstrap + fixtures) through
the shared fetch client with short in-memory caching so polling stays polite.
Chip suggestions are engine-informed: Triple Captain from stored predictions,
Bench Boost / Free Hit from double/blank gameweek detection in the fixtures.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import func, select

from ..db.engine import get_sessionmaker
from ..db.models import predictions_player_gw, team_match_stats
from ..ingest.fetch import FetchClient


@lru_cache(maxsize=1)
def _fetch() -> FetchClient:
    return FetchClient()


def _bootstrap() -> dict:
    res = _fetch().get("fpl", "/bootstrap-static/", cache_ttl=60)
    return res.payload if isinstance(res.payload, dict) else {}


def _fixtures(event: int | None = None) -> list[dict]:
    path = f"/fixtures/?event={event}" if event else "/fixtures/"
    res = _fetch().get("fpl", path, cache_ttl=45)
    return res.payload if isinstance(res.payload, list) else []


def deadline() -> dict:
    """Next gameweek number + deadline (the GW to plan for)."""
    boot = _bootstrap()
    events = boot.get("events", []) if isinstance(boot, dict) else []
    upcoming = [e for e in events if not e.get("finished") and e.get("deadline_time")]
    ev = min(upcoming, key=lambda e: e["deadline_time"]) if upcoming else (events[-1] if events else None)
    if not ev:
        return {"gw": None, "deadline_time": None}
    return {"gw": ev.get("id"), "deadline_time": ev.get("deadline_time")}


def ticker(limit: int = 24) -> dict:
    """Compact live items: in-play/finished scores, price moves and team news."""
    boot = _bootstrap()
    teams = {t["id"]: t.get("short_name") or t.get("name") for t in boot.get("teams", [])}
    elements = boot.get("elements", [])
    by_id = {e["id"]: e for e in elements}
    items: list[dict] = []

    # current/next event for scores
    events = boot.get("events", [])
    cur = next((e["id"] for e in events if e.get("is_current")), None) \
        or next((e["id"] for e in events if not e.get("finished")), None)
    for f in (_fixtures(cur) if cur else []):
        if not f.get("started"):
            continue
        items.append({
            "kind": "ft" if f.get("finished") else "live",
            "a": teams.get(f.get("team_h")), "b": teams.get(f.get("team_a")),
            "as_": f.get("team_h_score"), "bs": f.get("team_a_score"),
            "min": "FT" if f.get("finished") else (f"{f.get('minutes')}'" if f.get("minutes") else "live"),
        })

    # price moves this event
    moved = sorted((e for e in elements if int(e.get("cost_change_event") or 0) != 0),
                   key=lambda e: abs(int(e.get("cost_change_event"))), reverse=True)[:8]
    for e in moved:
        up = int(e.get("cost_change_event")) > 0
        items.append({"kind": "price", "dir": "up" if up else "down",
                      "name": e.get("web_name"), "val": f"£{(e.get('now_cost') or 0) / 10:.1f}",
                      "delta": f"{'+' if up else ''}{int(e.get('cost_change_event')) / 10:.1f}"})

    # injury / availability news
    for e in elements:
        if e.get("status") and e["status"] != "a" and e.get("news"):
            items.append({"kind": "news", "name": e.get("web_name"), "note": e.get("news")})
            if len([i for i in items if i["kind"] == "news"]) >= 8:
                break

    _ = by_id  # reserved for richer score detail later
    return {"items": items[:limit]}


def _gw_fixture_shape(season: str) -> dict[int, tuple[int, int, int]]:
    """{gw: (n_fixtures, n_teams, n_doubled)} for upcoming (unplayed) GWs."""
    t = team_match_stats.c
    with get_sessionmaker()() as s:
        rows = s.execute(
            select(t.gw, t.team_id).where(t.season == season, t.result.is_(None), t.gw.isnot(None))
        ).all()
    by_gw: dict[int, list[int]] = {}
    for gw, team in rows:
        by_gw.setdefault(int(gw), []).append(int(team))
    out: dict[int, tuple[int, int, int]] = {}
    for gw, teamlist in by_gw.items():
        n_fix = len(teamlist) // 2
        uniq = set(teamlist)
        doubled = sum(1 for tm in uniq if teamlist.count(tm) >= 2)
        out[gw] = (n_fix, len(uniq), doubled)
    return out


def chips(season: str, gw: int, horizon: int = 8) -> dict:
    """Engine-informed chip suggestions over the next ``horizon`` GWs."""
    p = predictions_player_gw.c
    with get_sessionmaker()() as s:
        rows = s.execute(
            select(p.gw, func.max(p.xp_next1))
            .where(p.season == season, p.gw >= gw, p.gw < gw + horizon, p.xp_next1.isnot(None))
            .group_by(p.gw).order_by(p.gw)
        ).all()
    top_by_gw = {int(g): float(x) for g, x in rows}

    out: list[dict] = []
    # Triple Captain: GW with the highest single-player xP (extra = that xP).
    if top_by_gw:
        best_gw = max(top_by_gw, key=top_by_gw.get)
        out.append({"key": "tripcap", "name": "Triple Captain", "best_gw": best_gw,
                    "ev": round(top_by_gw[best_gw], 1),
                    "note": f"Captain ceiling peaks in GW{best_gw} (+{top_by_gw[best_gw]:.1f} xP from the extra multiplier)."})
    else:
        out.append({"key": "tripcap", "name": "Triple Captain", "best_gw": None, "ev": None,
                    "note": "Needs current-GW predictions — run a refresh."})

    shape = _gw_fixture_shape(season)
    horizon_gws = {g: v for g, v in shape.items() if gw <= g < gw + horizon}
    # Bench Boost: a double gameweek (teams with two fixtures) is the classic spot.
    dgws = sorted((g for g, (_, _, d) in horizon_gws.items() if d > 0), key=lambda g: -horizon_gws[g][2])
    if dgws:
        g = dgws[0]; d = horizon_gws[g][2]
        out.append({"key": "bboost", "name": "Bench Boost", "best_gw": g, "ev": None,
                    "note": f"GW{g} is a double gameweek ({d} teams play twice) — most bench points."})
    else:
        out.append({"key": "bboost", "name": "Bench Boost", "best_gw": None, "ev": None,
                    "note": "No double gameweek detected in the horizon."})
    # Free Hit: a blank gameweek (fewest teams playing) is the classic spot.
    full = max((v[1] for v in horizon_gws.values()), default=0)
    blanks = sorted((g for g, v in horizon_gws.items() if v[1] < full), key=lambda g: horizon_gws[g][1])
    if blanks:
        g = blanks[0]
        out.append({"key": "freehit", "name": "Free Hit", "best_gw": g, "ev": None,
                    "note": f"GW{g} is a blank ({horizon_gws[g][1]} teams play) — Free Hit a full XI."})
    else:
        out.append({"key": "freehit", "name": "Free Hit", "best_gw": None, "ev": None,
                    "note": "No blank gameweek detected in the horizon."})
    # Wildcard: heuristic — the GW before the hardest fixture stretch (left as guidance).
    out.append({"key": "wildcard", "name": "Wildcard", "best_gw": dgws[0] - 1 if dgws else None, "ev": None,
                "note": "Best paired with a schedule swing — reset before a double or a hard run."})
    return {"season": season, "gw": gw, "chips": out}
