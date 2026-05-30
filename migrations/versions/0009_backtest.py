"""phase 10: backtest runs

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE serving.backtest_runs (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            model_version text NOT NULL,
            season        text NOT NULL,
            strategy      text NOT NULL,
            start_gw      integer NOT NULL,
            end_gw        integer NOT NULL,
            total_points  integer,
            total_hits    integer,
            net_points    integer,
            per_gw        jsonb,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_backtest ON serving.backtest_runs "
        "(season, strategy, model_version, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS serving.backtest_runs CASCADE")
