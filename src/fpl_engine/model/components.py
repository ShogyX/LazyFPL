"""Component-wise xP predictor (plan C.1 / 6.2).

Bottom-up expected points: predict each real-match component (goals, assists,
clean sheet, defensive-contribution threshold, saves, conceded, bonus), gate by
the minutes model, and convert with the *current* scoring rules:

    xP = P(appear) * appearance
       + goal_pts   * E(goals)
       + assist_pts * E(assists)
       + CS_pts     * P(CS & 60+)
       + DC_pts     * P(threshold & 60+)
       + saves/conceded/card terms
       + E(bonus)

Expected component rates come from windowed trailing features (FPL-native xG/xA,
conceded, saves, BPS, DC count) scaled by predicted minutes. ``expected_points``
is pure and unit-tested; ``ComponentPredictor.predict_gw`` wires features + the
minutes model and writes ``predictions_player_gw`` with a component breakdown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import predictions_player_gw, training_rows
from ..logging_setup import get_logger
from .minutes import MinutesModel, MinutesPrediction, minutes_from_features
from .predictors import RECENCY_K, BasePredictor, recency_weighted_rate
from .scoring import CURRENT, GK, DEF, ScoringRules, dc_threshold

log = get_logger(__name__)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _first(feats: dict, keys: tuple[str, ...], default: float = 0.0) -> float:
    for k in keys:
        v = feats.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


@dataclass
class ExpectedComponents:
    element_type: int
    p_appear: float
    p60: float
    e_minutes: float
    e_goals: float = 0.0
    e_assists: float = 0.0
    cs_prob: float = 0.0          # P(clean sheet AND played 60+)
    e_conceded: float = 0.0       # expected goals conceded while on pitch
    e_saves: float = 0.0
    dc_prob: float = 0.0          # P(DC threshold AND 60+), eligible positions
    e_bonus: float = 0.0
    e_yellow: float = 0.0


def expected_points(c: ExpectedComponents,
                    rules: ScoringRules = CURRENT) -> tuple[float, dict]:
    """Expected FPL points + per-component breakdown (continuous expectations)."""
    et = c.element_type
    b: dict[str, float] = {}

    # Appearance: 60+ scores the long award, 1-59 the short.
    p_short = max(0.0, c.p_appear - c.p60)
    b["appearance"] = c.p60 * rules.appearance_long + p_short * rules.appearance_short
    b["goals"] = rules.goal.get(et, 0) * c.e_goals
    b["assists"] = rules.assist * c.e_assists
    b["clean_sheet"] = rules.clean_sheet.get(et, 0) * c.cs_prob

    if et == GK:
        b["saves"] = c.e_saves / rules.saves_per_point
    if et in (GK, DEF):
        # -1 per 2 conceded: the EXACT expectation E[-floor(C/2)] for a Poisson(C)
        # on-pitch concession count. The old -lambda/2 over-penalised (since
        # floor(c/2) <= c/2), under-valuing defenders/keepers.
        b["conceded"] = _expected_conceded_penalty(c.e_conceded, rules.conceded_per_minus)

    if rules.dc_enabled and dc_threshold(rules, et) is not None:
        b["dc"] = rules.dc_points * c.dc_prob

    b["bonus"] = c.e_bonus
    b["cards"] = rules.yellow * c.e_yellow

    xp = round(sum(b.values()), 4)
    return xp, {k: round(v, 4) for k, v in b.items()}


def _expected_conceded_penalty(lam: float, per: int, cap: int = 14) -> float:
    """E[-floor(C/per)] for an on-pitch concession count C ~ Poisson(lam).

    Exact (sums the Poisson PMF) rather than the -lam/per linear approximation,
    which overstates the penalty because floor(c/per) <= c/per.
    """
    if lam <= 0.0:
        return 0.0
    p = math.exp(-lam)        # P(C=0)
    total = 0.0
    for c in range(0, cap + 1):
        if c > 0:
            p = p * lam / c   # iterative Poisson PMF
        total += (c // per) * p
    return -total


# Windowed feature keys, tried in order.
_DC = ("defensive_contribution__mean_3", "defensive_contribution__mean_5")
_BONUS = ("bonus__mean_3", "bonus__mean_5")
_YELLOW = ("yellow_cards__mean_5", "yellow_cards__mean_8")

# recency_weighted_rate / RECENCY_K live in predictors.py so both the component
# model and the ensemble's RecencyPredictor share one implementation.


def build_components(element_type: int, feats: dict,
                     mins: MinutesPrediction,
                     rules: ScoringRules = CURRENT) -> ExpectedComponents:
    """Turn windowed trailing features + a minutes prediction into expected rates.

    Opponent strength-of-schedule (when present as ``opp_def`` / ``opp_att``
    features, each a factor around 1.0) scales the attacking and concession
    rates: a leaky opponent (opp_def>1) boosts our goals/assists; a strong
    attacking opponent (opp_att>1) raises our concession rate and lowers CS.
    """
    opp_def = _clamp(_first(feats, ("opp_def",), 1.0), 0.6, 1.6)
    opp_att = _clamp(_first(feats, ("opp_att",), 1.0), 0.6, 1.6)

    # Treat recency-blended xG/xA-per-match as a per-90 rate and project onto
    # predicted minutes (robust: monotonic in minutes, no blow-up at ~0 minutes).
    minutes_share = mins.e_minutes / 90.0
    e_goals = recency_weighted_rate(feats, "expected_goals") * minutes_share * opp_def
    e_assists = recency_weighted_rate(feats, "expected_assists") * minutes_share * opp_def

    # Clean sheet: team concession rate (scaled by opponent attack) -> Poisson
    # P(0), gated by playing 60+.
    lam = max(recency_weighted_rate(feats, "goals_conceded"), 0.0) * opp_att
    cs_prob = math.exp(-lam) * mins.p60
    e_conceded = lam * mins.p_appear

    e_saves = recency_weighted_rate(feats, "saves") * minutes_share

    # DC: logistic on recent DC count vs the position threshold, gated by 60+.
    thr = dc_threshold(rules, element_type)
    if thr is not None:
        dc_recent = _first(feats, _DC, 0.0)
        dc_prob = (1.0 / (1.0 + math.exp(-(dc_recent - thr) / 2.0))) * mins.p60
    else:
        dc_prob = 0.0

    e_bonus = _first(feats, _BONUS, 0.0) * mins.p_appear
    e_yellow = _first(feats, _YELLOW, 0.0) * mins.p_appear

    return ExpectedComponents(
        element_type=element_type, p_appear=mins.p_appear, p60=mins.p60,
        e_minutes=mins.e_minutes, e_goals=e_goals, e_assists=e_assists,
        cs_prob=cs_prob, e_conceded=e_conceded, e_saves=e_saves,
        dc_prob=dc_prob, e_bonus=e_bonus, e_yellow=e_yellow)


@dataclass
class ComponentResult:
    model_version: str
    season: str
    gw: int
    n_players: int


class ComponentPredictor:
    """§C.1 bottom-up predictor; plugs in behind predictions_player_gw."""

    def __init__(self, sm: sessionmaker[Session] | None = None,
                 model_version: str = "c1"):
        self._sm = sm or get_sessionmaker()
        self.model_version = model_version
        self._minutes = MinutesModel(sm=self._sm)

    def predict_gw(self, season: str, gw: int) -> ComponentResult:
        rules = CURRENT
        minutes = self._minutes.predict_gw(season, gw)
        tr = training_rows.c
        with self._sm() as s:
            rows = s.execute(
                select(tr.element_id, tr.player_key, tr.element_type, tr.features).where(
                    tr.season == season, tr.gw == gw, tr.element_type.in_([1, 2, 3, 4]))
            ).all()
            out: list[dict] = []
            for r in rows:
                mins = minutes.get(r.element_id) or MinutesPrediction(0, 0, 0, 0)
                comps = build_components(r.element_type, r.features or {}, mins, rules)
                xp, breakdown = expected_points(comps, rules)
                breakdown.update({"p_start": mins.p_start, "p60": mins.p60,
                                  "e_minutes": mins.e_minutes})
                out.append({
                    "model_version": self.model_version, "season": season, "gw": gw,
                    "player_key": r.player_key, "element_id": r.element_id,
                    "element_type": r.element_type,
                    "xp_next1": xp, "xp_next6": None,
                    "pred_minutes": round(mins.e_minutes, 2),
                    "breakdown": breakdown,
                })
            self._write(s, out)
            s.commit()
        log.info("component xP written", extra={"version": self.model_version,
                                                "season": season, "gw": gw,
                                                "players": len(out)})
        return ComponentResult(self.model_version, season, gw, len(out))

    def _write(self, s: Session, rows: list[dict]) -> None:
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            if not chunk:
                continue
            stmt = insert(predictions_player_gw).values(chunk)
            update = {c: stmt.excluded[c] for c in chunk[0] if c not in
                      ("model_version", "season", "gw", "player_key")}
            s.execute(stmt.on_conflict_do_update(
                index_elements=["model_version", "season", "gw", "player_key"], set_=update))


class ComponentScorePredictor(BasePredictor):
    """Backtestable §C.1 predictor: same component model, but minutes come purely
    from trailing features (no live availability/lineups) so it stays strictly
    causal for head-to-head replay against v1 / the ensemble."""

    def __init__(self, name: str = "component:c1", rules: ScoringRules = CURRENT):
        self.name = name
        self.rules = rules

    def score(self, features: dict, element_type: int) -> float:
        mins = minutes_from_features(features or {})
        comps = build_components(element_type, features or {}, mins, self.rules)
        xp, _ = expected_points(comps, self.rules)
        return xp
