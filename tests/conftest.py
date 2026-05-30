"""Test fixtures. Targets the fpl_test database; migrates once, cleans per test."""

from __future__ import annotations

import os

# Point the app at the test DB before any fpl_engine import reads settings.
os.environ.setdefault(
    "FPL_DATABASE_URL", "postgresql+psycopg2://fpl:fpl@localhost:5432/fpl_test"
)
os.environ.setdefault("FPL_LOG_JSON", "true")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from fpl_engine.db.engine import get_engine, get_sessionmaker  # noqa: E402

_TABLES = (
    "raw.raw_snapshots",
    "core.app_settings",
    "core.budget_usage",
    "core.run_registry",
    "normalised.players",
    "normalised.teams",
    "normalised.player_gw_snapshots",
    "normalised.id_crosswalk",
    "normalised.id_overrides",
    "normalised.player_identity",
    "normalised.player_match_stats",
    "normalised.player_advanced_match_stats",
    "normalised.player_availability",
    "normalised.lineups",
    "normalised.injuries",
    "normalised.match_officials",
    "normalised.team_match_stats",
    "normalised.team_elo",
    "normalised.odds_snapshots",
    "normalised.true_probabilities",
    "normalised.dc_match",
    "normalised.targets",
    "feature.features_player_gw",
    "feature.training_rows",
    "feature.feature_availability",
    "study.feature_importance",
    "study.model_calibration",
    "study.model_registry",
    "serving.predictions_player_gw",
    "serving.recommendations",
    "serving.backtest_runs",
    "normalised.tracked_picks",
    "normalised.tracked_transfers",
    "normalised.tracked_entries",
    "normalised.authed_picks",
    "normalised.elite_managers",
    "normalised.elite_picks",
    "normalised.elite_ownership",
)


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_db():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def sm():
    return get_sessionmaker()
