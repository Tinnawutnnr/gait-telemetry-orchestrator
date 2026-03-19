"""merge alembic heads

Revision ID: 56b0ba9071c4
Revises: 094cedeef31b, fd5c388e2451
Create Date: 2026-03-19 17:59:19.027981
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56b0ba9071c4'
down_revision: str | None = ('094cedeef31b', 'fd5c388e2451')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
