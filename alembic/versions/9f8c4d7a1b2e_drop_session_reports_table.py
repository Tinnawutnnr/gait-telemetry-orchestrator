"""drop_session_reports_table

Revision ID: 9f8c4d7a1b2e
Revises: 56b0ba9071c4
Create Date: 2026-03-19 18:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f8c4d7a1b2e"
down_revision: str | None = "56b0ba9071c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_session_reports_timestamp;")
    op.execute("DROP INDEX IF EXISTS ix_session_reports_patient_timestamp;")
    op.execute("DROP INDEX IF EXISTS ix_session_reports_patient_id;")
    op.execute("DROP TABLE IF EXISTS session_reports;")


def downgrade() -> None:
    op.create_table(
        "session_reports",
        sa.Column("session_report_id", sa.String(), nullable=False),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("total_windows_analyzed", sa.Integer(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("total_calories", sa.Float(), nullable=True),
        sa.Column("total_distance_m", sa.Float(), nullable=True),
        sa.Column("avg_max_gyr_ms", sa.Float(), nullable=True),
        sa.Column("avg_val_gyr_hs", sa.Float(), nullable=True),
        sa.Column("avg_swing_time", sa.Float(), nullable=True),
        sa.Column("avg_stance_time", sa.Float(), nullable=True),
        sa.Column("avg_stride_cv", sa.Float(), nullable=True),
        sa.Column("anomaly_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("session_report_id"),
    )
    op.create_index(op.f("ix_session_reports_patient_id"), "session_reports", ["patient_id"], unique=False)
    op.create_index(
        "ix_session_reports_patient_timestamp", "session_reports", ["patient_id", "timestamp"], unique=False
    )
    op.create_index(op.f("ix_session_reports_timestamp"), "session_reports", ["timestamp"], unique=False)
