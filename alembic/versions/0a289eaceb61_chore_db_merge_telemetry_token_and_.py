"""chore(db): merge telemetry token and session drop migrations

Revision ID: 0a289eaceb61
Revises: 3a1617257197, 9f8c4d7a1b2e
Create Date: 2026-03-20 10:05:47.604133
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0a289eaceb61"
down_revision: str | None = ("3a1617257197", "9f8c4d7a1b2e")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
