"""initial three-layer schema

Revision ID: 0001
Revises:
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


SCHEMAS = ("raw", "normalised", "feature", "core")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # --- RAW: content-addressed source snapshots ---
    op.execute(
        """
        CREATE TABLE raw.raw_snapshots (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            provider     text NOT NULL,
            endpoint     text NOT NULL,
            params_hash  text NOT NULL,
            params       jsonb NOT NULL DEFAULT '{}'::jsonb,
            content_hash text NOT NULL,
            status_code  integer,
            payload      jsonb,
            season       text,
            fetched_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_raw_snapshots_latest
            ON raw.raw_snapshots (provider, endpoint, params_hash, fetched_at DESC)
        """
    )

    # --- CORE: per-provider windowed budget counters ---
    op.execute(
        """
        CREATE TABLE core.budget_usage (
            provider     text NOT NULL,
            window_kind  text NOT NULL,
            window_start timestamptz NOT NULL,
            count        integer NOT NULL DEFAULT 0,
            PRIMARY KEY (provider, window_kind, window_start)
        )
        """
    )

    # --- CORE: orchestrator run registry ---
    op.execute(
        """
        CREATE TABLE core.run_registry (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            job_name    text NOT NULL,
            status      text NOT NULL,
            started_at  timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            error       text,
            meta        jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_run_registry_job ON core.run_registry (job_name, started_at DESC)"
    )

    # --- NORMALISED: current-state team/player projections ---
    op.execute(
        """
        CREATE TABLE normalised.teams (
            id                     integer PRIMARY KEY,
            code                   integer,
            name                   text NOT NULL,
            short_name             text,
            strength               integer,
            strength_overall_home  integer,
            strength_overall_away  integer,
            strength_attack_home   integer,
            strength_attack_away   integer,
            strength_defence_home  integer,
            strength_defence_away  integer,
            updated_at             timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE normalised.players (
            id                  integer PRIMARY KEY,
            code                integer,
            web_name            text,
            first_name          text,
            second_name         text,
            team_id             integer,
            element_type        smallint,
            now_cost            integer,
            status              varchar(1),
            selected_by_percent numeric,
            total_points        integer,
            minutes             integer,
            form                numeric,
            ep_next             numeric,
            updated_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # --- NORMALISED: per-GW time series, partitioned by season ---
    # Native LIST partitioning works on stock Postgres. When TimescaleDB is
    # installed this table can instead be a hypertable; we detect and prefer
    # native partitioning here so the migration runs on any Postgres.
    op.execute(
        """
        CREATE TABLE normalised.player_gw_snapshots (
            season              text NOT NULL,
            player_id           integer NOT NULL,
            gw                  integer NOT NULL,
            captured_at         timestamptz NOT NULL DEFAULT now(),
            now_cost            integer,
            selected_by_percent numeric,
            total_points        integer,
            event_points        integer,
            minutes             integer,
            form                numeric,
            payload             jsonb,
            PRIMARY KEY (season, player_id, gw, captured_at)
        ) PARTITION BY LIST (season)
        """
    )
    for season, suffix in (("2024-25", "2024_25"), ("2025-26", "2025_26")):
        op.execute(
            f"""
            CREATE TABLE normalised.player_gw_snapshots_{suffix}
                PARTITION OF normalised.player_gw_snapshots
                FOR VALUES IN ('{season}')
            """
        )
    op.execute(
        """
        CREATE TABLE normalised.player_gw_snapshots_default
            PARTITION OF normalised.player_gw_snapshots DEFAULT
        """
    )

    # --- FEATURE layer scaffold ---
    op.execute(
        """
        CREATE TABLE feature.features_player_gw (
            season      text NOT NULL,
            player_id   integer NOT NULL,
            gw          integer NOT NULL,
            feature_set text NOT NULL,
            features    jsonb NOT NULL DEFAULT '{}'::jsonb,
            built_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (season, player_id, gw, feature_set)
        )
        """
    )


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
