"""Elite-EO overlay threaded through RecommendationEngine (no DB candidates)."""

from fpl_engine.model.recommend import RecommendationEngine
from fpl_engine.optimise.transfer import PlayerH

GK, DEF, MID, FWD = 1, 2, 3, 4


def _pool() -> list[PlayerH]:
    """Exactly 15 players (2/5/5/3). One FWD is an elite differential (highest
    xP, zero ownership); the others are owned template players."""
    pool: list[PlayerH] = []
    cid = 0

    def add(pos, xp, own):
        nonlocal cid
        cid += 1
        pool.append(PlayerH(cid, pos, 50, (cid % 6) + 1, [xp], p_play=1.0,
                            name=f"p{cid}", ownership=own))

    for _ in range(2):
        add(GK, 3.0, 50.0)
    for _ in range(5):
        add(DEF, 4.0, 50.0)
    for _ in range(5):
        add(MID, 5.0, 50.0)
    # forwards: a high-xP differential + two owned templates
    add(FWD, 10.0, 0.0)     # differential -> highest xP overall
    add(FWD, 4.0, 100.0)
    add(FWD, 4.0, 100.0)
    return pool


def _captain(rec):
    return rec.rationale["captain"]["name"]


def test_pure_xp_captains_the_differential(sm):
    pool = _pool()
    roster = {p.id for p in pool}
    rec = RecommendationEngine(sm=sm, model_version="vt").generate(
        "2025-26", 24, roster, horizon=1, candidates=pool, eo_weight=0.0)
    # The differential (xP 10) is the clear captain when ownership is ignored.
    diff = next(p for p in pool if p.position == FWD and p.ownership == 0.0)
    assert _captain(rec) == diff.name


def test_strong_eo_weight_benches_differential_and_shifts_captain(sm):
    pool = _pool()
    roster = {p.id for p in pool}
    rec = RecommendationEngine(sm=sm, model_version="vt").generate(
        "2025-26", 24, roster, horizon=1, candidates=pool, eo_weight=2.0)
    diff = next(p for p in pool if p.position == FWD and p.ownership == 0.0)
    # Template-protection overlay benches the zero-ownership differential, so the
    # captain is no longer it -> proves eo_weight reached the planner.
    assert _captain(rec) != diff.name


def test_eo_override_replaces_ownership_signal(sm):
    # Pass candidates with a stale ownership; eo_override is only applied in the
    # DB loader path (covered by test_elite); here we assert generate accepts and
    # threads both knobs without error and surfaces a valid recommendation.
    pool = _pool()
    roster = {p.id for p in pool}
    rec = RecommendationEngine(sm=sm, model_version="vt").generate(
        "2025-26", 24, roster, horizon=1, candidates=pool,
        eo_override={1: 99.0}, eo_weight=1.0)
    assert rec.rationale["captain"]["name"]
    assert rec.kind in ("transfer", "captain")
