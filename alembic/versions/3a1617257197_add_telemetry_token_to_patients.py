"""add telemetry token to patients

Revision ID: 3a1617257197
Revises: 094cedeef31b
Create Date: 2026-03-19 15:34:52.687976
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1617257197"
down_revision: str | None = "094cedeef31b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the column telemetry_token with nullable=True.
    op.add_column("patients", sa.Column("telemetry_token", sa.String(), nullable=True))

    # 2. Execute a raw SQL update utilizing pg_crypto/native UUID gen for backfill.
    op.execute("UPDATE patients SET telemetry_token = gen_random_uuid()::text")

    # 3. Alter the telemetry_token column to nullable=False.
    op.alter_column("patients", "telemetry_token", existing_type=sa.String(), nullable=False)

    # 4. Create the unique index for telemetry_token.
    op.create_index(op.f("ix_patients_telemetry_token"), "patients", ["telemetry_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_patients_telemetry_token"), table_name="patients")
    op.drop_column("patients", "telemetry_token")
