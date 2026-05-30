"""phase 10.2 (F1): operator-editable app settings + secrets for the UI

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Key-value config the Settings page reads/writes at runtime. Secrets
    # (is_secret = true) are stored here for the single-operator deployment but
    # are NEVER returned in plaintext by the API — only a masked presence flag.
    op.execute(
        """
        CREATE TABLE core.app_settings (
            key         text        PRIMARY KEY,
            value       jsonb       NOT NULL,
            is_secret   boolean     NOT NULL DEFAULT false,
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.app_settings CASCADE")
