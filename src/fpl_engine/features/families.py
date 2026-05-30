"""Per-position feature assembly (plan 3.3 / B.13).

Each position's feature families map to base metrics; the windowed feature keys
for those metrics (built by the panel) are selected into a per-position matrix.
Every family is span-tagged with the sources of its metrics so the study can
honour the ragged-history rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import training_rows
from .availability import ADVANCED_METRIC_SOURCES, METRIC_SOURCES

GK, DEF, MID, FWD = 1, 2, 3, 4

# position -> family -> base metrics (B.13). Advanced metrics (Understat npxG /
# xGChain / key passes / shots; FBref SCA/GCA / progression) are folded into the
# attacking families; they carry their own (shorter, ragged) span tags.
POSITION_FAMILIES: dict[int, dict[str, tuple[str, ...]]] = {
    GK: {
        "availability": ("minutes", "starts", "played"),
        "team_defence": ("clean_sheets", "goals_conceded"),
        "shot_stopping": ("saves",),
        "bonus_drivers": ("bonus", "bps", "influence"),
    },
    DEF: {
        "availability": ("minutes", "starts", "played"),
        "cs_drivers": ("clean_sheets", "goals_conceded"),
        "dc_cbit": ("tackles", "clearances_blocks_interceptions", "defensive_contribution"),
        "attacking_threat": ("goals_scored", "assists", "expected_goals",
                             "expected_assists", "threat", "npxg", "key_passes"),
        "bonus_drivers": ("bonus", "bps", "influence"),
    },
    MID: {
        "availability": ("minutes", "starts", "played"),
        "goal_threat": ("goals_scored", "expected_goals", "threat", "npxg", "shots"),
        "creation": ("assists", "expected_assists", "creativity", "ict_index",
                     "key_passes", "xg_chain", "xg_buildup", "sca", "gca"),
        "dc_cbirt": ("tackles", "clearances_blocks_interceptions", "recoveries",
                     "defensive_contribution"),
        "progression": ("prog_passes", "prog_carries"),
        "team_attack": ("expected_goal_involvements", "total_points"),
        "bonus_drivers": ("bonus", "bps", "influence"),
    },
    FWD: {
        "availability": ("minutes", "starts", "played"),
        "finishing": ("goals_scored", "expected_goals", "threat", "npxg", "shots"),
        "creation": ("assists", "expected_assists", "creativity", "key_passes",
                     "xg_buildup"),
        "progression": ("prog_passes", "prog_carries"),
        "team_fixture": ("expected_goal_involvements", "total_points"),
        "dc_minor": ("defensive_contribution",),
        "bonus_drivers": ("bonus", "bps", "influence"),
    },
}

# Per-90 features (panel-built) attached to their owning family.
_PER90_FAMILY = {
    DEF: {"attacking_threat": ("goals90", "assists90", "xg90", "xa90", "xgi90",
                               "npxg90", "key_passes90")},
    MID: {"goal_threat": ("goals90", "xg90", "npxg90"),
          "creation": ("assists90", "xa90", "key_passes90", "sca90", "gca90"),
          "team_attack": ("xgi90",)},
    FWD: {"finishing": ("goals90", "xg90", "npxg90"),
          "creation": ("assists90", "xa90", "key_passes90"),
          "team_fixture": ("xgi90",)},
    GK: {},
}


@dataclass
class FamilySpec:
    name: str
    metrics: tuple[str, ...]
    sources: tuple[str, ...]      # span tags (distinct metric sources)
    feature_keys: tuple[str, ...]  # actual keys present in a sample row


# Panel-derived metrics absent from the availability matrix but still sourced
# from FPL basic data (so the span tag should not read "derived").
_EXTRA_SOURCES = {"total_points": "fpl_basic", "starts": "fpl_basic", "played": "fpl_basic"}


def _metric_source(metric: str) -> str:
    return (METRIC_SOURCES.get(metric) or ADVANCED_METRIC_SOURCES.get(metric)
            or _EXTRA_SOURCES.get(metric, "derived"))


def family_sources(metrics: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_metric_source(m) for m in metrics}))


def position_feature_keys(position: int, sample_features: dict) -> dict[str, FamilySpec]:
    """Resolve each family to the windowed feature keys present in a sample row."""
    specs: dict[str, FamilySpec] = {}
    families = POSITION_FAMILIES[position]
    per90 = _PER90_FAMILY.get(position, {})
    for family, metrics in families.items():
        keys = [k for k in sample_features
                if any(k.startswith(f"{m}__") for m in metrics)]
        keys += [p for p in per90.get(family, ()) if p in sample_features]
        specs[family] = FamilySpec(
            name=family, metrics=metrics, sources=family_sources(metrics),
            feature_keys=tuple(sorted(keys)),
        )
    return specs


@dataclass
class PositionMatrix:
    position: int
    season: str
    families: dict[str, FamilySpec]
    rows: list[dict]


class FeatureMatrixBuilder:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def assemble(self, season: str, position: int, *, limit: int | None = None) -> PositionMatrix:
        tr = training_rows.c
        with self._sm() as s:
            stmt = (
                select(tr.player_key, tr.gw, tr.element_type, tr.features,
                       tr.tgt_pts_next1, tr.tgt_pts_norm_next1, tr.tgt_minutes_next1)
                .where(tr.season == season, tr.element_type == position)
                .order_by(tr.gw, tr.player_key)
            )
            if limit:
                stmt = stmt.limit(limit)
            raw = [dict(r) for r in s.execute(stmt).mappings().all()]

        if not raw:
            return PositionMatrix(position, season, {}, [])

        specs = position_feature_keys(position, raw[0]["features"])
        keep = sorted({k for spec in specs.values() for k in spec.feature_keys})
        rows: list[dict] = []
        for r in raw:
            feats = r["features"]
            rows.append({
                "player_key": r["player_key"], "gw": r["gw"],
                "y_next1": r["tgt_pts_next1"], "y_norm_next1": r["tgt_pts_norm_next1"],
                "y_minutes_next1": r["tgt_minutes_next1"],
                **{k: feats.get(k) for k in keep},
            })
        return PositionMatrix(position, season, specs, rows)
