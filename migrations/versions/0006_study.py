"""phase 4: predictive-validity study artefacts

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS study')

    # Per (position, target, horizon, feature): screen + weight diagnostics.
    op.execute(
        """
        CREATE TABLE study.feature_importance (
            study_version  text NOT NULL,
            position       smallint NOT NULL,
            target         text NOT NULL,
            horizon        text NOT NULL,
            feature        text NOT NULL,
            family         text,
            metric         text,
            window_label   text,
            half_life      text,
            mean_ic        numeric,
            sd_ic          numeric,
            sign_stability numeric,
            n_seasons      integer,
            fdr_q          numeric,
            en_weight      numeric,
            gbm_importance numeric,
            selected       boolean NOT NULL DEFAULT false,
            PRIMARY KEY (study_version, position, target, horizon, feature)
        )
        """
    )

    # Per (position, target, horizon): out-of-sample skill vs baselines.
    op.execute(
        """
        CREATE TABLE study.model_calibration (
            study_version text NOT NULL,
            position      smallint NOT NULL,
            target        text NOT NULL,
            horizon       text NOT NULL,
            n_rows        integer,
            n_seasons     integer,
            oos_spearman  numeric,
            oos_rmse      numeric,
            base_recent_spearman numeric,
            base_season_spearman numeric,
            base_recent_rmse     numeric,
            base_season_rmse     numeric,
            beats_baseline boolean,
            shrink_lambda numeric,
            extra         jsonb,
            PRIMARY KEY (study_version, position, target, horizon)
        )
        """
    )

    # Versioned, rollback-capable weight registry.
    op.execute(
        """
        CREATE TABLE study.model_registry (
            version         text PRIMARY KEY,
            status          text NOT NULL,       -- frozen | active | archived
            created_at      timestamptz NOT NULL DEFAULT now(),
            spec            jsonb NOT NULL,
            holdout_metrics jsonb,
            notes           text
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS study CASCADE")
