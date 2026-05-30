"""phase 9: tracked-team state + recommendations

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE normalised.tracked_entries (
            entry_id      bigint PRIMARY KEY,
            player_name   text,
            current_event integer,
            bank          integer,
            team_value    integer,
            total_points  integer,
            overall_rank  bigint,
            updated_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE normalised.tracked_picks (
            entry_id     bigint NOT NULL,
            event        integer NOT NULL,
            element_id   integer NOT NULL,
            slot         integer,
            multiplier   integer,
            is_captain   boolean,
            is_vice      boolean,
            captured_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (entry_id, event, element_id, captured_at)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE normalised.tracked_transfers (
            entry_id        bigint NOT NULL,
            event           integer,
            element_in      integer NOT NULL,
            element_out     integer,
            element_in_cost integer,
            element_out_cost integer,
            transfer_time   timestamptz NOT NULL,
            PRIMARY KEY (entry_id, transfer_time, element_in)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE serving.recommendations (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            model_version text NOT NULL,
            entry_id      bigint,
            season        text NOT NULL,
            target_event  integer,
            kind          text NOT NULL,
            ev            numeric,
            confidence    numeric,
            rationale     jsonb NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_reco_entry ON serving.recommendations "
        "(entry_id, season, target_event, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS serving.recommendations CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.tracked_transfers CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.tracked_picks CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.tracked_entries CASCADE")
