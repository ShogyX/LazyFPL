"""historical lake: identity crosswalk + per-match facts + team elo

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_NEW_TABLES = (
    "normalised.team_elo",
    "normalised.team_match_stats",
    "normalised.player_match_stats",
    "normalised.id_overrides",
    "normalised.id_crosswalk",
    "normalised.player_identity",
)


def upgrade() -> None:
    # Canonical player identity, keyed by the stable FPL player code.
    op.execute(
        """
        CREATE TABLE normalised.player_identity (
            player_key  bigint PRIMARY KEY,
            web_name    text,
            first_name  text,
            second_name text,
            last_season text,
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # Per-source, per-season id -> canonical player_key.
    op.execute(
        """
        CREATE TABLE normalised.id_crosswalk (
            source       text NOT NULL,
            season       text NOT NULL,
            source_id    text NOT NULL,
            player_key   bigint NOT NULL REFERENCES normalised.player_identity(player_key),
            source_name  text,
            source_team  text,
            match_method text NOT NULL,
            confidence   numeric NOT NULL DEFAULT 1.0,
            PRIMARY KEY (source, season, source_id)
        )
        """
    )

    # Manual overrides take precedence over fuzzy matches.
    op.execute(
        """
        CREATE TABLE normalised.id_overrides (
            source     text NOT NULL,
            season     text NOT NULL,
            source_id  text NOT NULL,
            player_key bigint NOT NULL,
            note       text,
            PRIMARY KEY (source, season, source_id)
        )
        """
    )

    # Per-player per-match facts (vaastav merged_gw), keyed by canonical id.
    op.execute(
        """
        CREATE TABLE normalised.player_match_stats (
            season           text NOT NULL,
            element_id       integer NOT NULL,
            player_key       bigint,
            gw               integer NOT NULL,
            fixture_id       integer NOT NULL,
            team_id          integer,
            opponent_team_id integer,
            was_home         boolean,
            minutes          integer,
            starts           integer,
            goals_scored     integer,
            assists          integer,
            clean_sheets     integer,
            goals_conceded   integer,
            own_goals        integer,
            penalties_saved  integer,
            penalties_missed integer,
            saves            integer,
            yellow_cards     integer,
            red_cards        integer,
            bonus            integer,
            bps              integer,
            influence        numeric,
            creativity       numeric,
            threat           numeric,
            ict_index        numeric,
            expected_goals               numeric,
            expected_assists             numeric,
            expected_goal_involvements   numeric,
            expected_goals_conceded      numeric,
            total_points     integer,
            value            integer,
            selected         integer,
            transfers_balance integer,
            kickoff_time     timestamptz,
            raw              jsonb,
            PRIMARY KEY (season, element_id, fixture_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_pms_player_key ON normalised.player_match_stats (player_key, season, gw)"
    )

    # Per-team per-match facts (from fixtures): one row per team per fixture.
    op.execute(
        """
        CREATE TABLE normalised.team_match_stats (
            season           text NOT NULL,
            fixture_id       integer NOT NULL,
            team_id          integer NOT NULL,
            opponent_team_id integer,
            gw               integer,
            was_home         boolean,
            goals_for        integer,
            goals_against    integer,
            result           varchar(1),
            points           integer,
            difficulty       integer,
            kickoff_time     timestamptz,
            PRIMARY KEY (season, fixture_id, team_id)
        )
        """
    )

    # ClubElo daily team Elo (free CSV API), mapped to FPL team where possible.
    op.execute(
        """
        CREATE TABLE normalised.team_elo (
            club          text NOT NULL,
            snapshot_date date NOT NULL,
            elo           numeric,
            country       text,
            level         integer,
            fpl_team_id   integer,
            PRIMARY KEY (club, snapshot_date)
        )
        """
    )


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
