"""phase 5.1: authed /my-team selling prices + purchase prices

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Authed /my-team picks: exact selling + purchase prices per owned player
    # (only available via the operator-cookie endpoint). Append-only by capture
    # so a price history is retained; latest snapshot drives the planner budget.
    op.execute(
        """
        CREATE TABLE normalised.authed_picks (
            entry_id       bigint      NOT NULL,
            element_id     integer     NOT NULL,
            captured_at    timestamptz NOT NULL DEFAULT now(),
            selling_price  integer,
            purchase_price integer,
            multiplier     integer,
            is_captain     boolean,
            is_vice        boolean,
            PRIMARY KEY (entry_id, element_id, captured_at)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS normalised.authed_picks CASCADE")
