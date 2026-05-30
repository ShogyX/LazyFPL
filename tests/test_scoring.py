"""Unit tests for the versioned points converter against ruleset B.10."""

from fpl_engine.model.scoring import (
    RULES_2024_25,
    RULES_2025_26,
    Components,
    rules_for_season,
    score,
)

GK, DEF, MID, FWD = 1, 2, 3, 4


def test_mid_goal_assist_bonus():
    c = Components(MID, minutes=90, goals_scored=1, assists=1, bonus=3)
    assert score(c, RULES_2025_26) == 2 + 5 + 3 + 3  # 13


def test_def_clean_sheet_with_and_without_dc():
    c = Components(DEF, minutes=90, clean_sheets=1, bonus=1, dc_hit=True)
    assert score(c, RULES_2025_26) == 2 + 4 + 2 + 1   # 9 (DC counts)
    assert score(c, RULES_2024_25) == 2 + 4 + 1       # 7 (no DC pre-2025/26)


def test_gk_saves_and_clean_sheet():
    c = Components(GK, minutes=90, clean_sheets=1, saves=6)
    assert score(c, RULES_2025_26) == 2 + 4 + 2       # 6//... 6 saves -> +2


def test_gk_penalty_save_and_conceded():
    c = Components(GK, minutes=90, saves=4, goals_conceded=3, penalties_saved=1)
    # appearance 2 + saves 4//3=1 + conceded -(3//2)= -1 + pen save 5 = 7
    assert score(c, RULES_2025_26) == 2 + 1 - 1 + 5


def test_fwd_clean_sheet_worth_zero():
    c = Components(FWD, minutes=90, goals_scored=2, clean_sheets=1)
    assert score(c, RULES_2025_26) == 2 + 8 + 0       # 10


def test_clean_sheet_requires_60_minutes():
    c = Components(DEF, minutes=45, clean_sheets=1)
    assert score(c, RULES_2025_26) == 1               # appearance only, no CS


def test_appearance_tiers():
    assert score(Components(MID, minutes=0), RULES_2025_26) == 0
    assert score(Components(MID, minutes=1), RULES_2025_26) == 1
    assert score(Components(MID, minutes=59), RULES_2025_26) == 1
    assert score(Components(MID, minutes=60), RULES_2025_26) == 2


def test_cards_and_own_goal():
    c = Components(MID, minutes=90, yellow_cards=1, red_cards=0, own_goals=1)
    assert score(c, RULES_2025_26) == 2 - 1 - 2       # -1
    c2 = Components(MID, minutes=90, red_cards=1)
    assert score(c2, RULES_2025_26) == 2 - 3          # -1


def test_gk_ineligible_for_dc():
    c = Components(GK, minutes=90, dc_hit=True)
    # DC must not be awarded to GK even when "hit" is set.
    assert score(c, RULES_2025_26) == 2


def test_rules_for_season_selection():
    assert rules_for_season("2025-26").dc_enabled is True
    assert rules_for_season("2024-25").dc_enabled is False
    assert rules_for_season("2019-20").dc_enabled is False
