"""migrate_email_to_citext

Revision ID: 242b98f29d3b
Revises: 0a289eaceb61
Create Date: 2026-03-20 15:57:51.270253
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "242b98f29d3b"
down_revision: str | None = "0a289eaceb61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable the citext extension
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    conn = op.get_bind()
    duplicate_rows = conn.execute(
        sa.text(
            """
            SELECT LOWER(email) AS normalized_email, COUNT(*) AS count
            FROM users
            GROUP BY LOWER(email)
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicate_rows:
        duplicated_emails = ", ".join(
            sorted({row.normalized_email for row in duplicate_rows if row.normalized_email is not None})
        )
        raise RuntimeError(
            "Cannot migrate users.email to CITEXT because the following email "
            "values are duplicated when compared case-insensitively: "
            f"{duplicated_emails}. Please resolve or merge these accounts "
            "so that no two users share the same email ignoring case, then "
            "re-run this migration."
        )

    # Normalize existing email strings
    op.execute("UPDATE users SET email = LOWER(email)")

    # Alter the email column type to CITEXT
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(),
        type_=postgresql.CITEXT(),
        existing_nullable=False,
        postgresql_using="email::citext",
    )


def downgrade() -> None:
    # Revert the email column type back to standard String/VARCHAR
    op.alter_column(
        "users",
        "email",
        existing_type=postgresql.CITEXT(),
        type_=sa.String(),
        existing_nullable=False,
    )
