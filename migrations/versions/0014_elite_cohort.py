"""phase 5.2: elite-manager cohort + per-GW picks + effective ownership

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE normalised.elite_managers (
            entry_id      bigint      PRIMARY KEY,
            player_name   text,
            rank          integer,
            total_points  integer,
            source_league bigint,
            captured_at   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE normalised.elite_picks (
            entry_id     bigint      NOT NULL,
            event        integer     NOT NULL,
            element_id   integer     NOT NULL,
            captured_at  timestamptz NOT NULL DEFAULT now(),
            multiplier   integer,
            is_captain   boolean,
            PRIMARY KEY (entry_id, event, element_id, captured_at)
        )
        """
    )
    # Elite-cohort effective ownership per GW (distinct from global EO).
    op.execute(
        """
        CREATE TABLE normalised.elite_ownership (
            event         integer     NOT NULL,
            element_id    integer     NOT NULL,
            captured_at   timestamptz NOT NULL DEFAULT now(),
            n_managers    integer     NOT NULL,
            owned         integer     NOT NULL,
            captained     integer     NOT NULL,
            owned_pct     numeric,
            captaincy_pct numeric,
            eo            numeric,     -- effective ownership: owned + captained (xC weight)
            PRIMARY KEY (event, element_id, captured_at)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS normalised.elite_ownership CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.elite_picks CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.elite_managers CASCADE")
