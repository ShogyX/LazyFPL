"""Advanced stats (Understat/FBref) wired into the windowed feature panel."""

from sqlalchemy import insert, select

from fpl_engine.db.models import (
    feature_availability,
    player_advanced_match_stats,
    training_rows,
)
from fpl_engine.features.availability import AvailabilityBuilder
from fpl_engine.features.families import FeatureMatrixBuilder
from fpl_engine.features.panel import PanelBuilder
from tests.test_panel import _pipeline   # reuse the vaastav->facts->targets pipeline


def _seed_advanced(sm):
    """Understat + FBref rows for Saka (player_key=100) at fixtures 10, 20."""
    with sm() as s:
        s.execute(insert(player_advanced_match_stats), [
            {"source": "understat", "season": "2025-26", "source_match_id": "u10",
             "source_player_id": "501", "player_key": 100, "fixture_id": 10,
             "npxg": 0.4, "key_passes": 2, "shots": 3, "xg_chain": 0.8,
             "xg_buildup": 0.2},
            {"source": "understat", "season": "2025-26", "source_match_id": "u20",
             "source_player_id": "501", "player_key": 100, "fixture_id": 20,
             "npxg": 0.2, "key_passes": 1, "shots": 2, "xg_chain": 0.5,
             "xg_buildup": 0.1},
        ])
        # FBref provides the disjoint creation/progression columns (separate
        # insert so each batch has a uniform column set).
        s.execute(insert(player_advanced_match_stats), [
            {"source": "fbref", "season": "2025-26", "source_match_id": "f10",
             "source_player_id": "saka01", "player_key": 100, "fixture_id": 10,
             "sca": 4, "gca": 1, "prog_passes": 5, "prog_carries": 3},
            {"source": "fbref", "season": "2025-26", "source_match_id": "f20",
             "source_player_id": "saka01", "player_key": 100, "fixture_id": 20,
             "sca": 2, "gca": 0, "prog_passes": 3, "prog_carries": 1},
        ])
        s.commit()


def test_panel_windows_advanced_metrics(sm):
    _pipeline(sm)
    _seed_advanced(sm)
    PanelBuilder(sm=sm).build(seasons=["2025-26"], min_history=1)

    with sm() as s:
        rows = {r.gw: r for r in s.execute(
            select(training_rows).where(training_rows.c.player_key == 100)
            .order_by(training_rows.c.gw)).all()}

    # GW3 prediction point sees history from GW1 + GW2 (strictly prior).
    f = rows[3].features
    # Understat npxg windowed: mean of GW1(0.4) + GW2(0.2) = 0.3.
    assert abs(f["npxg__mean_3"] - 0.3) < 1e-9
    assert f["npxg__career_mean"] is not None
    # FBref SCA coalesced onto the same matches: mean of 4 + 2 = 3.
    assert abs(f["sca__mean_3"] - 3.0) < 1e-9
    assert abs(f["prog_passes__mean_3"] - 4.0) < 1e-9
    # per-90 advanced features computed.
    assert f["npxg90"] is not None and f["sca90"] is not None


def test_panel_advanced_absent_is_none_not_crash(sm):
    # GW2's only prior match (GW1) HAS advanced data, but verify a metric with
    # no data anywhere stays None rather than erroring.
    _pipeline(sm)   # no advanced rows seeded
    PanelBuilder(sm=sm).build(seasons=["2025-26"], min_history=1)
    with sm() as s:
        row = s.execute(select(training_rows).where(
            training_rows.c.player_key == 100, training_rows.c.gw == 3)).one()
    assert row.features["npxg__mean_3"] is None
    assert row.features["sca90"] is None


def test_availability_tags_advanced_span(sm):
    _pipeline(sm)
    _seed_advanced(sm)
    AvailabilityBuilder(sm=sm).build(seasons=["2025-26"])
    with sm() as s:
        rows = {r.metric: r for r in s.execute(
            select(feature_availability).where(
                feature_availability.c.season == "2025-26")).all()}
    assert rows["npxg"].source == "understat"
    assert rows["sca"].source == "fbref"
    # 2 of 3 appearances carry advanced data -> coverage 2/3.
    assert abs(float(rows["npxg"].coverage) - 2 / 3) < 1e-4


def test_per_position_assembly_includes_advanced(sm):
    _pipeline(sm)
    _seed_advanced(sm)
    PanelBuilder(sm=sm).build(seasons=["2025-26"], min_history=1)
    matrix = FeatureMatrixBuilder(sm=sm).assemble("2025-26", position=3)  # MID

    # New progression family + advanced metrics folded into goal_threat/creation.
    assert "progression" in matrix.families
    assert any(k.startswith("npxg__") for k in matrix.families["goal_threat"].feature_keys)
    assert any(k.startswith("sca__") for k in matrix.families["creation"].feature_keys)
    # creation now spans Understat + FBref sources alongside the FPL ones.
    assert {"understat", "fbref"} <= set(matrix.families["creation"].sources)
