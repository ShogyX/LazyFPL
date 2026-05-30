"""phase 5.3: multi-source odds snapshots + consensus true probabilities

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalised odds quotes from every provider (one row per selection quote).
    op.execute(
        """
        CREATE TABLE normalised.odds_snapshots (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            provider     text NOT NULL,
            event_ref    text NOT NULL,
            market       text NOT NULL,
            selection    text NOT NULL,
            line         numeric,
            decimal_odds numeric,
            back_price   numeric,
            lay_price    numeric,
            no_vig_prob  numeric,
            sharp        boolean NOT NULL DEFAULT false,
            captured_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_odds_event ON normalised.odds_snapshots "
        "(event_ref, market, captured_at DESC)"
    )

    # Consensus true probability per (event, market, selection) snapshot.
    op.execute(
        """
        CREATE TABLE normalised.true_probabilities (
            event_ref     text NOT NULL,
            market        text NOT NULL,
            selection     text NOT NULL,
            captured_at   timestamptz NOT NULL,
            true_prob     numeric NOT NULL,
            n_sources     integer NOT NULL,
            sharp_present boolean NOT NULL,
            method        text NOT NULL,
            PRIMARY KEY (event_ref, market, selection, captured_at)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS normalised.true_probabilities CASCADE")
    op.execute("DROP TABLE IF EXISTS normalised.odds_snapshots CASCADE")
