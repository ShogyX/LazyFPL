"""phase 1.1: Understat/FBref advanced per-match player stats

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Advanced per-match player stats from Understat + FBref, source-tagged.
    # Keyed on the SOURCE's own identifiers so ingestion is idempotent even
    # before entity/fixture resolution succeeds; player_key + fixture_id are
    # resolved attributes (nullable) joined onto the FPL fact tables downstream.
    op.execute(
        """
        CREATE TABLE normalised.player_advanced_match_stats (
            source            text    NOT NULL,
            season            text    NOT NULL,
            source_match_id   text    NOT NULL,
            source_player_id  text    NOT NULL,
            player_key        bigint,
            fixture_id        integer,
            source_team       text,
            source_opponent   text,
            was_home          boolean,
            match_date        date,
            minutes           integer,
            position          text,
            -- Understat attacking (xG family)
            goals             numeric,
            assists           numeric,
            npg               numeric,
            xg                numeric,
            xa                numeric,
            npxg              numeric,
            key_passes        numeric,
            shots             numeric,
            xg_chain          numeric,
            xg_buildup        numeric,
            -- FBref creation / progression / defensive actions
            sca               numeric,
            gca               numeric,
            prog_passes       numeric,
            prog_carries      numeric,
            prog_passes_rec   numeric,
            passes_completed  numeric,
            passes_attempted  numeric,
            tackles           numeric,
            interceptions     numeric,
            blocks            numeric,
            clearances        numeric,
            touches           numeric,
            take_ons          numeric,
            take_ons_won      numeric,
            aerials_won       numeric,
            aerials_lost      numeric,
            raw               jsonb,
            ingested_at       timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (source, season, source_match_id, source_player_id)
        )
        """
    )
    # Downstream join path: (season, player_key, fixture_id) onto FPL facts.
    op.execute(
        "CREATE INDEX ix_adv_player_fixture ON normalised.player_advanced_match_stats "
        "(season, player_key, fixture_id)"
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS normalised.player_advanced_match_stats CASCADE"
    )
