"""phase 2 follow-up: explicit dc_known flag on targets

Marks whether Defensive Contribution was observable for a row, so that
normalised_points (current-rules re-scoring) is known-complete vs a lower
bound for seasons lacking DC data.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE normalised.targets "
        "ADD COLUMN dc_known boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE normalised.targets DROP COLUMN IF EXISTS dc_known")
