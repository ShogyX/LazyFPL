"""phase 2: DC component columns, dc_match, rule-invariant targets

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DC components are present in vaastav merged_gw from 2025/26 (when FPL
    # introduced the Defensive Contribution stat); NULL for earlier seasons
    # until reconstructed from FBref.
    op.execute(
        """
        ALTER TABLE normalised.player_match_stats
            ADD COLUMN element_type smallint,
            ADD COLUMN tackles integer,
            ADD COLUMN clearances_blocks_interceptions integer,
            ADD COLUMN recoveries integer,
            ADD COLUMN defensive_contribution integer
        """
    )

    op.execute(
        """
        CREATE TABLE normalised.dc_match (
            season              text NOT NULL,
            element_id          integer NOT NULL,
            fixture_id          integer NOT NULL,
            player_key          bigint,
            gw                  integer,
            element_type        smallint,
            cbi                 integer,
            tackles             integer,
            recoveries          integer,
            cbit                integer,
            cbirt               integer,
            dc_value            integer,   -- position-appropriate DC count
            dc_official         integer,   -- FPL defensive_contribution
            threshold           integer,   -- 10 (DEF) / 12 (MID,FWD) / NULL (GK)
            dc_hit              boolean,
            recoveries_imputed  boolean NOT NULL DEFAULT false,
            source              text NOT NULL DEFAULT 'vaastav',
            PRIMARY KEY (season, element_id, fixture_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_dc_match_player ON normalised.dc_match (player_key, season, gw)")

    op.execute(
        """
        CREATE TABLE normalised.targets (
            season            text NOT NULL,
            element_id        integer NOT NULL,
            fixture_id        integer NOT NULL,
            player_key        bigint,
            gw                integer,
            element_type      smallint,
            minutes           integer,
            actual_points     integer,   -- FPL total_points (as recorded)
            as_played_points  integer,   -- converter under that season's rules
            normalised_points numeric,   -- converter under CURRENT rules
            dc_hit            boolean,
            components        jsonb,
            converter_version text NOT NULL,
            built_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (season, element_id, fixture_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_targets_player ON normalised.targets (player_key, season, gw)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS normalised.targets CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.dc_match CASCADE")
    op.execute(
        """
        ALTER TABLE normalised.player_match_stats
            DROP COLUMN IF EXISTS element_type,
            DROP COLUMN IF EXISTS tackles,
            DROP COLUMN IF EXISTS clearances_blocks_interceptions,
            DROP COLUMN IF EXISTS recoveries,
            DROP COLUMN IF EXISTS defensive_contribution
        """
    )
