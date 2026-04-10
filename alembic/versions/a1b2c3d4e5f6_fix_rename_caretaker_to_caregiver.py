"""fix: rename caretaker to caregiver

Revision ID: a1b2c3d4e5f6
Revises: ed0ae94d0ecb
Create Date: 2026-04-10 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "ed0ae94d0ecb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename caretakers table to caregivers
    op.rename_table("caretakers", "caregivers")

    # Rename caretaker_id column on patients to caregiver_id
    op.alter_column("patients", "caretaker_id", new_column_name="caregiver_id")

    # Update the role check constraint on users
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role IN ('caregiver', 'patient')")

    # Rename indexes to match new names
    op.execute("ALTER INDEX IF EXISTS ix_caretakers_user_id RENAME TO ix_caregivers_user_id")
    op.execute("ALTER INDEX IF EXISTS ix_patients_caretaker_id RENAME TO ix_patients_caregiver_id")


def downgrade() -> None:
    # Revert index renames
    op.execute("ALTER INDEX IF EXISTS ix_patients_caregiver_id RENAME TO ix_patients_caretaker_id")
    op.execute("ALTER INDEX IF EXISTS ix_caregivers_user_id RENAME TO ix_caretakers_user_id")

    # Revert role check constraint
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role IN ('caretaker', 'patient')")

    # Revert column rename
    op.alter_column("patients", "caregiver_id", new_column_name="caretaker_id")

    # Revert table rename
    op.rename_table("caregivers", "caretakers")
