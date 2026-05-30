"""Minutes / availability model (plan 6.1).

Serves P(start), P(60+) and E(minutes) — the highest-leverage sub-model, since
every component is gated by minutes. It blends three signals, in priority:

1. **Declared availability** (FPL ``status`` / ``chance_of_playing``) — a hard
   gate: injured/suspended -> 0; a percentage chance scales everything.
2. **Confirmed lineup** (API-Football, near deadline) — overrides the prior:
   named in the XI -> start; on the bench -> start prob collapses to a sub shot.
3. **Trailing role** (recent starts rate + minutes) — the prior when no lineup
   is out yet.

``predict_one`` is pure and unit-tested across the regimes; ``predict_gw`` wires
the DB signals (training_rows features + player_availability + lineups).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import lineups, player_availability, training_rows
from ..logging_setup import get_logger

log = get_logger(__name__)

# Calibrated priors (FPL-typical). Tunable; the structure is what matters.
SUB_ON_RATE = 0.35      # P(a benched, available player comes on)
BENCH_MINUTES = 12.0    # expected minutes if subbed on
DEFAULT_START_MINUTES = 82.0
UNAVAILABLE_STATUS = {"i", "s", "u", "n"}  # injured/suspended/unavailable/not-in-squad

# Trailing-feature keys to try, in order (windowing emits metric__window).
_STARTS_KEYS = ("starts__mean_3", "starts__mean_5", "starts__mean_8")
_MINUTES_KEYS = ("minutes__mean_3", "minutes__mean_5", "minutes__mean_8")
_PLAYED_KEYS = ("played__mean_5", "played__mean_3", "played__mean_8")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _first(feats: dict, keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = feats.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


@dataclass
class MinutesPrediction:
    p_start: float
    p60: float
    e_minutes: float
    p_appear: float = 0.0   # P(>=1 minute), starter or sub


def availability_multiplier(status: str | None, chance: int | None) -> float:
    """Hard availability gate in [0, 1] from FPL status + chance_of_playing."""
    if status in UNAVAILABLE_STATUS:
        return 0.0
    if chance is not None:
        return _clamp(chance / 100.0, 0.0, 1.0)
    if status == "d":          # doubtful, no percentage given
        return 0.5
    return 1.0                 # 'a' / unknown -> available


def predict_one(
    *,
    starts_rate: float | None,
    recent_minutes: float | None,
    status: str | None = None,
    chance: int | None = None,
    lineup_role: str | None = None,
    sub_on_rate: float | None = None,
) -> MinutesPrediction:
    """Predict (p_start, p60, e_minutes) for one player-GW from blended signals.

    ``sub_on_rate`` (P(comes on | not starting)) defaults to a league prior but,
    when derived from a player's trailing played-vs-started rates, sharpens the
    cameo mass for impact subs / rotation players vs nailed starters.
    """
    avail = availability_multiplier(status, chance)
    if avail <= 0.0:
        return MinutesPrediction(0.0, 0.0, 0.0, 0.0)
    sub_rate = SUB_ON_RATE if sub_on_rate is None else _clamp(sub_on_rate, 0.0, 1.0)

    # Base start probability: a confirmed lineup overrides the trailing prior.
    if lineup_role == "start":
        base_start = 1.0
    elif lineup_role == "bench":
        base_start = 0.0
    else:
        base_start = _clamp(starts_rate if starts_rate is not None else 0.7, 0.0, 1.0)

    p_start = avail * base_start

    # Minutes a starter typically plays: infer per-start minutes from the trailing
    # average when we can (recent_minutes is depressed by games not started).
    if recent_minutes is not None and base_start > 0 and starts_rate and starts_rate > 0.05:
        start_minutes = _clamp(recent_minutes / starts_rate, 45.0, 90.0)
    elif recent_minutes is not None and lineup_role == "start":
        start_minutes = _clamp(max(recent_minutes, 60.0), 45.0, 90.0)
    else:
        start_minutes = DEFAULT_START_MINUTES

    p_appear = avail * (base_start + (1.0 - base_start) * sub_rate)
    p_bench = max(0.0, p_appear - p_start)
    e_minutes = p_start * start_minutes + p_bench * BENCH_MINUTES
    p60 = p_start * _clamp((start_minutes - 30.0) / 60.0, 0.0, 1.0)
    return MinutesPrediction(round(p_start, 4), round(p60, 4), round(e_minutes, 2),
                             round(p_appear, 4))


def minutes_from_features(features: dict, *, status: str | None = None,
                          chance: int | None = None,
                          lineup_role: str | None = None) -> MinutesPrediction:
    """Minutes prediction from trailing windowed features (+ optional live gates).

    With no live signals it is purely causal (trailing starts/minutes only) — the
    form used inside the backtester; live availability/lineups refine it in serving.
    """
    starts_rate = _first(features, _STARTS_KEYS)
    played_rate = _first(features, _PLAYED_KEYS)
    # P(plays | doesn't start), from how often the player features without
    # starting: (played - started) / (matches not started).
    sub_on_rate = None
    if played_rate is not None and starts_rate is not None and starts_rate < 1.0:
        sub_on_rate = (played_rate - starts_rate) / (1.0 - starts_rate)
    return predict_one(
        starts_rate=starts_rate,
        recent_minutes=_first(features, _MINUTES_KEYS),
        status=status, chance=chance, lineup_role=lineup_role,
        sub_on_rate=sub_on_rate,
    )


@dataclass
class MinutesGwResult:
    season: str
    gw: int
    n_players: int


class MinutesModel:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def _availability(self, s: Session) -> dict[int, tuple[str | None, int | None]]:
        """element_id -> latest (status, chance_next) from player_availability."""
        rows = s.execute(
            select(player_availability.c.element_id, player_availability.c.status,
                   player_availability.c.chance_next)
            .order_by(player_availability.c.element_id,
                      player_availability.c.captured_at.desc())
            .distinct(player_availability.c.element_id)
        ).all()
        return {r.element_id: (r.status, r.chance_next) for r in rows}

    def _lineup_roles(self, s: Session) -> dict[int, str]:
        """player_key -> latest known lineup role (start/bench)."""
        rows = s.execute(
            select(lineups.c.player_key, lineups.c.role, lineups.c.captured_at)
            .where(lineups.c.player_key.isnot(None))
            .order_by(lineups.c.player_key, lineups.c.captured_at.desc())
            .distinct(lineups.c.player_key)
        ).all()
        return {r.player_key: r.role for r in rows}

    def predict_gw(self, season: str, gw: int) -> dict[int, MinutesPrediction]:
        """Per-element minutes predictions for (season, gw)."""
        tr = training_rows.c
        with self._sm() as s:
            rows = s.execute(
                select(tr.element_id, tr.player_key, tr.features).where(
                    tr.season == season, tr.gw == gw, tr.element_type.in_([1, 2, 3, 4]))
            ).all()
            avail = self._availability(s)
            roles = self._lineup_roles(s)

        out: dict[int, MinutesPrediction] = {}
        for r in rows:
            status, chance = avail.get(r.element_id, (None, None))
            out[r.element_id] = minutes_from_features(
                r.features or {}, status=status, chance=chance,
                lineup_role=roles.get(r.player_key))
        log.info("minutes predicted", extra={"season": season, "gw": gw, "players": len(out)})
        return out
