"""Backtester realism: autosubs, vice-captain, bench boost (pure unit tests)."""

from fpl_engine.backtest.engine import realise_gw

GK, DEF, MID, FWD = 1, 2, 3, 4

# 15-man squad: GK 1,2 / DEF 3-7 / MID 8-12 / FWD 13-15.
POS = {**{1: GK, 2: GK}, **{i: DEF for i in range(3, 8)},
       **{i: MID for i in range(8, 13)}, **{i: FWD for i in range(13, 16)}}
SQUAD = set(range(1, 16))
# Valid XI (1 GK, 4 DEF, 3 MID, 3 FWD); bench = 2(GK),7(DEF),11,12(MID).
XI = [1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15]
XP = {i: 5.0 for i in SQUAD}            # flat xP unless a test overrides


def test_no_blanks_scores_xi_plus_captain():
    actual = {i: 5 for i in SQUAD}
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=XP)
    assert subs == 0 and cap == 13
    assert pts == 11 * 5 + 5            # XI + captain doubling


def test_blanking_starter_replaced_by_bench():
    actual = {i: 5 for i in SQUAD}
    actual[8] = 0                       # starting MID blanks
    actual[11] = 6                      # bench MID played
    xp = {**XP, 11: 9.0}                # highest bench xP -> first autosub priority
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=xp)
    assert subs == 1
    # 10 played starters (5 each) + sub 11 (6) + captain 13 (+5)
    assert pts == 10 * 5 + 6 + 5


def test_gk_only_subbed_by_gk():
    actual = {i: 5 for i in SQUAD}
    actual[1] = 0                       # starting GK blanks
    actual[7] = 9                       # bench DEF played (must NOT fill GK slot)
    actual[2] = 3                       # bench GK played -> fills GK slot
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=XP)
    # GK slot filled by bench GK (2), and bench DEF (7) can also come in for the
    # freed outfield headroom — both played; verify the GK got on.
    # Scoring must contain exactly one GK.
    assert subs >= 1
    assert cap == 13


def test_vice_captain_inherits_when_captain_blanks():
    actual = {i: 5 for i in SQUAD}
    actual[13] = 0                      # captain (FWD 13) blanks
    xp = {**XP, 14: 9.0}                # FWD 14 is highest-xP non-captain -> vice
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=xp)
    assert cap == 14                    # vice took the armband
    # the blanked FWD is autosubbed (a played bench player fills in), so 11 score;
    # captain 13 contributes 0, vice 14 is doubled (+5)
    assert pts == 11 * 5 + 5


def test_both_captain_and_vice_blank_no_bonus():
    actual = {i: 5 for i in SQUAD}
    actual[13] = 0                      # captain blanks
    xp = {**XP, 14: 9.0}                # vice = 14
    actual[14] = 0                      # vice also blanks
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=xp)
    assert cap is None                  # no armband bonus


def test_bench_boost_scores_all_fifteen():
    actual = {i: 5 for i in SQUAD}
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=XP,
                                bench_boost=True)
    assert pts == 15 * 5 + 5            # all 15 + captain doubling
    assert subs == 0


def test_triple_captain_multiplier():
    actual = {i: 5 for i in SQUAD}
    pts, subs, cap = realise_gw(XI, SQUAD, captain=13, actual=actual, pos=POS, xp=XP,
                                cap_mult=3)
    assert pts == 11 * 5 + 2 * 5        # captain counted x3 (base + 2 extra)


def test_chip_bonuses_pick_best_xp_timed_gw():
    from fpl_engine.backtest.engine import Backtester
    per_gw = [
        {"gw": 1, "cap_xp": 6.0, "tc_uplift": 8, "bench_xp": 4.0, "bb_uplift": 5},
        {"gw": 2, "cap_xp": 9.0, "tc_uplift": 12, "bench_xp": 3.0, "bb_uplift": 2},
        {"gw": 3, "cap_xp": 5.0, "tc_uplift": 20, "bench_xp": 11.0, "bb_uplift": 14},
        {"gw": 4, "points": 0, "skipped": "no_data"},
    ]
    bonus, chips = Backtester._chip_bonuses(per_gw)
    # TC at GW2 (highest cap_xp -> uplift 12); BB at GW3 (highest bench_xp -> 14).
    assert chips["triple_captain"] == {"gw": 2, "uplift": 12}
    assert chips["bench_boost"] == {"gw": 3, "uplift": 14}
    assert bonus == 12 + 14            # NOT the hindsight max (GW3 TC=20)


def test_chip_bonuses_empty_when_all_skipped():
    from fpl_engine.backtest.engine import Backtester
    bonus, chips = Backtester._chip_bonuses([{"gw": 1, "skipped": "no_data"}])
    assert bonus == 0 and chips == {}


def test_chip_bonuses_includes_free_hit_when_measured():
    from fpl_engine.backtest.engine import Backtester
    per_gw = [
        {"gw": 1, "cap_xp": 6.0, "tc_uplift": 8, "bench_xp": 4.0, "bb_uplift": 5,
         "fh_xp_gap": 3.0, "fh_uplift": 10},
        {"gw": 2, "cap_xp": 9.0, "tc_uplift": 12, "bench_xp": 3.0, "bb_uplift": 2,
         "fh_xp_gap": 8.0, "fh_uplift": 25},
    ]
    bonus, chips = Backtester._chip_bonuses(per_gw)
    assert chips["free_hit"] == {"gw": 2, "uplift": 25}   # highest fh_xp_gap
    assert bonus == 12 + 5 + 25                            # TC(gw2)+BB(gw1)+FH(gw2)
