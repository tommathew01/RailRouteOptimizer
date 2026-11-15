"""journey_searches.quotas: selected reservation quotas (GN/TQ)

Revision ID: 3b7d2c9a41e6
Revises: 8cf8f518e4ec
Create Date: 2026-11-15 08:00:00+00:00

Additive and backward compatible: existing rows get ["GN"], the legacy single ``quota`` column is
kept (it holds the first selected quota).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3b7d2c9a41e6"
down_revision: str | None = "8cf8f518e4ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "journey_searches",
        sa.Column(
            "quotas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[\"GN\"]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("journey_searches", "quotas")
