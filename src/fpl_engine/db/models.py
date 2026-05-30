"""Core table definitions for the three-layer schema.

Layers (per FPL_MASTER_PLAN_v2.md A.3):
  * ``raw``        — verbatim, timestamped source snapshots (immutable history)
  * ``normalised`` — typed relational facts
  * ``feature``    — derived model inputs
  * ``core``       — operational/registry tables (budget, run registry)

The Alembic migration is the DDL source of truth; these ``Table`` objects
mirror it for typed query access. Tests assert the two stay consistent.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

SCHEMAS = ("raw", "normalised", "feature", "core", "study", "serving")

metadata = MetaData()

# --- RAW layer: immutable, content-addressed source snapshots ---
raw_snapshots = Table(
    "raw_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("endpoint", Text, nullable=False),
    Column("params_hash", Text, nullable=False),
    Column("params", JSONB, nullable=False, server_default="{}"),
    Column("content_hash", Text, nullable=False),
    Column("status_code", Integer),
    Column("payload", JSONB),
    Column("season", Text),
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="raw",
)

# --- CORE: operator-editable app settings + secrets (UI Settings page) ---
app_settings = Table(
    "app_settings",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSONB, nullable=False),
    Column("is_secret", Boolean, nullable=False, server_default="false"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="core",
)

# --- CORE: per-provider budget consumption (windowed counters) ---
budget_usage = Table(
    "budget_usage",
    metadata,
    Column("provider", Text, primary_key=True),
    Column("window_kind", Text, primary_key=True),  # minute|hour|day|month
    Column("window_start", DateTime(timezone=True), primary_key=True),
    Column("count", Integer, nullable=False, server_default="0"),
    schema="core",
)

# --- CORE: run registry for the orchestrator ---
run_registry = Table(
    "run_registry",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("job_name", Text, nullable=False),
    Column("status", Text, nullable=False),  # running|success|failed
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("error", Text),
    Column("meta", JSONB, nullable=False, server_default="{}"),
    schema="core",
)

# --- NORMALISED: current-state projections from FPL bootstrap ---
teams = Table(
    "teams",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Integer),
    Column("name", Text, nullable=False),
    Column("short_name", Text),
    Column("strength", Integer),
    Column("strength_overall_home", Integer),
    Column("strength_overall_away", Integer),
    Column("strength_attack_home", Integer),
    Column("strength_attack_away", Integer),
    Column("strength_defence_home", Integer),
    Column("strength_defence_away", Integer),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

players = Table(
    "players",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Integer),
    Column("web_name", Text),
    Column("first_name", Text),
    Column("second_name", Text),
    Column("team_id", Integer),
    Column("element_type", SmallInteger),  # 1 GK 2 DEF 3 MID 4 FWD
    Column("now_cost", Integer),
    Column("status", String(1)),
    Column("selected_by_percent", Numeric),
    Column("total_points", Integer),
    Column("minutes", Integer),
    Column("form", Numeric),
    Column("ep_next", Numeric),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

# --- NORMALISED: per-GW point-in-time time series, partitioned by season ---
# Native LIST partitioning by season (TimescaleDB hypertables are used instead
# when the extension is present; see migration 0001).
player_gw_snapshots = Table(
    "player_gw_snapshots",
    metadata,
    Column("season", Text, primary_key=True),
    Column("player_id", Integer, primary_key=True),
    Column("gw", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True, server_default=func.now()),
    Column("now_cost", Integer),
    Column("selected_by_percent", Numeric),
    Column("total_points", Integer),
    Column("event_points", Integer),
    Column("minutes", Integer),
    Column("form", Numeric),
    Column("payload", JSONB),
    schema="normalised",
    postgresql_partition_by="LIST (season)",
)

# --- NORMALISED: canonical identity + cross-source crosswalk ---
player_identity = Table(
    "player_identity",
    metadata,
    Column("player_key", BigInteger, primary_key=True),  # stable FPL code
    Column("web_name", Text),
    Column("first_name", Text),
    Column("second_name", Text),
    Column("last_season", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

id_crosswalk = Table(
    "id_crosswalk",
    metadata,
    Column("source", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("player_key", BigInteger, nullable=False),
    Column("source_name", Text),
    Column("source_team", Text),
    Column("match_method", Text, nullable=False),
    Column("confidence", Numeric, nullable=False, server_default="1.0"),
    schema="normalised",
)

id_overrides = Table(
    "id_overrides",
    metadata,
    Column("source", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("player_key", BigInteger, nullable=False),
    Column("note", Text),
    schema="normalised",
)

# --- NORMALISED: per-match fact tables ---
player_match_stats = Table(
    "player_match_stats",
    metadata,
    Column("season", Text, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("fixture_id", Integer, primary_key=True),
    Column("player_key", BigInteger),
    Column("gw", Integer, nullable=False),
    Column("team_id", Integer),
    Column("opponent_team_id", Integer),
    Column("was_home", Boolean),
    Column("minutes", Integer),
    Column("starts", Integer),
    Column("goals_scored", Integer),
    Column("assists", Integer),
    Column("clean_sheets", Integer),
    Column("goals_conceded", Integer),
    Column("own_goals", Integer),
    Column("penalties_saved", Integer),
    Column("penalties_missed", Integer),
    Column("saves", Integer),
    Column("yellow_cards", Integer),
    Column("red_cards", Integer),
    Column("bonus", Integer),
    Column("bps", Integer),
    Column("influence", Numeric),
    Column("creativity", Numeric),
    Column("threat", Numeric),
    Column("ict_index", Numeric),
    Column("expected_goals", Numeric),
    Column("expected_assists", Numeric),
    Column("expected_goal_involvements", Numeric),
    Column("expected_goals_conceded", Numeric),
    Column("total_points", Integer),
    Column("value", Integer),
    Column("selected", Integer),
    Column("transfers_balance", Integer),
    Column("kickoff_time", DateTime(timezone=True)),
    Column("element_type", SmallInteger),
    Column("tackles", Integer),
    Column("clearances_blocks_interceptions", Integer),
    Column("recoveries", Integer),
    Column("defensive_contribution", Integer),
    Column("raw", JSONB),
    schema="normalised",
)

dc_match = Table(
    "dc_match",
    metadata,
    Column("season", Text, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("fixture_id", Integer, primary_key=True),
    Column("player_key", BigInteger),
    Column("gw", Integer),
    Column("element_type", SmallInteger),
    Column("cbi", Integer),
    Column("tackles", Integer),
    Column("recoveries", Integer),
    Column("cbit", Integer),
    Column("cbirt", Integer),
    Column("dc_value", Integer),
    Column("dc_official", Integer),
    Column("threshold", Integer),
    Column("dc_hit", Boolean),
    Column("recoveries_imputed", Boolean, nullable=False, server_default="false"),
    Column("source", Text, nullable=False, server_default="vaastav"),
    schema="normalised",
)

player_advanced_match_stats = Table(
    "player_advanced_match_stats",
    metadata,
    Column("source", Text, primary_key=True),          # 'understat' | 'fbref'
    Column("season", Text, primary_key=True),
    Column("source_match_id", Text, primary_key=True),
    Column("source_player_id", Text, primary_key=True),
    Column("player_key", BigInteger),                  # resolved (nullable)
    Column("fixture_id", Integer),                     # resolved FPL fixture (nullable)
    Column("source_team", Text),
    Column("source_opponent", Text),
    Column("was_home", Boolean),
    Column("match_date", Date),
    Column("minutes", Integer),
    Column("position", Text),
    # Understat attacking (xG family)
    Column("goals", Numeric),
    Column("assists", Numeric),
    Column("npg", Numeric),
    Column("xg", Numeric),
    Column("xa", Numeric),
    Column("npxg", Numeric),
    Column("key_passes", Numeric),
    Column("shots", Numeric),
    Column("xg_chain", Numeric),
    Column("xg_buildup", Numeric),
    # FBref creation / progression / defensive actions
    Column("sca", Numeric),
    Column("gca", Numeric),
    Column("prog_passes", Numeric),
    Column("prog_carries", Numeric),
    Column("prog_passes_rec", Numeric),
    Column("passes_completed", Numeric),
    Column("passes_attempted", Numeric),
    Column("tackles", Numeric),
    Column("interceptions", Numeric),
    Column("blocks", Numeric),
    Column("clearances", Numeric),
    Column("touches", Numeric),
    Column("take_ons", Numeric),
    Column("take_ons_won", Numeric),
    Column("aerials_won", Numeric),
    Column("aerials_lost", Numeric),
    Column("raw", JSONB),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

targets = Table(
    "targets",
    metadata,
    Column("season", Text, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("fixture_id", Integer, primary_key=True),
    Column("player_key", BigInteger),
    Column("gw", Integer),
    Column("element_type", SmallInteger),
    Column("minutes", Integer),
    Column("actual_points", Integer),
    Column("as_played_points", Integer),
    Column("normalised_points", Numeric),
    Column("dc_hit", Boolean),
    Column("dc_known", Boolean, nullable=False, server_default="false"),
    Column("components", JSONB),
    Column("converter_version", Text, nullable=False),
    Column("built_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

team_match_stats = Table(
    "team_match_stats",
    metadata,
    Column("season", Text, primary_key=True),
    Column("fixture_id", Integer, primary_key=True),
    Column("team_id", Integer, primary_key=True),
    Column("opponent_team_id", Integer),
    Column("gw", Integer),
    Column("was_home", Boolean),
    Column("goals_for", Integer),
    Column("goals_against", Integer),
    Column("result", String(1)),
    Column("points", Integer),
    Column("difficulty", Integer),
    Column("kickoff_time", DateTime(timezone=True)),
    schema="normalised",
)

# --- NORMALISED: elite-manager cohort + effective ownership (plan 5.2) ---
elite_managers = Table(
    "elite_managers",
    metadata,
    Column("entry_id", BigInteger, primary_key=True),
    Column("player_name", Text),
    Column("rank", Integer),
    Column("total_points", Integer),
    Column("source_league", BigInteger),
    Column("captured_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

elite_picks = Table(
    "elite_picks",
    metadata,
    Column("entry_id", BigInteger, primary_key=True),
    Column("event", Integer, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("multiplier", Integer),
    Column("is_captain", Boolean),
    schema="normalised",
)

elite_ownership = Table(
    "elite_ownership",
    metadata,
    Column("event", Integer, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("n_managers", Integer, nullable=False),
    Column("owned", Integer, nullable=False),
    Column("captained", Integer, nullable=False),
    Column("owned_pct", Numeric),
    Column("captaincy_pct", Numeric),
    Column("eo", Numeric),
    schema="normalised",
)


# --- NORMALISED: authed /my-team selling + purchase prices (plan 5.1) ---
authed_picks = Table(
    "authed_picks",
    metadata,
    Column("entry_id", BigInteger, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("selling_price", Integer),
    Column("purchase_price", Integer),
    Column("multiplier", Integer),
    Column("is_captain", Boolean),
    Column("is_vice", Boolean),
    schema="normalised",
)


# --- NORMALISED: availability / lineups / injuries / referees (plan 5.4) ---
player_availability = Table(
    "player_availability",
    metadata,
    Column("element_id", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("player_key", BigInteger),
    Column("status", Text),
    Column("news", Text),
    Column("news_added", DateTime(timezone=True)),
    Column("chance_this", Integer),
    Column("chance_next", Integer),
    Column("source", Text, nullable=False, server_default="fpl"),
    schema="normalised",
)

lineups = Table(
    "lineups",
    metadata,
    Column("source", Text, primary_key=True),
    Column("fixture_ref", Text, primary_key=True),
    Column("player_ref", Text, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("team_ref", Text),
    Column("team_id", Integer),
    Column("player_key", BigInteger),
    Column("role", Text),                 # 'start' | 'bench'
    Column("confirmed", Boolean, nullable=False, server_default="false"),
    Column("formation", Text),
    Column("grid", Text),
    schema="normalised",
)

injuries = Table(
    "injuries",
    metadata,
    Column("source", Text, primary_key=True),
    Column("player_ref", Text, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("player_key", BigInteger),
    Column("team_ref", Text),
    Column("team_id", Integer),
    Column("fixture_ref", Text),
    Column("type", Text),
    Column("reason", Text),
    schema="normalised",
)

match_officials = Table(
    "match_officials",
    metadata,
    Column("source", Text, primary_key=True),
    Column("fixture_ref", Text, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True,
           server_default=func.now()),
    Column("fixture_id", Integer),
    Column("referee", Text),
    schema="normalised",
)

odds_snapshots = Table(
    "odds_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("provider", Text, nullable=False),
    Column("event_ref", Text, nullable=False),
    Column("market", Text, nullable=False),
    Column("selection", Text, nullable=False),
    Column("line", Numeric),
    Column("decimal_odds", Numeric),
    Column("back_price", Numeric),
    Column("lay_price", Numeric),
    Column("no_vig_prob", Numeric),
    Column("sharp", Boolean, nullable=False, server_default="false"),
    Column("captured_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

true_probabilities = Table(
    "true_probabilities",
    metadata,
    Column("event_ref", Text, primary_key=True),
    Column("market", Text, primary_key=True),
    Column("selection", Text, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True),
    Column("true_prob", Numeric, nullable=False),
    Column("n_sources", Integer, nullable=False),
    Column("sharp_present", Boolean, nullable=False),
    Column("method", Text, nullable=False),
    schema="normalised",
)

team_elo = Table(
    "team_elo",
    metadata,
    Column("club", Text, primary_key=True),
    Column("snapshot_date", Date, primary_key=True),
    Column("elo", Numeric),
    Column("country", Text),
    Column("level", Integer),
    Column("fpl_team_id", Integer),
    schema="normalised",
)

# --- FEATURE layer: ragged-history availability matrix ---
feature_availability = Table(
    "feature_availability",
    metadata,
    Column("metric", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("n_rows", Integer, nullable=False),
    Column("n_present", Integer, nullable=False),
    Column("coverage", Numeric, nullable=False),
    schema="feature",
)

# --- FEATURE layer: strictly-causal walk-forward training panel ---
training_rows = Table(
    "training_rows",
    metadata,
    Column("season", Text, primary_key=True),
    Column("player_key", BigInteger, primary_key=True),
    Column("gw", Integer, primary_key=True),
    Column("element_id", Integer),
    Column("element_type", SmallInteger),
    Column("deadline", DateTime(timezone=True)),
    Column("hist_n", Integer, nullable=False),
    Column("hist_last_kickoff", DateTime(timezone=True)),
    Column("tgt_first_kickoff", DateTime(timezone=True)),
    Column("tgt_pts_next1", Integer),
    Column("tgt_pts_next6", Integer),
    Column("tgt_pts_ros", Integer),
    Column("tgt_pts_norm_next1", Numeric),
    Column("tgt_pts_norm_next6", Numeric),
    Column("tgt_pts_norm_ros", Numeric),
    Column("tgt_minutes_next1", Integer),
    Column("n_gw_next6", Integer),
    Column("n_gw_ros", Integer),
    Column("features", JSONB, nullable=False),
    Column("feature_version", Text, nullable=False),
    Column("built_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="feature",
)

# --- STUDY layer: predictive-validity artefacts + versioned weights ---
feature_importance = Table(
    "feature_importance",
    metadata,
    Column("study_version", Text, primary_key=True),
    Column("position", SmallInteger, primary_key=True),
    Column("target", Text, primary_key=True),
    Column("horizon", Text, primary_key=True),
    Column("feature", Text, primary_key=True),
    Column("family", Text),
    Column("metric", Text),
    Column("window_label", Text),
    Column("half_life", Text),
    Column("mean_ic", Numeric),
    Column("sd_ic", Numeric),
    Column("sign_stability", Numeric),
    Column("n_seasons", Integer),
    Column("fdr_q", Numeric),
    Column("en_weight", Numeric),
    Column("gbm_importance", Numeric),
    Column("selected", Boolean, nullable=False, server_default="false"),
    schema="study",
)

model_calibration = Table(
    "model_calibration",
    metadata,
    Column("study_version", Text, primary_key=True),
    Column("position", SmallInteger, primary_key=True),
    Column("target", Text, primary_key=True),
    Column("horizon", Text, primary_key=True),
    Column("n_rows", Integer),
    Column("n_seasons", Integer),
    Column("oos_spearman", Numeric),
    Column("oos_rmse", Numeric),
    Column("base_recent_spearman", Numeric),
    Column("base_season_spearman", Numeric),
    Column("base_recent_rmse", Numeric),
    Column("base_season_rmse", Numeric),
    Column("beats_baseline", Boolean),
    Column("shrink_lambda", Numeric),
    Column("extra", JSONB),
    schema="study",
)

model_registry = Table(
    "model_registry",
    metadata,
    Column("version", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("spec", JSONB, nullable=False),
    Column("holdout_metrics", JSONB),
    Column("notes", Text),
    schema="study",
)

# --- NORMALISED: tracked-team state (operator's / followed entries) ---
tracked_entries = Table(
    "tracked_entries",
    metadata,
    Column("entry_id", BigInteger, primary_key=True),
    Column("player_name", Text),
    Column("current_event", Integer),
    Column("bank", Integer),
    Column("team_value", Integer),
    Column("total_points", Integer),
    Column("overall_rank", BigInteger),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="normalised",
)

tracked_picks = Table(
    "tracked_picks",
    metadata,
    Column("entry_id", BigInteger, primary_key=True),
    Column("event", Integer, primary_key=True),
    Column("element_id", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), primary_key=True, server_default=func.now()),
    Column("slot", Integer),
    Column("multiplier", Integer),
    Column("is_captain", Boolean),
    Column("is_vice", Boolean),
    schema="normalised",
)

tracked_transfers = Table(
    "tracked_transfers",
    metadata,
    Column("entry_id", BigInteger, primary_key=True),
    Column("transfer_time", DateTime(timezone=True), primary_key=True),
    Column("element_in", Integer, primary_key=True),
    Column("event", Integer),
    Column("element_out", Integer),
    Column("element_in_cost", Integer),
    Column("element_out_cost", Integer),
    schema="normalised",
)

recommendations = Table(
    "recommendations",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("model_version", Text, nullable=False),
    Column("entry_id", BigInteger),
    Column("season", Text, nullable=False),
    Column("target_event", Integer),
    Column("kind", Text, nullable=False),
    Column("ev", Numeric),
    Column("confidence", Numeric),
    Column("rationale", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="serving",
)

backtest_runs = Table(
    "backtest_runs",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("model_version", Text, nullable=False),
    Column("season", Text, nullable=False),
    Column("strategy", Text, nullable=False),
    Column("start_gw", Integer, nullable=False),
    Column("end_gw", Integer, nullable=False),
    Column("total_points", Integer),
    Column("total_hits", Integer),
    Column("net_points", Integer),
    Column("per_gw", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="serving",
)

# --- SERVING layer: per-player per-GW expected points ---
predictions_player_gw = Table(
    "predictions_player_gw",
    metadata,
    Column("model_version", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("gw", Integer, primary_key=True),
    Column("player_key", BigInteger, primary_key=True),
    Column("element_id", Integer),
    Column("element_type", SmallInteger),
    Column("xp_next1", Numeric),
    Column("xp_next6", Numeric),
    Column("pred_minutes", Numeric),
    Column("breakdown", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="serving",
)

# --- FEATURE layer: derived per-player per-GW model inputs (scaffold) ---
features_player_gw = Table(
    "features_player_gw",
    metadata,
    Column("season", Text, primary_key=True),
    Column("player_id", Integer, primary_key=True),
    Column("gw", Integer, primary_key=True),
    Column("feature_set", Text, primary_key=True),
    Column("features", JSONB, nullable=False, server_default="{}"),
    Column("built_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="feature",
)
