# PERGA Backend — Gait Telemetry Orchestrator

[![CI/CD Pipeline](https://github.com/Tinnawutnnr/gait-telemetry-orchestrator/actions/workflows/ci_cd.yml/badge.svg)](https://github.com/Tinnawutnnr/gait-telemetry-orchestrator/actions/workflows/ci_cd.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00a393.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)

---

## 1. Abstract

Falls represent the leading cause of injury-related morbidity and mortality among elderly populations, yet existing clinical gait assessment methods rely on periodic, in-clinic observation that fails to capture day-to-day variability in ambulatory function. The **PERGA** (Personalized Gait Anomaly Detection in Elderly) backend is the server-side orchestration layer of a continuous gait monitoring system designed to address this gap. The system ingests high-frequency inertial measurement unit (IMU) telemetry streamed at 100 Hz from ESP32-C3 wearable devices via the MQTT protocol, routes the raw signal through an asynchronous message broker (Apache Kafka), and applies a real-time signal processing pipeline consisting of fourth-order Butterworth low-pass filtering, gait-event detection via peak matching, and five-dimensional kinematic feature extraction. Anomaly detection is performed per-patient using a Local Outlier Factor (LOF) model operating in novelty detection mode, which compares the density of incoming gait feature vectors against a continuously updated personalized baseline. Detected anomalies trigger clinical alerts to designated caregivers and are persisted alongside multi-granularity temporal aggregations (daily, weekly, monthly, yearly) in a declaratively partitioned PostgreSQL 16 time-series store. A RESTful API layer with role-based access control exposes processed gait metrics and anomaly histories to the companion mobile application.

---

## 2. System Architecture & Data Flow

The PERGA backend is composed of four independently deployable asynchronous services that communicate through a shared PostgreSQL database and an Apache Kafka message broker. The architecture enforces strict separation between the **ingestion path** (write-optimized, event-driven) and the **query path** (read-optimized, request-response).

### 2.1 End-to-End Data Path

```
ESP32-C3 (IMU @ 100 Hz)
    │  gyro_z samples, JSON over MQTT
    ▼
HiveMQ Cloud (MQTT Broker)
    │  TLS 8883, QoS 1, topic: gait/telemetry/{telemetry_token}
    ▼
┌─────────────────────────┐
│   Ingestion Bridge      │  aiomqtt subscriber → AIOKafkaProducer
│   (workers/ingestion_   │  Token → patient_id resolution (cached)
│    bridge.py)           │  send_and_wait(), acks="all"
└─────────┬───────────────┘
          │  raw bytes, keyed by patient_id
          ▼
    Apache Kafka
    Topic: raw-gait-telemetry
    (KRaft mode, single broker)
          │
          ▼
┌─────────────────────────┐
│   ML Worker             │  AIOKafkaConsumer, group: gait_data_consumers
│   (workers/ml_worker.py)│  Per-patient GaitSystem instances
│                         │  Butterworth filter → Feature extraction → LOF
│                         │  Persists WindowReport + AnomalyLog
│                         │  Sends anomaly alert emails (async task)
└─────────┬───────────────┘
          │  INSERT into PostgreSQL
          ▼
┌─────────────────────────┐
│   PostgreSQL 16         │  Partitioned: window_reports, anomaly_logs
│   (RANGE by timestamp)  │  Aggregated: daily/weekly/monthly/yearly_averages
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│   FastAPI REST API      │  4 Uvicorn workers, asyncpg, JWT/RBAC
│   (app/main.py)         │  Serves processed metrics to mobile app
└─────────────────────────┘

┌─────────────────────────┐
│   Batch Aggregator      │  APScheduler (Asia/Bangkok timezone)
│   (workers/batch_       │  00:01 — WindowReport → Daily/Weekly/Monthly/Yearly
│    aggregator.py)       │  02:00 — Cohort benchmark pre-query (cohort_schedule.py)
└─────────────────────────┘
```

### 2.2 Service Descriptions

| Service | Process | Async Model | Database Access |
|---------|---------|-------------|-----------------|
| **API** | `uvicorn app.main:app` (4 workers) | `asyncpg` via SQLAlchemy `AsyncSession` | Read path (queries) |
| **Ingestion Bridge** | `python -m workers.ingestion_bridge` | `aiomqtt` + `AIOKafkaProducer` | None (HTTP call to API for token resolution) |
| **ML Worker** | `python -m workers.ml_worker` | `AIOKafkaConsumer` + `asyncio.to_thread` for DB | Write path (inserts) |
| **Batch Aggregator** | `python -m workers.batch_aggregator` | `APScheduler` (blocking, Asia/Bangkok) + sync SQLAlchemy | Read/write (aggregation) |

### 2.3 Async Boundaries

Three explicit async boundaries decouple the system:

1. **MQTT &rarr; Kafka**: The ingestion bridge subscribes to HiveMQ and publishes to Kafka using `send_and_wait()`. This decouples the 100 Hz ingestion rate from downstream processing capacity. Kafka provides durable buffering if the ML worker falls behind.
2. **Kafka &rarr; Database**: The ML worker consumes from Kafka, processes signal data in a thread pool (`asyncio.to_thread`), and writes results to PostgreSQL. This isolates CPU-bound signal processing from async I/O.
3. **Anomaly detection &rarr; Email**: Anomaly alert emails are dispatched as fire-and-forget `asyncio.Task` instances, preventing email delivery latency from blocking the processing loop.

### 2.4 Docker Compose Orchestration

All services are orchestrated via `docker-compose.yml` on a shared bridge network (`gait_net`). Service dependencies enforce startup ordering via health checks:

- **PostgreSQL** must pass `pg_isready` before API, ML Worker, and Batch Aggregator start.
- **Kafka** must pass topic listing before Ingestion Bridge and ML Worker start.
- The **Ingestion Bridge** uses a file-based health check (`/tmp/bridge_healthy` mtime < 60s).
- The **API** uses HTTP `GET /health` with a 30-second interval.

---

## 3. MQTT Ingestion & Protocol Design

### 3.1 Topic Schema

The backend subscribes to a single wildcard topic:

```
gait/telemetry/+
```

The `+` single-level wildcard matches the patient's `telemetry_token` — a UUID v4 string assigned at profile creation and stored in the `patients.telemetry_token` column. A concrete topic example:

```
gait/telemetry/a3f8b2c1-7d4e-4a91-b6f0-9e2c5d1a8f47
```

### 3.2 Payload Format

The ESP32-C3 publishes JSON payloads containing z-axis gyroscope readings. The ML worker accepts multiple payload shapes:

```json
// Batch of samples (preferred for throughput)
{"gyro_z": [1.23, -0.45, 2.67, ...]}

// Single sample
{"gyro_z": 1.23}

// Raw list (no key wrapper)
[1.23, -0.45, 2.67, ...]

// Single scalar
1.23
```

All values represent angular velocity in rad/s from the IMU's z-axis gyroscope.

### 3.3 Consumer Lifecycle

The MQTT consumer is implemented using `aiomqtt.Client` (`workers/ingestion_bridge.py`):

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `hostname` | HiveMQ Cloud cluster | Managed MQTT broker |
| `port` | 8883 | MQTT over TLS |
| `tls_context` | `ssl.create_default_context()` | System CA bundle for certificate verification |
| `keepalive` | 30 seconds | Detect stale connections before TCP timeout |
| `qos` | 1 (at-least-once) | Tolerates duplicate delivery; prevents data loss |

**Reconnection strategy**: Exponential backoff with parameters `base=1.0s`, `factor=2.0`, `cap=60.0s`, and a maximum of 5 MQTT connection attempts before the process exits. Kafka connection uses the same backoff pattern without a retry limit.

**Graceful shutdown**: SIGINT and SIGTERM are caught via `asyncio` signal handlers, setting a shared `asyncio.Event` that unblocks all `wait_for` calls and triggers orderly disconnection of both MQTT and Kafka clients.

### 3.4 Ingestion-to-Processing Handoff

The handoff from MQTT to the processing pipeline is **fully asynchronous via Apache Kafka**:

1. The bridge extracts the `telemetry_token` from the MQTT topic path.
2. The token is resolved to a `patient_id` (integer) via an HTTP GET to the API (`/api/v1/patients/{telemetry_token}`). Results are cached in an in-memory dictionary (`_TOKEN_TO_USER_CACHE`) to avoid per-message API calls.
3. The raw MQTT payload bytes are published to the `raw-gait-telemetry` Kafka topic using `send_and_wait()` with the `patient_id` as the message key. This ensures all messages for a given patient are routed to the same Kafka partition, preserving temporal ordering.

**Kafka producer configuration**:
```python
AIOKafkaProducer(
    bootstrap_servers=KAFKA_BROKER_URL,
    acks="all",       # Wait for all in-sync replicas to acknowledge
    linger_ms=5,      # Micro-batch for 5ms to improve throughput
)
```

### 3.5 Backpressure Handling

For 100 Hz streams, the system relies on Kafka's built-in backpressure mechanisms rather than application-level buffering. If the ML worker cannot keep pace with incoming messages, Kafka retains unconsumed messages on disk up to its configured retention limit. The consumer uses `auto_offset_reset="earliest"` to resume from the last committed offset after restarts, ensuring no data loss. There is no explicit application-level backpressure or rate limiting on the ingestion path.

---

## 4. Anomaly Detection Pipeline

The anomaly detection pipeline is implemented in `workers/realtime_processor.py` as the `GaitSystem` class. Each active patient maintains an independent `GaitSystem` instance with its own signal buffer, calibration state, and LOF model. The pipeline operates in two phases: **calibration** (baseline establishment) and **monitoring** (real-time anomaly scoring).

### 4.1 Signal Filtering

Raw gyroscope samples are filtered using a fourth-order Butterworth low-pass filter applied via zero-phase forward-backward filtering (`scipy.signal.filtfilt`):

```python
b, a = signal.butter(N=4, Wn=6 / (0.5 * 100), btype="low")
# N = 4 (filter order)
# Wn = 6 / 50 = 0.12 (normalized cutoff frequency)
# Absolute cutoff = 6 Hz
# Sampling frequency (Fs) = 100 Hz
```

**Rationale for 6 Hz cutoff**: Human gait produces a fundamental frequency of approximately 1.5-2.0 Hz during normal walking, with significant harmonic content extending to approximately 4-5 Hz. A 6 Hz cutoff preserves the full gait signal spectrum — including the second and third harmonics that encode heel-strike and toe-off events — while rejecting higher-frequency sensor noise, vibration artifacts, and electrical interference. The fourth-order design provides a roll-off of approximately -80 dB/decade, ensuring sharp attenuation above the cutoff. Zero-phase filtering via `filtfilt` eliminates the phase distortion that would otherwise shift peak locations in the time domain, which is critical for accurate gait event timing.

The transfer function of the Butterworth filter is:

$$|H(j\omega)|^2 = \frac{1}{1 + \left(\frac{\omega}{\omega_c}\right)^{2N}}$$

where *N* = 4 and *&omega;<sub>c</sub>* = 2&pi; &times; 6 rad/s.

### 4.2 Windowing

The pipeline uses **non-overlapping fixed-width windows** of 30 seconds (3,000 samples at 100 Hz):

```python
FS = 100              # Sampling frequency (Hz)
WINDOW_SECONDS = 30   # Window duration
WINDOW_SAMPLES = 3000 # FS * WINDOW_SECONDS
```

Samples are accumulated in a raw buffer (`raw_buffer`). When the buffer reaches 3,000 samples, the first 3,000 are extracted for analysis and removed from the buffer. This is a non-overlapping (hop = window length) scheme, meaning each sample is analyzed exactly once. The 30-second window provides sufficient temporal extent to capture approximately 25-30 complete gait cycles at normal elderly walking cadence (~100 steps/min), ensuring statistically reliable feature estimates.

Additionally, a **live metrics update** runs every 1 second (every 100 samples) for real-time step counting and calorie estimation, independent of the 30-second deep analysis window.

### 4.3 Feature Extraction

Five kinematic features are extracted from each 30-second filtered window via the `_extract_params()` method. The extraction proceeds through gait event detection followed by temporal parameter computation.

#### 4.3.1 Gait Event Detection

**Midswing (MS) Peak Detection**:
```python
height_thresh = 0.25 * np.max(sig)
min_dist = int(0.4 * FS)  # 40 samples = 0.4 seconds
ms_peaks, _ = find_peaks(sig, distance=min_dist, height=height_thresh)
```
MS peaks correspond to the maximum angular velocity during the leg swing phase. The minimum distance of 0.4 seconds enforces a physiological lower bound on stride duration, preventing double-counting within a single stride.

**Heel-Strike (HS) Candidate Detection**:
```python
hs_candidates, _ = find_peaks(-sig, distance=int(0.3 * FS))  # 30 samples
```
HS events appear as local minima (nadirs) in the gyroscope signal, corresponding to the deceleration impulse at foot contact. Detecting peaks in the negated signal identifies these minima.

**MS-HS Pair Matching**:
Each MS peak is paired with the nearest subsequent HS candidate within a 0.5-second window (50 samples). A minimum of 5 valid MS-HS pairs is required to proceed; otherwise, the window is classified as non-ambulatory and discarded.

**Toe-Off (TO) Detection**:
For each consecutive HS pair (HS[i], HS[i+1]), the algorithm identifies the midswing peak between them and locates the signal minimum between HS[i] + 50ms and the next MS peak. This minimum corresponds to the toe-off event, marking the transition from stance to swing phase.

#### 4.3.2 Extracted Features

| Feature | Symbol | Definition | Unit |
|---------|--------|------------|------|
| **Max Gyroscope at Midswing** | `max_gyr_ms` | Mean of gyroscope values at detected MS peak indices: *&mu;*(*g*[MS<sub>i</sub>]) | rad/s |
| **Gyroscope Value at Heel-Strike** | `val_gyr_hs` | Mean of gyroscope values at detected HS peak indices: *&mu;*(*g*[HS<sub>i</sub>]) | rad/s |
| **Swing Time** | `swing_time` | Mean duration from toe-off to next heel-strike: *&mu;*((HS<sub>i+1</sub> - TO<sub>i</sub>) / *F<sub>s</sub>*) | s |
| **Stance Time** | `stance_time` | Mean duration from heel-strike to toe-off: *&mu;*((TO<sub>i</sub> - HS<sub>i</sub>) / *F<sub>s</sub>*) | s |
| **Stride Time CV** | `stride_cv` | Coefficient of variation of stride durations: (*&sigma;*(*T<sub>stride</sub>*) / *&mu;*(*T<sub>stride</sub>*)) &times; 100 | % |

where *T<sub>stride,i</sub>* = (HS<sub>i+1</sub> - HS<sub>i</sub>) / *F<sub>s</sub>* and *F<sub>s</sub>* = 100 Hz.

**Physiological filtering**: Stance and swing times outside the range [0.2, 2.0] seconds are discarded as physiologically implausible. After filtering, a minimum of 4 valid strides is required to produce a feature vector.

#### 4.3.3 Derived Metrics (Non-ML)

In addition to the five ML features, each window computes activity metrics for the patient dashboard:

| Metric | Computation |
|--------|-------------|
| `steps` | *n_strides* &times; 2 (bilateral assumption) |
| `calories` | MET &times; *weight<sub>kg</sub>* &times; (*T<sub>window</sub>* / 3600), where MET = 4.0 if cadence &ge; 100, else 3.0 |
| `distance_m` | *steps* &times; *height<sub>cm</sub>* &times; 0.415 / 100 (stride length approximation) |

### 4.4 LOF Anomaly Scoring

#### 4.4.1 Calibration Phase

During calibration, the system collects normal gait windows to establish a per-patient baseline:

1. Each window must contain **&ge;20 valid strides** to be considered reliable for training.
2. **10 reliable windows** (`CALIBRATION_WINDOWS = 10`) must be accumulated before the LOF model is trained.
3. During calibration, each window report is saved with `status = "CALIBRATING"` and no anomaly scoring is performed.

The ML worker checks the persisted `status` field on startup to determine whether a patient's `GaitSystem` instance should resume in calibration mode or monitoring mode, avoiding unnecessary re-calibration after restarts when sufficient data already exists.

#### 4.4.2 Model Training

```python
def _train_model(self):
    X_train = np.array(self.normal_windows)  # Shape: (n, 5)
    n_samples = len(X_train)
    n_neighbors = min(15, n_samples - 1)     # Cap k at 15

    self.scaler.fit(X_train)
    X_train_scaled = self.scaler.transform(X_train)

    self.model = LocalOutlierFactor(
        n_neighbors=n_neighbors,
        contamination=0.01,
        metric="manhattan",
        novelty=True
    )
    self.model.fit(X_train_scaled)
```

| LOF Parameter | Value | Rationale |
|---------------|-------|-----------|
| `n_neighbors` | min(15, *n* - 1) | Adaptive: uses all available neighbors during early calibration; caps at 15 to balance local sensitivity against global robustness |
| `contamination` | 0.01 | Assumes 1% of the training data may contain mild outliers, providing tolerance against imperfect calibration windows |
| `metric` | `"manhattan"` | L1 distance is more robust to individual feature outliers than Euclidean distance in low-dimensional spaces |
| `novelty` | `True` | Enables `predict()` and `decision_function()` on unseen data; the model operates as a novelty detector rather than an inlier/outlier classifier on the training set |

Feature vectors are standardized using `sklearn.preprocessing.StandardScaler` (zero mean, unit variance) before LOF training and prediction, ensuring that features with different physical units (rad/s, seconds, %) contribute equally to the distance computation.

The LOF algorithm estimates the local density of each point as the inverse of its average reachability distance to its *k* nearest neighbors:

$$\text{lrd}_k(x) = \left(\frac{1}{k} \sum_{o \in N_k(x)} \text{reach-dist}_k(x, o)\right)^{-1}$$

The Local Outlier Factor is then:

$$\text{LOF}_k(x) = \frac{1}{k} \sum_{o \in N_k(x)} \frac{\text{lrd}_k(o)}{\text{lrd}_k(x)}$$

A LOF value near 1 indicates the point has similar density to its neighbors (normal); values significantly greater than 1 indicate the point lies in a lower-density region (anomalous).

#### 4.4.3 Monitoring Phase

Once calibrated, each incoming window is scored:

1. The 5-feature vector is scaled using the fitted `StandardScaler`.
2. `model.predict(X)` returns `1` (inlier/normal) or `-1` (outlier/anomaly).
3. `model.decision_function(X)` returns a continuous score (more negative = more anomalous).

**Dynamic baseline update**: When a window is classified as **normal** and has &ge;20 strides, it is appended to the `normal_windows` buffer. If the buffer exceeds 50 windows (`MAX_BUFFER_SIZE`), the oldest window is removed (FIFO). The LOF model is **retrained** after every normal window addition. This sliding window retraining allows the model to adapt to gradual changes in gait pattern (e.g., post-surgical recovery, seasonal mobility changes) while maintaining sensitivity to acute deviations.

**Root cause identification**: When an anomaly is detected, the system identifies the most deviant feature by examining the scaled input vector and selecting the feature with the highest absolute value:

```python
z_scores = input_vec[0]            # Standardized feature values
max_dev_idx = np.argmax(np.abs(z_scores))
feature_name = self.feature_names[max_dev_idx]  # e.g., "stride_cv"
z_val = z_scores[max_dev_idx]
normal_mean = self.scaler.mean_[max_dev_idx]
current_val = ml_features[max_dev_idx]
```

This provides clinically interpretable anomaly explanations (e.g., "Stride consistency deviated 2.3 standard deviations from baseline").

#### 4.4.4 Model Persistence

The LOF model, scaler, and normal window buffer exist **only in memory** within each `GaitSystem` instance. There is no disk serialization. If the ML worker process restarts, all patients re-enter the calibration phase. Patient state is also evicted after 30 minutes of inactivity (`PATIENT_STATE_TTL_SECONDS = 1800`).

### 4.5 Anomaly Alerting

When an anomaly is detected, the ML worker:

1. Persists a `WindowReport` with `gait_health = "ANOMALY_DETECTED"` and an `AnomalyLog` record containing the root cause feature, z-score, current value, and normal reference value.
2. Dispatches alert emails (via `asyncio.create_task`) using the Resend API to both the **patient** and their **linked caregiver** (if one exists). The contact resolution function (`_get_patient_contact_info_sync`) fetches both the patient's email and the caregiver's email from the database in a single query. Each email includes:
   - A severity badge based on the percentage deviation from normal: **Slight Change** (<5%, yellow), **Noticeable Change** (5-10%, orange), **Significant Change** (&ge;10%, red).
   - The human-readable feature name (e.g., "Leg Swing Speed" for `max_gyr`), today's value, and the patient's normal average.

---

## 5. Database Schema & Partitioning Design

### 5.1 Entity-Relationship Overview

The database contains 10 tables organized into three domains: **identity** (users, caregivers, patients), **time-series** (window_reports, anomaly_logs), and **aggregation** (daily/weekly/monthly/yearly averages, cohort benchmarks).

### 5.2 Identity Tables

#### `users`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `BIGINT` | PRIMARY KEY, auto-increment |
| `username` | `VARCHAR` | UNIQUE, NOT NULL, indexed |
| `email` | `CITEXT` | UNIQUE, NOT NULL, indexed |
| `hashed_password` | `VARCHAR` | NOT NULL |
| `role` | `VARCHAR` | NOT NULL, CHECK IN (`'caregiver'`, `'patient'`) |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | DEFAULT `now()` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | DEFAULT `now()`, ON UPDATE `now()` |

The `CITEXT` extension provides case-insensitive email uniqueness without application-level normalization.

#### `caregivers`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `BIGINT` | PRIMARY KEY, auto-increment |
| `user_id` | `BIGINT` | UNIQUE, FK &rarr; `users(id)` ON DELETE CASCADE |
| `first_name` | `VARCHAR` | NOT NULL |
| `last_name` | `VARCHAR` | NOT NULL |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | DEFAULT `now()` |

#### `patients`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `BIGINT` | PRIMARY KEY, auto-increment |
| `user_id` | `BIGINT` | UNIQUE, NULLABLE, FK &rarr; `users(id)` ON DELETE CASCADE |
| `caregiver_id` | `BIGINT` | NULLABLE, FK &rarr; `caregivers(id)` ON DELETE SET NULL |
| `first_name` | `VARCHAR` | NOT NULL |
| `last_name` | `VARCHAR` | NOT NULL |
| `age` | `INTEGER` | NULLABLE |
| `height` | `FLOAT` | NOT NULL |
| `weight` | `FLOAT` | NOT NULL |
| `telemetry_token` | `VARCHAR` | UNIQUE, NOT NULL, indexed (UUID v4) |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | DEFAULT `now()` |

The `telemetry_token` enables device authentication without transmitting user credentials over MQTT. The `caregiver_id` foreign key uses `SET NULL` to allow soft-unlinking without cascading deletes.

### 5.3 Time-Series Tables (Partitioned)

#### `window_reports`
| Column | Type | Constraints |
|--------|------|-------------|
| `window_report_id` | `VARCHAR` | PRIMARY KEY (composite with timestamp) |
| `patient_id` | `BIGINT` | FK &rarr; `patients(id)`, indexed |
| `timestamp` | `TIMESTAMP WITH TIME ZONE` | PRIMARY KEY (composite), DEFAULT `now()`, indexed |
| `status` | `VARCHAR` | NULLABLE, CHECK IN (`'CALIBRATING'`, `'MONITORING'`) |
| `gait_health` | `VARCHAR` | NULLABLE, CHECK IN (`'NORMAL'`, `'ANOMALY_DETECTED'`) |
| `anomaly_score` | `FLOAT` | NULLABLE |
| `max_gyr_ms` | `FLOAT` | NULLABLE |
| `val_gyr_hs` | `FLOAT` | NULLABLE |
| `swing_time` | `FLOAT` | NULLABLE |
| `stance_time` | `FLOAT` | NULLABLE |
| `stride_time` | `FLOAT` | NULLABLE |
| `stride_cv` | `FLOAT` | NULLABLE |
| `n_strides` | `INTEGER` | NULLABLE |
| `steps` | `INTEGER` | NULLABLE |
| `calories` | `FLOAT` | NULLABLE |
| `distance_m` | `FLOAT` | NULLABLE |

**Partitioning**: `PARTITION BY RANGE (timestamp)`, monthly granularity.

#### `anomaly_logs`
| Column | Type | Constraints |
|--------|------|-------------|
| `anomaly_id` | `VARCHAR` | PRIMARY KEY (composite with timestamp) |
| `window_id` | `VARCHAR` | FK (composite), indexed |
| `patient_id` | `BIGINT` | FK &rarr; `patients(id)` ON DELETE RESTRICT, indexed |
| `timestamp` | `TIMESTAMP WITH TIME ZONE` | PRIMARY KEY (composite), DEFAULT `now()`, indexed |
| `anomaly_score` | `FLOAT` | NULLABLE |
| `root_cause_feature` | `VARCHAR` | NULLABLE |
| `z_score` | `FLOAT` | NULLABLE |
| `current_val` | `FLOAT` | NULLABLE |
| `normal_ref` | `FLOAT` | NULLABLE |

**Composite foreign key**: `(window_id, timestamp)` &rarr; `window_reports(window_report_id, timestamp)`. This composite FK is required because PostgreSQL's declarative partitioning mandates that the partition key (`timestamp`) must be included in any unique constraint or foreign key referencing a partitioned table. A simple FK on `window_id` alone would fail, as uniqueness is only enforced within individual partitions, not across the entire partitioned table. Including `timestamp` in the FK ensures the database can route the constraint check to the correct partition.

The `ON DELETE RESTRICT` on `patient_id` prevents accidental deletion of patients who have anomaly records, preserving clinical audit trails.

### 5.4 Partitioning Strategy

Both `window_reports` and `anomaly_logs` use PostgreSQL declarative **range partitioning** on the `timestamp` column with monthly boundaries:

```sql
-- Example partition definitions (from migration 157ad1d052bb)
CREATE TABLE window_reports_2026_03
    PARTITION OF window_reports
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE TABLE anomaly_logs_2026_03
    PARTITION OF anomaly_logs
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
```

**Initial partitions seeded**: March, April, and May 2026 (three months), created in the partitioning migration. Future partitions must be provisioned manually via additional migrations or scheduled DDL.

**Why monthly partitioning**: At 100 Hz with 30-second windows, each patient generates up to 2,880 window reports per day. For a deployment with hundreds of patients, monthly partitions keep each partition's B-tree index manageable (tens of thousands of rows rather than millions), enable efficient time-range queries via partition pruning, and allow old partitions to be detached and archived without downtime.

### 5.5 Aggregation Tables

Four aggregation tables store pre-computed temporal rollups:

| Table | Period Key | Unique Constraint |
|-------|-----------|-------------------|
| `daily_averages` | `report_date` (DATE) | `(patient_id, report_date)` |
| `weekly_averages` | `report_week` (VARCHAR, `"YYYY-Www"`) | `(patient_id, report_week)` |
| `monthly_averages` | `report_month` (VARCHAR, `"YYYY-MM"`) | `(patient_id, report_month)` |
| `yearly_averages` | `report_year` (INTEGER) | `(patient_id, report_year)` |

All four tables share an identical set of metric columns: `total_windows_analyzed`, `total_steps`, `total_calories`, `total_distance_m`, `avg_max_gyr_ms`, `avg_val_gyr_hs`, `avg_swing_time`, `avg_stance_time`, `avg_stride_cv`, `avg_cadence`, `anomaly_count`.

**Cadence computation**: `avg_cadence = total_steps / (total_windows * 0.5)` (steps per minute, assuming each window represents 30 seconds = 0.5 minutes of walking).

#### `cohort_benchmark_data`
| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `BIGINT` | PRIMARY KEY, auto-increment |
| `age_center` | `INTEGER` | UNIQUE (with metric), indexed |
| `metric` | `VARCHAR` | UNIQUE (with age_center), indexed |
| `cohort_vals` | `FLOAT[]` | DEFAULT `'{}'` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | DEFAULT `now()` |

Stores pre-computed arrays of peer metric values grouped by patient age, used for percentile-based benchmarking with an age band of &plusmn;5 years.

### 5.6 Alembic Migration Strategy

The schema is managed through 14 sequential Alembic migrations. Key migrations include:

- **`44268ef266c0`**: Initial schema (users, caregivers, patients, window_reports, anomaly_logs, daily_averages).
- **`157ad1d052bb`**: Introduced declarative range partitioning. Renamed original tables, recreated them as partitioned, migrated existing data, and seeded initial monthly partitions. This migration is the most complex, involving raw SQL DDL for partition creation.
- **`242b98f29d3b`**: Migrated `users.email` from `VARCHAR` to `CITEXT` with duplicate detection and lowercase normalization.
- **`ed0ae94d0ecb`**: Added `avg_cadence` to all aggregation tables and created the `cohort_benchmark_data` table.
- **`a1b2c3d4e5f6`**: Renamed the `caretakers` table to `caregivers` and updated the `users.role` CHECK constraint value from `'caretaker'` to `'caregiver'`. All existing role values in the `users` table were migrated via an `UPDATE` statement.

Alembic runs automatically during container startup via `docker-entrypoint.sh` (unless `SKIP_MIGRATIONS=true`). In CI, migrations run against a dedicated test database to validate schema compatibility before merge.

---

## 6. API Design

### 6.1 Router Modules

The REST API is organized under the `/api/v1` prefix with five router modules:

| Module | Prefix | Primary Role |
|--------|--------|-------------|
| `auth` | `/api/v1/auth` | Registration, login, password reset |
| `profiles` | `/api/v1/profiles` | Profile CRUD for both roles |
| `patients` | `/api/v1/patients` | Patient self-service (metrics, reports, benchmarks) |
| `caregiver_patients` | `/api/v1/caregivers/patients` | Caregiver management of linked patients |
| `mqtt_credential` | `/api/v1/mqtt-credential` | MQTT broker credentials for device pairing |

Additionally, a health check endpoint at `GET /health` returns `{"status": "healthy"}` without authentication.

### 6.2 Complete Endpoint Reference

#### Authentication (`/api/v1/auth`)

| Method | Path | Auth | Request | Response | Status |
|--------|------|------|---------|----------|--------|
| POST | `/register` | None | `RegisterRequest` | `Token` | 201 |
| POST | `/login` | OAuth2 Form | `OAuth2PasswordRequestForm` | `Token` | 200 |
| POST | `/forgot-password` | None | `ForgotPasswordRequest` | `ForgotPasswordResponse` | 202 |
| POST | `/reset-password` | None | `ResetPasswordRequest` | `{"message": str}` | 200 |

Registration performs identity-only provisioning (creates a `User` record; profile creation is a separate step). Password reset uses a two-step flow: a 6-digit OTP is generated, HMAC-SHA256 hashed, embedded in a short-lived JWT (5-minute expiry), and emailed via the Resend API.

#### Profiles (`/api/v1/profiles`)

| Method | Path | Auth | Request | Response | Status |
|--------|------|------|---------|----------|--------|
| GET | `/me/status` | JWT | — | `ProfileStatus` | 200 |
| POST | `/me` | JWT | `CaregiverProfile` or `PatientProfile` | Profile object | 201 |
| PUT | `/me` | JWT | `CaregiverProfile` or `PatientProfile` | Profile object | 200 |
| GET | `/me` | JWT | — | Profile object | 200 |

Profile creation is role-polymorphic: the request body schema is selected based on the JWT's `role` claim.

#### Patient Self-Service (`/api/v1/patients`)

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/me/status` | JWT (patient) | `PatientCaregiverStatus` |
| POST | `/me/sessions/stop` | JWT (patient) | `{"status": "success"}` |
| GET | `/me/windowReport` | JWT (patient) | Latest `WindowReport` |
| GET | `/me/dailyAverage` | JWT (patient) | Last 7 `DailyAverageSchema` |
| GET | `/me/weeklyAverage` | JWT (patient) | Last 4 `WeeklyAverageSchema` |
| GET | `/me/monthlyAverage` | JWT (patient) | Last 6 `MonthlyAverageSchema` |
| GET | `/me/yearlyAverage` | JWT (patient) | Last 4 `YearlyAverageSchema` |
| GET | `/me/anomalyLog` | JWT (patient) | All `AnomalyLogSchema` |
| GET | `/me/dailyAverage/byDate` | JWT (patient) | `DailyAverageSchema` or null |
| GET | `/me/fallAnalysis` | JWT (patient) | `FallAnalysisResponseSchema` |
| GET | `/me/benchmark` | JWT (patient) | `AllMetricsBenchmarkSchema` |
| GET | `/{telemetry_token}` | None | Patient ID (integer) |

The `POST /me/sessions/stop` endpoint triggers on-demand aggregation for the current date using `BackgroundTasks`, enabling the patient to see updated daily metrics immediately after ending a walking session.

The fall analysis endpoint accepts a `date_str` query parameter and returns comparison pairs (previous vs. latest) for weekly, monthly, and yearly aggregation periods relative to that date.

The benchmark endpoint computes the patient's percentile rank within their age cohort (&plusmn;5 years) across 7 metrics, with labels ("above_peers", "with_peers", "below_peers") based on &plusmn;1 standard deviation bounds.

#### Caregiver Patient Management (`/api/v1/caregivers/patients`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/` | JWT (caregiver) | Link patient by username |
| DELETE | `/{username}` | JWT (caregiver) | Unlink patient (SET NULL) |
| GET | `/` | JWT (caregiver) | List all linked patients |
| GET | `/{username}` | JWT (caregiver) | Patient profile |
| GET | `/dailyAverage/{username}` | JWT (caregiver) | Patient's daily averages |
| GET | `/weeklyAverage/{username}` | JWT (caregiver) | Patient's weekly averages |
| GET | `/monthlyAverage/{username}` | JWT (caregiver) | Patient's monthly averages |
| GET | `/yearlyAverage/{username}` | JWT (caregiver) | Patient's yearly averages |
| GET | `/anomalyLog/{username}` | JWT (caregiver) | Patient's anomaly logs |
| GET | `/dailyAverage/byDate/{username}` | JWT (caregiver) | Daily average by date |
| GET | `/fallAnalysis/{username}` | JWT (caregiver) | Fall analysis comparison |
| GET | `/benchmark/{username}` | JWT (caregiver) | Patient benchmark |

All caregiver endpoints enforce authorization: the requesting caregiver must have an active link (`patient.caregiver_id == caregiver.id`) to the target patient.

#### MQTT Credentials (`/api/v1/mqtt-credential`)

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/me` | JWT (patient) | `MqttCredential` |

Returns the HiveMQ WebSocket Secure URL, publish credentials, and the patient's `telemetry_token` for device configuration.

### 6.3 JWT Authentication & RBAC

Authentication uses the OAuth2 Password Bearer flow:

- **Token generation**: JWT signed with HS256 using `SECRET_KEY`. Claims include `sub` (user ID), `role`, `exp` (expiration), and `iat` (issued at).
- **Password hashing**: bcrypt with 12 rounds.
- **Token validation**: The `get_current_user` dependency decodes the JWT, extracts the user ID and role, and queries the database for the `User` object. Invalid or expired tokens return HTTP 401.
- **Role enforcement**: The `require_role(*allowed_roles)` dependency factory returns a FastAPI dependency that checks `current_user.role` against the allowed set, returning HTTP 403 if unauthorized.

Two roles exist: `patient` and `caregiver`. There is no admin role or superuser concept.

### 6.4 Rate Limiting

No rate limiting or ingestion throttling is implemented at the API layer. The system relies on Kafka's buffering capacity and the ML worker's processing rate to regulate throughput.

---

## 7. Performance & Scalability Characteristics

### 7.1 Connection Pool Configuration

The FastAPI async engine (`app/core/database.py`) is configured with:

```python
create_async_engine(
    url,
    pool_pre_ping=True,      # Validate connections before checkout
    pool_size=20,             # Base pool: 20 persistent connections
    max_overflow=30,          # Burst capacity: 30 additional connections
    pool_timeout=30,          # Max wait for available connection: 30s
    pool_recycle=1800,        # Recycle idle connections every 30 minutes
)
```

With 4 Uvicorn workers, the theoretical maximum is **200 concurrent database connections** (50 per worker &times; 4 workers). The `pool_recycle=1800` prevents stale connections when operating behind managed database proxies (e.g., AWS RDS Proxy).

The batch aggregator uses a separate synchronous engine with `pool_size=5, max_overflow=10` — a smaller pool appropriate for its single-threaded scheduled workload.

### 7.2 Ingestion Throughput

At 100 Hz per patient:
- **Raw samples**: 100 &times; 86,400 = **8,640,000 samples/patient/day**
- **Analysis windows**: 86,400 / 30 = **2,880 windows/patient/day**
- **Database writes**: 2,880 `WindowReport` inserts/patient/day (only for monitoring-phase windows; calibration windows are not persisted as full monitoring records)

For 35 concurrent patients (a plausible pilot deployment), this yields approximately 100,800 window reports per day, or roughly 3 million per month — well within the capacity of a single monthly partition.

The "100M data points daily" claim from the original README would require approximately 12 concurrent patients streaming continuously (8.64M &times; 12 &asymp; 100M), which is achievable given the async architecture, though the single ML worker instance would need to process windows fast enough to keep pace.

### 7.3 Partition Pruning Benefits

Time-range queries (e.g., "last 7 days of daily averages") benefit from PostgreSQL's partition pruning: the query planner eliminates partitions outside the requested time range at planning time, reducing I/O to only the relevant monthly partition(s). This is particularly impactful for the `window_reports` table, which accumulates the highest volume of rows.

### 7.4 Identified Bottlenecks

1. **Single ML worker instance**: All patients are processed by a single consumer in one Kafka consumer group. CPU-bound signal processing (Butterworth filtering, peak detection, LOF prediction) runs in `asyncio.to_thread`, which is limited by the thread pool size and GIL contention.
2. **Synchronous database writes in ML worker**: Although the ML worker uses async Kafka consumption, database writes are synchronous (`sqlalchemy.orm.Session`) wrapped in `asyncio.to_thread`, adding overhead.
3. **In-memory model state**: The `GaitSystem` per-patient state (including the fitted LOF model) is not shared across worker replicas, preventing horizontal scaling without a shared state store.
4. **No connection pooling in ML worker**: The ML worker's `create_engine(DATABASE_URL)` uses SQLAlchemy's default pool settings rather than the tuned pool configuration of the API service.

---

## 8. CI/CD Pipeline

### 8.1 Workflow Configuration

The CI/CD pipeline is defined in `.github/workflows/ci_cd.yml` and triggers on:
- Push to `main`
- Pull request targeting `main`
- Manual dispatch (`workflow_dispatch`)

Concurrent runs on the same branch are automatically cancelled (`concurrency.cancel-in-progress: true`).

### 8.2 CI Job: Lint & Test

**Runner**: `ubuntu-latest`, 10-minute timeout.

**Service containers**:
- PostgreSQL 16-alpine (port 5433, database `gait_test`)
- Redis 7-alpine (port 6379)

**Steps**:

1. **Checkout** repository (actions/checkout@v4)
2. **Setup Python 3.11** with pip cache (actions/setup-python@v5)
3. **Install dependencies**: `pip install -r requirements.txt -r requirements-dev.txt`
4. **Ruff lint**: `ruff check . --output-format=github` — enforces code style and catches common errors
5. **Ruff format check**: `ruff format --check .` — verifies consistent formatting without modifying files
6. **Alembic migrations**: `alembic upgrade head` against the test database (`ALEMBIC_TARGET_ENV=test`) — validates that all migrations apply cleanly
7. **Pytest**: `pytest -v --tb=short --strict-markers -x` — runs the test suite with fail-fast behavior

### 8.3 CD Job: Build & Publish

**Condition**: Runs only on push to `main` after CI passes.

**Permissions**: `contents: read`, `packages: write`.

**Steps**:

1. **Checkout** repository
2. **Setup Docker Buildx** (docker/setup-buildx-action@v3)
3. **Login to GHCR**: Authenticates with `ghcr.io` using `GITHUB_TOKEN`
4. **Extract metadata**: Generates Docker tags (commit SHA + `latest`) and OCI labels
5. **Build & push**: Multi-stage Docker build with GitHub Actions layer caching (`type=gha, mode=max`), pushed to `ghcr.io/<repository>`

The multi-stage Dockerfile produces a minimal runtime image (~200MB) based on `python:3.11-slim` with a non-root user (`appuser`, UID 1000).

---

## 9. Limitations & Future Work

### 9.1 Current Limitations

| Limitation | Impact | Root Cause |
|------------|--------|------------|
| **No horizontal ML worker scaling** | Processing throughput is bounded by a single consumer instance | In-memory per-patient model state cannot be shared across replicas |
| **No automatic partition provisioning** | Requires manual DDL or migration for each new month | Initial partitions are hardcoded for Mar-May 2026; no scheduled partition creation exists |
| **No model persistence** | Patient re-enters 10-window calibration after any worker restart | LOF model and scaler are held in memory only; no serialization to disk or object store |
| **No model retraining pipeline** | LOF hyperparameters are fixed at deployment time | No mechanism to evaluate model performance or tune parameters per-patient |
| **No API rate limiting** | Potential for abuse or accidental overload of the API layer | No middleware for request throttling |
| **Aggressive data retention** | `RETENTION_DAYS=0` deletes all raw `WindowReport` data after daily aggregation | Prevents retroactive reanalysis of raw window data |
| **Single-axis IMU utilization** | Only `gyro_z` is ingested and analyzed | The ESP32-C3 IMU provides 6-axis data, but the current pipeline processes only the z-axis gyroscope |

### 9.2 Hardcoded Assumptions

| Assumption | Value | Location |
|------------|-------|----------|
| Sampling frequency | 100 Hz | `workers/realtime_processor.py:9` |
| Butterworth cutoff | 6 Hz | `workers/realtime_processor.py:32` |
| Window size | 30 seconds | `workers/realtime_processor.py:10` |
| Calibration windows | 10 | `workers/realtime_processor.py:13` |
| LOF contamination | 0.01 | `workers/realtime_processor.py:280` |
| LOF max neighbors | 15 | `workers/realtime_processor.py:273` |
| Patient state TTL | 1800 seconds | `workers/ml_worker.py:54` |
| Age band for cohort | &plusmn;5 years | `workers/cohort_schedule.py:18`, `app/core/benchmark.py:10` |
| Timezone | UTC+7 (Bangkok) | `workers/ml_worker.py:18` |
| Stride length factor | 0.415 &times; height | `workers/realtime_processor.py:106` |
| MET values | 3.0 / 4.0 | `workers/realtime_processor.py:75,104` |

### 9.3 Recommended Future Work

1. **Automatic partition management**: Integrate `pg_partman` or implement a scheduled task to create monthly partitions in advance, preventing insert failures when the current month's partition does not exist.
2. **Model serialization**: Persist fitted LOF models and scalers using `joblib` or `pickle` to a shared object store (e.g., S3), enabling warm restarts and cross-replica state sharing.
3. **Horizontal consumer scaling**: With model persistence in place, multiple ML worker replicas can join the same Kafka consumer group, distributing patient load across partitions.
4. **Multi-axis feature extraction**: Incorporate accelerometer and additional gyroscope axes to capture a richer kinematic feature set (e.g., mediolateral sway, vertical displacement).
5. **Adaptive hyperparameter tuning**: Implement periodic evaluation of LOF model performance (e.g., via reconstruction error on held-out normal windows) and adjust `n_neighbors` and `contamination` per patient.
6. **Clinical validation study**: Conduct a prospective study comparing PERGA's anomaly alerts against gold-standard clinical gait assessments (e.g., Timed Up and Go, 6-Minute Walk Test) to establish sensitivity, specificity, and positive predictive value.
7. **API rate limiting**: Add middleware (e.g., `slowapi` or Redis-backed token bucket) to protect the API from excessive request volume.
8. **Configurable retention policy**: Allow per-deployment configuration of `RETENTION_DAYS` and support archival to cold storage before deletion.

---

## Appendix A: Dependency Manifest

| Package | Version Constraint | Purpose |
|---------|-------------------|---------|
| `fastapi` | &ge;0.111, <1 | Async web framework (ASGI) |
| `uvicorn[standard]` | &ge;0.29, <1 | ASGI server with libuv event loop |
| `sqlalchemy[mypy]` | &ge;2.0, <3 | ORM with async support and type stubs |
| `asyncpg` | &ge;0.29.0 | PostgreSQL async driver |
| `pydantic-settings` | &ge;2.2, <3 | Environment-based configuration |
| `pydantic[email]` | 2.10.1 | Request/response validation |
| `alembic` | &ge;1.13, <2 | Database schema migrations |
| `pyjwt` | &ge;2.10, <3 | JSON Web Token encoding/decoding |
| `bcrypt` | 4.0.1 | Password hashing (12 rounds) |
| `httpx` | &ge;0.27, <1 | Async HTTP client |
| `numpy` | &ge;1.26, <3 | Numerical array operations |
| `scipy` | &ge;1.11, <2 | Signal processing (Butterworth, peak detection) |
| `scikit-learn` | &ge;1.4, <2 | LOF anomaly detection, StandardScaler |
| `pandas` | &ge;2.2, <3 | Data manipulation |
| `aiokafka` | &ge;0.10, <1 | Async Kafka producer/consumer |
| `aiomqtt` | &ge;2.3, <3 | Async MQTT client |
| `apscheduler` | 3.10.4 | Cron-like scheduled task execution |
| `psycopg2-binary` | &ge;2.9, <3 | Synchronous PostgreSQL adapter (Alembic) |
| `greenlet` | &ge;2.0, <4 | Coroutine context switching |
| `python-multipart` | &ge;0.0.9, <1 | Form data parsing (OAuth2) |

## Appendix B: Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `SECRET_KEY` | Yes | JWT signing secret (generate via `openssl rand -hex 32`) |
| `HASH_ALGORITHM` | Yes | JWT algorithm (e.g., `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Yes | JWT token TTL in minutes |
| `RESEND_API_KEY` | Yes | Resend.com email API key |
| `MQTT_BROKER` | Yes | HiveMQ cluster hostname |
| `MQTT_BROKER_WSS` | Yes | HiveMQ WebSocket Secure URL |
| `MQTT_PORT` | No | MQTT port (default: 8883) |
| `MQTT_USERNAME` | Yes | MQTT subscriber username |
| `MQTT_PASSWORD` | Yes | MQTT subscriber password |
| `MQTT_USE_TLS` | No | Enable TLS (default: `true`) |
| `MQTT_QOS` | No | MQTT QoS level (default: 1) |
| `MQTT_PUB_USERNAME` | Yes | MQTT publisher credentials (served to devices) |
| `MQTT_PUB_PASSWORD` | Yes | MQTT publisher credentials (served to devices) |
| `KAFKA_BROKER_URL` | Yes | Kafka bootstrap server(s) |
| `KAFKA_TOPIC` | Yes | Kafka topic for raw telemetry |
| `KAFKA_GROUP_ID` | Yes | Kafka consumer group ID |
| `PATIENT_STATE_TTL_SECONDS` | No | Inactive patient eviction TTL (default: 1800) |
| `SKIP_MIGRATIONS` | No | Skip Alembic on container start (default: `false`) |

---

## License

This project is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for details.
