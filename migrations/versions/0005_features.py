"""phase 3: feature availability matrix + walk-forward training panel

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ragged-history matrix: coverage of each metric over each season.
    op.execute(
        """
        CREATE TABLE feature.feature_availability (
            metric    text NOT NULL,
            source    text NOT NULL,
            season    text NOT NULL,
            n_rows    integer NOT NULL,
            n_present integer NOT NULL,
            coverage  numeric NOT NULL,
            PRIMARY KEY (metric, season)
        )
        """
    )

    # Strictly-causal walk-forward panel: one row per (player, season, GW)
    # prediction point. Features come only from matches before `deadline`;
    # targets from the horizon at/after `deadline`. hist_last_kickoff and
    # tgt_first_kickoff exist so a leakage audit can assert
    # hist_last_kickoff < deadline <= tgt_first_kickoff.
    op.execute(
        """
        CREATE TABLE feature.training_rows (
            season            text NOT NULL,
            player_key        bigint NOT NULL,
            gw                integer NOT NULL,
            element_id        integer,
            element_type      smallint,
            deadline          timestamptz,
            hist_n            integer NOT NULL,
            hist_last_kickoff timestamptz,
            tgt_first_kickoff timestamptz,
            tgt_pts_next1     integer,
            tgt_pts_next6     integer,
            tgt_pts_ros       integer,
            tgt_pts_norm_next1  numeric,
            tgt_pts_norm_next6  numeric,
            tgt_pts_norm_ros    numeric,
            tgt_minutes_next1 integer,
            n_gw_next6        integer,
            n_gw_ros          integer,
            features          jsonb NOT NULL,
            feature_version   text NOT NULL,
            built_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (season, player_key, gw)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_training_rows_pos ON feature.training_rows (element_type, season, gw)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.training_rows CASCADE")
    op.execute("DROP TABLE IF EXISTS feature.feature_availability CASCADE")
