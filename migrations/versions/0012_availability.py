"""phase 5.4: availability snapshots + lineups / injuries / referees

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Append-only availability history (FPL status/news/chance). A new row is
    # written only when the availability state changes -> flips are detected and
    # timestamped, and the minutes model can read the trailing state at any GW.
    op.execute(
        """
        CREATE TABLE normalised.player_availability (
            element_id   integer     NOT NULL,
            captured_at  timestamptz NOT NULL DEFAULT now(),
            player_key   bigint,
            status       text,
            news         text,
            news_added   timestamptz,
            chance_this  integer,
            chance_next  integer,
            source       text        NOT NULL DEFAULT 'fpl',
            PRIMARY KEY (element_id, captured_at)
        )
        """
    )

    # Predicted/confirmed lineups (API-Football free tier + scraped fallback).
    op.execute(
        """
        CREATE TABLE normalised.lineups (
            source       text        NOT NULL,
            fixture_ref  text        NOT NULL,
            player_ref   text        NOT NULL,
            captured_at  timestamptz NOT NULL DEFAULT now(),
            team_ref     text,
            team_id      integer,
            player_key   bigint,
            role         text,                 -- 'start' | 'bench'
            confirmed    boolean     NOT NULL DEFAULT false,
            formation    text,
            grid         text,
            PRIMARY KEY (source, fixture_ref, player_ref, captured_at)
        )
        """
    )

    # Injury / availability feed (API-Football).
    op.execute(
        """
        CREATE TABLE normalised.injuries (
            source       text        NOT NULL,
            player_ref   text        NOT NULL,
            captured_at  timestamptz NOT NULL DEFAULT now(),
            player_key   bigint,
            team_ref     text,
            team_id      integer,
            fixture_ref  text,
            type         text,
            reason       text,
            PRIMARY KEY (source, player_ref, captured_at)
        )
        """
    )

    # Referee appointments (thin; from API-Football fixtures or scraped).
    op.execute(
        """
        CREATE TABLE normalised.match_officials (
            source       text        NOT NULL,
            fixture_ref  text        NOT NULL,
            captured_at  timestamptz NOT NULL DEFAULT now(),
            fixture_id   integer,
            referee      text,
            PRIMARY KEY (source, fixture_ref, captured_at)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS normalised.match_officials CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.injuries CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.lineups CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.player_availability CASCADE")
