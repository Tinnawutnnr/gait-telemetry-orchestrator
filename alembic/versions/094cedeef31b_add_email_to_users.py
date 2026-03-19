"""add email to users

Revision ID: 094cedeef31b
Revises: 157ad1d052bb
Create Date: 2026-03-19 14:02:42.560454
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '094cedeef31b'
down_revision: str | None = '157ad1d052bb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add column with nullable=True
    op.add_column("users", sa.Column("email", sa.String(), nullable=True))
    
    # 2. Populate existing rows to avoid "contains null values" execution errors
    op.execute("UPDATE users SET email = username || '@temp-migration.com'")
    
    # 3. Alter column to nullable=False and apply unique index
    op.alter_column("users", "email", existing_type=sa.String(), nullable=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_column("users", "email")
