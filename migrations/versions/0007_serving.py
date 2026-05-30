"""phase 6: serving layer (predictions)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS serving")
    op.execute(
        """
        CREATE TABLE serving.predictions_player_gw (
            model_version text NOT NULL,
            season        text NOT NULL,
            gw            integer NOT NULL,
            player_key    bigint NOT NULL,
            element_id    integer,
            element_type  smallint,
            xp_next1      numeric,
            xp_next6      numeric,
            pred_minutes  numeric,
            breakdown     jsonb,
            created_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (model_version, season, gw, player_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_pred_pos ON serving.predictions_player_gw "
        "(model_version, season, gw, element_type)"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS serving CASCADE")
