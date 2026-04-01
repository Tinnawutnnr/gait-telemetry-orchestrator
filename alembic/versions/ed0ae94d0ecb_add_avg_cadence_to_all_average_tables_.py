"""add avg_cadence to all average tables and add cohort summary table

Revision ID: ed0ae94d0ecb
Revises: 242b98f29d3b
Create Date: 2026-04-01 16:27:22.572040
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ed0ae94d0ecb'
down_revision: str | None = '242b98f29d3b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create the new cohort benchmark table
    op.create_table('cohort_benchmark_data',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('age_center', sa.Integer(), nullable=False),
        sa.Column('metric', sa.String(), nullable=False),
        sa.Column('cohort_vals', postgresql.ARRAY(sa.Float()), server_default='{}', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('age_center', 'metric', name='uq_cohort_benchmark')
    )
    op.create_index(op.f('ix_cohort_benchmark_data_age_center'), 'cohort_benchmark_data', ['age_center'], unique=False)
    op.create_index(op.f('ix_cohort_benchmark_data_metric'), 'cohort_benchmark_data', ['metric'], unique=False)

    # 2. Add avg_cadence column to all average tables
    op.add_column('daily_averages', sa.Column('avg_cadence', sa.Float(), nullable=True))
    op.add_column('weekly_averages', sa.Column('avg_cadence', sa.Float(), nullable=True))
    op.add_column('monthly_averages', sa.Column('avg_cadence', sa.Float(), nullable=True))
    op.add_column('yearly_averages', sa.Column('avg_cadence', sa.Float(), nullable=True))


def downgrade() -> None:
    # 1. Remove avg_cadence column from all average tables
    op.drop_column('yearly_averages', 'avg_cadence')
    op.drop_column('monthly_averages', 'avg_cadence')
    op.drop_column('weekly_averages', 'avg_cadence')
    op.drop_column('daily_averages', 'avg_cadence')

    # 2. Drop the cohort benchmark table
    op.drop_index(op.f('ix_cohort_benchmark_data_metric'), table_name='cohort_benchmark_data')
    op.drop_index(op.f('ix_cohort_benchmark_data_age_center'), table_name='cohort_benchmark_data')
    op.drop_table('cohort_benchmark_data')