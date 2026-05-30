"""Versioned FPL scoring converter (plan B.10 / B.12 / A.3 "rule-invariant").

We predict real-match component outcomes, then convert to points via the
*current* scoring function. The function is versioned so a rule change is a
one-file edit; ``as_played`` uses the rules in effect for a given season while
``normalised`` always uses ``CURRENT`` so targets are rule-invariant.

Positions: 1 GK, 2 DEF, 3 MID, 4 FWD.
"""

from __future__ import annotations

from dataclasses import dataclass

GK, DEF, MID, FWD = 1, 2, 3, 4


@dataclass(frozen=True)
class ScoringRules:
    version: str
    goal: dict[int, int]
    clean_sheet: dict[int, int]
    assist: int = 3
    appearance_short: int = 1   # 1-59 minutes
    appearance_long: int = 2    # 60+ minutes
    saves_per_point: int = 3    # GK: +1 per N saves
    conceded_per_minus: int = 2  # GK/DEF: -1 per N conceded
    penalty_save: int = 5
    penalty_miss: int = -2
    own_goal: int = -2
    yellow: int = -1
    red: int = -3
    dc_enabled: bool = True
    dc_points: int = 2
    # +dc_points when defensive count >= threshold[position] (GK ineligible).
    dc_threshold: dict[int, int] | None = None


# 2025/26 — Defensive Contribution active (DEF CBIT>=10; MID/FWD CBIRT>=12).
RULES_2025_26 = ScoringRules(
    version="2025-26",
    goal={GK: 6, DEF: 6, MID: 5, FWD: 4},
    clean_sheet={GK: 4, DEF: 4, MID: 1, FWD: 0},
    dc_enabled=True,
    dc_threshold={DEF: 10, MID: 12, FWD: 12},
)

# 2024/25 and earlier — identical scoring but no Defensive Contribution.
RULES_2024_25 = ScoringRules(
    version="2024-25",
    goal={GK: 6, DEF: 6, MID: 5, FWD: 4},
    clean_sheet={GK: 4, DEF: 4, MID: 1, FWD: 0},
    dc_enabled=False,
)

CURRENT = RULES_2025_26

# DC became a scoring element in 2025/26; everything before used 2024/25 rules.
_SEASON_RULES = {"2025-26": RULES_2025_26}


def rules_for_season(season: str) -> ScoringRules:
    return _SEASON_RULES.get(season, RULES_2024_25)


@dataclass
class Components:
    element_type: int
    minutes: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    saves: int = 0
    penalties_saved: int = 0
    penalties_missed: int = 0
    own_goals: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    bonus: int = 0
    dc_hit: bool = False


def score(c: Components, rules: ScoringRules = CURRENT) -> int:
    """Convert realised components to FPL points under ``rules``.

    ``bonus`` is passed through as provided (the BPS top-3 award is not
    recomputed here; it is predicted by a separate sub-model in serving).
    """
    et = c.element_type
    pts = 0

    if c.minutes >= 60:
        pts += rules.appearance_long
    elif c.minutes > 0:
        pts += rules.appearance_short

    pts += rules.goal.get(et, 0) * c.goals_scored
    pts += rules.assist * c.assists

    # Clean sheet points require 60+ minutes played.
    if c.minutes >= 60:
        pts += rules.clean_sheet.get(et, 0) * c.clean_sheets

    if et == GK:
        pts += c.saves // rules.saves_per_point
        pts += rules.penalty_save * c.penalties_saved

    if et in (GK, DEF):
        pts += -(c.goals_conceded // rules.conceded_per_minus)

    pts += rules.penalty_miss * c.penalties_missed
    pts += rules.own_goal * c.own_goals
    pts += rules.yellow * c.yellow_cards
    pts += rules.red * c.red_cards

    if rules.dc_enabled and et != GK and c.dc_hit:
        pts += rules.dc_points

    pts += c.bonus
    return pts


def dc_threshold(rules: ScoringRules, element_type: int) -> int | None:
    if not rules.dc_enabled or rules.dc_threshold is None or element_type == GK:
        return None
    return rules.dc_threshold.get(element_type)
