"""partition_window_reports

Revision ID: 157ad1d052bb
Revises: f39c2dac4f38
Create Date: 2026-03-18 16:26:46.695509
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '157ad1d052bb'
down_revision: str | None = 'f39c2dac4f38'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Rename existing tables
    op.rename_table("anomaly_logs", "anomaly_logs_old")
    op.rename_table("window_reports", "window_reports_old")
    
    op.execute("DROP INDEX IF EXISTS ix_window_reports_patient_id;")
    op.execute("DROP INDEX IF EXISTS ix_window_reports_timestamp;")
    op.execute("DROP INDEX IF EXISTS ix_anomaly_logs_window_id;")
    op.execute("DROP INDEX IF EXISTS ix_anomaly_logs_patient_id;")
    op.execute("DROP INDEX IF EXISTS ix_anomaly_logs_timestamp;")

    # 2. Re-create `window_reports` as a partitioned table
    op.execute("""
        CREATE TABLE window_reports (
            window_report_id VARCHAR NOT NULL,
            patient_id BIGINT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            status VARCHAR,
            gait_health VARCHAR,
            anomaly_score DOUBLE PRECISION,
            max_gyr_ms DOUBLE PRECISION,
            val_gyr_hs DOUBLE PRECISION,
            swing_time DOUBLE PRECISION,
            stance_time DOUBLE PRECISION,
            stride_time DOUBLE PRECISION,
            stride_cv DOUBLE PRECISION,
            n_strides INTEGER,
            steps INTEGER,
            calories DOUBLE PRECISION,
            distance_m DOUBLE PRECISION,
            CONSTRAINT pk_window_reports PRIMARY KEY (window_report_id, timestamp),
            CONSTRAINT fk_window_reports_patients FOREIGN KEY (patient_id) REFERENCES patients(id),
            CONSTRAINT ck_window_reports_status CHECK (status IN ('CALIBRATING', 'MONITORING')),
            CONSTRAINT ck_window_reports_gait_health CHECK (gait_health IN ('NORMAL', 'ANOMALY_DETECTED'))
        ) PARTITION BY RANGE (timestamp);
    """)

    op.create_index("ix_window_reports_patient_id", "window_reports", ["patient_id"])
    op.create_index("ix_window_reports_timestamp", "window_reports", ["timestamp"])

    # Create initial partitions (Example: 2026-03, 2026-04, 2026-05)
    op.execute("CREATE TABLE window_reports_2026_03 PARTITION OF window_reports FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');")
    op.execute("CREATE TABLE window_reports_2026_04 PARTITION OF window_reports FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');")
    op.execute("CREATE TABLE window_reports_2026_05 PARTITION OF window_reports FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');")

    # 3. Re-create `anomaly_logs` as a partitioned table
    op.execute("""
        CREATE TABLE anomaly_logs (
            anomaly_id VARCHAR NOT NULL,
            window_id VARCHAR NOT NULL,
            patient_id BIGINT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            anomaly_score DOUBLE PRECISION,
            root_cause_feature VARCHAR,
            z_score DOUBLE PRECISION,
            current_val DOUBLE PRECISION,
            normal_ref DOUBLE PRECISION,
            CONSTRAINT pk_anomaly_logs PRIMARY KEY (anomaly_id, timestamp),
            CONSTRAINT fk_anomaly_logs_window_reports FOREIGN KEY (window_id, timestamp) REFERENCES window_reports(window_report_id, timestamp),
            CONSTRAINT fk_anomaly_logs_patients FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE RESTRICT
        ) PARTITION BY RANGE (timestamp);
    """)

    op.create_index("ix_anomaly_logs_window_id", "anomaly_logs", ["window_id"])
    op.create_index("ix_anomaly_logs_patient_id", "anomaly_logs", ["patient_id"])
    op.create_index("ix_anomaly_logs_timestamp", "anomaly_logs", ["timestamp"])

    op.execute("CREATE TABLE anomaly_logs_2026_03 PARTITION OF anomaly_logs FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');")
    op.execute("CREATE TABLE anomaly_logs_2026_04 PARTITION OF anomaly_logs FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');")
    op.execute("CREATE TABLE anomaly_logs_2026_05 PARTITION OF anomaly_logs FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');")

    # 4. Migrate data
    op.execute("""
        INSERT INTO window_reports (
            window_report_id, patient_id, timestamp, status, gait_health, 
            anomaly_score, max_gyr_ms, val_gyr_hs, swing_time, stance_time, 
            stride_time, stride_cv, n_strides, steps, calories, distance_m
        )
        SELECT 
            window_report_id, patient_id, timestamp, status, gait_health, 
            anomaly_score, max_gyr_ms, val_gyr_hs, swing_time, stance_time, 
            stride_time, stride_cv, n_strides, steps, calories, distance_m
        FROM window_reports_old;
    """)

    op.execute("""
        INSERT INTO anomaly_logs (
            anomaly_id, window_id, patient_id, timestamp, 
            anomaly_score, root_cause_feature, z_score, current_val, normal_ref
        )
        SELECT 
            a.anomaly_id, 
            a.window_id, 
            a.patient_id, 
            w.timestamp,  -- Fetch exact timestamp from parent to avoid FK violations
            a.anomaly_score, 
            a.root_cause_feature, 
            a.z_score, 
            a.current_val, 
            a.normal_ref
        FROM anomaly_logs_old a
        JOIN window_reports_old w ON a.window_id = w.window_report_id;
    """)

    # 5. Drop old tables
    op.drop_table("anomaly_logs_old")
    op.drop_table("window_reports_old")


def downgrade() -> None:
    # 1. Rename existing partitioned tables
    op.rename_table("anomaly_logs", "anomaly_logs_partitioned")
    op.rename_table("window_reports", "window_reports_partitioned")
    
    op.execute("DROP INDEX IF EXISTS ix_window_reports_patient_id;")
    op.execute("DROP INDEX IF EXISTS ix_window_reports_timestamp;")
    op.execute("DROP INDEX IF EXISTS ix_anomaly_logs_window_id;")
    op.execute("DROP INDEX IF EXISTS ix_anomaly_logs_patient_id;")
    op.execute("DROP INDEX IF EXISTS ix_anomaly_logs_timestamp;")

    # 2. Re-create old unpartitioned tables
    op.execute("""
        CREATE TABLE window_reports (
            window_report_id VARCHAR NOT NULL,
            patient_id BIGINT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            status VARCHAR,
            gait_health VARCHAR,
            anomaly_score DOUBLE PRECISION,
            max_gyr_ms DOUBLE PRECISION,
            val_gyr_hs DOUBLE PRECISION,
            swing_time DOUBLE PRECISION,
            stance_time DOUBLE PRECISION,
            stride_time DOUBLE PRECISION,
            stride_cv DOUBLE PRECISION,
            n_strides INTEGER,
            steps INTEGER,
            calories DOUBLE PRECISION,
            distance_m DOUBLE PRECISION,
            PRIMARY KEY (window_report_id),
            FOREIGN KEY(patient_id) REFERENCES patients (id),
            CHECK (gait_health IN ('NORMAL', 'ANOMALY_DETECTED')),
            CHECK (status IN ('CALIBRATING', 'MONITORING'))
        );
    """)
    op.create_index("ix_window_reports_patient_id", "window_reports", ["patient_id"])
    op.create_index("ix_window_reports_timestamp", "window_reports", ["timestamp"])

    op.execute("""
        CREATE TABLE anomaly_logs (
            anomaly_id VARCHAR NOT NULL,
            window_id VARCHAR NOT NULL,
            patient_id BIGINT NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            anomaly_score DOUBLE PRECISION,
            root_cause_feature VARCHAR,
            z_score DOUBLE PRECISION,
            current_val DOUBLE PRECISION,
            normal_ref DOUBLE PRECISION,
            PRIMARY KEY (anomaly_id),
            FOREIGN KEY(patient_id) REFERENCES patients (id) ON DELETE RESTRICT,
            FOREIGN KEY(window_id) REFERENCES window_reports (window_report_id)
        );
    """)
    op.create_index('ix_anomaly_logs_patient_id', 'anomaly_logs', ['patient_id'])
    op.create_index('ix_anomaly_logs_timestamp', 'anomaly_logs', ['timestamp'])
    op.create_index('ix_anomaly_logs_window_id', 'anomaly_logs', ['window_id'])
    op.execute("ALTER TABLE anomaly_logs ADD CONSTRAINT uq_anomaly_logs_window_id UNIQUE (window_id);")

    # 3. Migrate data back
    op.execute("""
        INSERT INTO window_reports (
            window_report_id, patient_id, timestamp, status, gait_health, 
            anomaly_score, max_gyr_ms, val_gyr_hs, swing_time, stance_time, 
            stride_time, stride_cv, n_strides, steps, calories, distance_m
        )
        SELECT 
            window_report_id, patient_id, timestamp, status, gait_health, 
            anomaly_score, max_gyr_ms, val_gyr_hs, swing_time, stance_time, 
            stride_time, stride_cv, n_strides, steps, calories, distance_m
        FROM window_reports_partitioned;
    """)
    op.execute("""
        INSERT INTO anomaly_logs (
            anomaly_id, window_id, patient_id, timestamp, 
            anomaly_score, root_cause_feature, z_score, current_val, normal_ref
        )
        SELECT 
            anomaly_id, 
            window_id, 
            patient_id, 
            timestamp, 
            anomaly_score, 
            root_cause_feature, 
            z_score, 
            current_val, 
            normal_ref
        FROM anomaly_logs_partitioned;
    """)

    # 4. Drop partitioned tables & their partitions automatically dropped by CASCADE
    op.execute("DROP TABLE anomaly_logs_partitioned CASCADE;")
    op.execute("DROP TABLE window_reports_partitioned CASCADE;")
