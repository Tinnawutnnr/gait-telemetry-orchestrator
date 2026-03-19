import numpy as np
from scipy import signal
from scipy.signal import find_peaks
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

# CONFIGURATION

FS = 100
WINDOW_SECONDS = 30
WINDOW_SAMPLES = WINDOW_SECONDS * FS

CALIBRATION_WINDOWS = 10
MAX_BUFFER_SIZE = 50

class GaitSystem:
    def __init__(self, user_weight_kg=70.0, user_height_cm=175.0):
        self.user_weight_kg = user_weight_kg
        self.user_height_cm = user_height_cm
        
        self.raw_buffer = []
        self.normal_windows = []  # Buffer for training model

        self.is_calibrated = False
        self.total_steps = 0
        self.total_calories = 0.0
        self.model = None
        self.scaler = StandardScaler()

        # Filter Settings
        b, a = signal.butter(4, 6 / (0.5 * FS), btype="low")
        self.filter_b = b
        self.filter_a = a

        # Mapping Index to Name for Contribution
        self.feature_names = ["max_gyr", "val_gyr", "swing_time", "stance_time", "stride_cv"]

    def process_stream_chunk(self, chunk_data):
        self.raw_buffer.extend(chunk_data)

        # 1. LIVE METRICS
        if len(self.raw_buffer) % FS == 0:
            self._update_live_metrics()

        # 2. DEEP ANALYSIS (Every 30s)
        if len(self.raw_buffer) >= WINDOW_SAMPLES:
            window_data = np.array(self.raw_buffer[:WINDOW_SAMPLES])
            self.raw_buffer = self.raw_buffer[WINDOW_SAMPLES:]  # Slide Window
            return self._analyze_window(window_data)

        return None

    def _update_live_metrics(self):
        # 1. Grab last 1 second (100 samples)
        recent_raw = np.array(self.raw_buffer[-FS:])

        recent_filt = signal.filtfilt(self.filter_b, self.filter_a, recent_raw)

        peaks, _ = find_peaks(recent_filt, height=2.0, distance=60)

        strides_detected = len(peaks)

        # 4. SAFETY CLAMP
        # Even if Bolt runs, he can't do more than 4 steps in 1 second.
        # If we see more, it's a "Data Burst" or Noise.
        if strides_detected > 2:
            strides_detected = 1  # Fallback to a realistic max

        new_steps = strides_detected * 2

        if new_steps > 0:
            self.total_steps += new_steps
            cadence = new_steps * 60
            mets = 4.0 if cadence >= 100 else 3.0
            kcal_per_sec = (mets * self.user_weight_kg * 1) / 3600
            self.total_calories += kcal_per_sec

    def _analyze_window(self, raw_signal):
        # 1. Preprocess
        sig_filt = signal.filtfilt(self.filter_b, self.filter_a, raw_signal)
        params = self._extract_params(sig_filt)

        if params is None:
            return {"type": "info", "msg": "No walking detected."}

        # EXTRACT ONLY THE 5 ML FEATURES FOR THE MODEL
        ml_features = [
            params["max_gyr_ms"],
            params["val_gyr_hs"],
            params["swing_time"],
            params["stance_time"],
            params["stride_cv"],
        ]

        # Must have at least 20 strides to train
        MIN_STRIDES_REQUIRED = 20
        is_reliable_for_training = params["n_strides"] >= MIN_STRIDES_REQUIRED

        window_strides = params["n_strides"]
        window_steps = window_strides * 2
        window_cadence = (window_steps / WINDOW_SECONDS) * 60

        mets = 4.0 if window_cadence >= 100 else 3.0
        window_kcal = (mets * self.user_weight_kg * 1) * (WINDOW_SECONDS / 3600)
        window_dist = window_steps * self.user_height_cm * 0.415 / 100
        # ------------------------------------------------------------------

        # --- PHASE 1: CALIBRATION ---
        if not self.is_calibrated:
            if is_reliable_for_training:
                self.normal_windows.append(ml_features)  # Append the 5 features, not the dictionary!

            progress = len(self.normal_windows)

            if progress >= CALIBRATION_WINDOWS:
                self._train_model()
                return {"type": "status", "status": "MONITORING", "msg": "Calibration Complete!"}

            report = {
                "type": "status",
                "status": "CALIBRATING",
                "progress": f"{progress}/{CALIBRATION_WINDOWS}",
                "params": params,
                "is_reliable": is_reliable_for_training,
                "metrics": {
                    "steps": window_steps,
                    "calories": f"{window_kcal:.2f}",
                    "distance_m": f"{window_dist:.2f}",
                },
            }
            return report

        # --- PHASE 2: MONITORING ---
        else:
            # Predict & Score using the 5 features
            input_vec = self.scaler.transform([ml_features])
            prediction = self.model.predict(input_vec)[0]
            score = self.model.decision_function(input_vec)[0]

            status = "NORMAL" if prediction == 1 else "ANOMALY_DETECTED"
            contribution_info = {}

            if status == "NORMAL":
                # Only update the dynamic baseline if the walk was steady/reliable
                if is_reliable_for_training:
                    self.normal_windows.append(ml_features)
                    if len(self.normal_windows) > MAX_BUFFER_SIZE:
                        self.normal_windows.pop(0)
                    self._train_model()
            else:
                z_scores = input_vec[0]
                max_dev_idx = np.argmax(np.abs(z_scores))
                feature_name = self.feature_names[max_dev_idx]
                z_val = z_scores[max_dev_idx]
                normal_mean = self.scaler.mean_[max_dev_idx]
                current_val = ml_features[max_dev_idx]

                contribution_info = {
                    "feature": feature_name,
                    "z_score": float(z_val),
                    "current_val": float(current_val),
                    "normal_ref": float(normal_mean),
                }

            # 3. Build Report
            report = {
                "type": "analysis",
                "gait_health": status,
                "anomaly_score": float(score),
                "is_reliable": is_reliable_for_training,
                "contribution": contribution_info,
                "params": params,
                "metrics": {
                    "steps": window_steps,
                    "calories": f"{window_kcal:.2f}",
                    "distance_m": f"{window_dist:.2f}",
                },
            }

            return report

    def _extract_params(self, sig):
        # 1. Basic Peak Detection
        max_val = np.max(sig)
        if max_val < 1.0:
            return None  # Signal too weak (sitting still)

        height_thresh = 0.25 * max_val
        min_dist = int(0.4 * FS)

        ms_peaks, _ = find_peaks(sig, distance=min_dist, height=height_thresh)
        hs_candidates, _ = find_peaks(-sig, distance=int(0.3 * FS))

        # 2. Match MS -> HS (Match Swing -> Impact)
        valid_ms = []
        valid_hs = []
        for ms in ms_peaks:
            future_hs = hs_candidates[(hs_candidates > ms) & (hs_candidates < ms + int(0.5 * FS))]
            if len(future_hs) > 0:
                valid_ms.append(ms)
                valid_hs.append(future_hs[0])

        if len(valid_hs) < 3:
            return None  # Too few steps (Noise/Stopped walking)

        ms_peaks = np.array(valid_ms)
        hs_peaks = np.array(valid_hs)

        # 3. Calculate Parameters from VALID STEPS ONLY
        max_gyr_values = sig[ms_peaks]  # Take only values from matched steps
        val_gyr_values = sig[hs_peaks]

        swing_times = []
        stance_times = []
        stride_times = []

        for i in range(len(hs_peaks) - 1):
            curr_hs = hs_peaks[i]
            next_hs = hs_peaks[i + 1]

            # Stride Time (HS -> HS)
            stride_t = (next_hs - curr_hs) / FS

            # Find TO (Toe-Off)
            # Logic V2: Find TO between HS and next MS
            next_ms_list = ms_peaks[(ms_peaks > curr_hs) & (ms_peaks < next_hs)]
            if len(next_ms_list) > 0:
                next_ms = next_ms_list[0]
                search_start = curr_hs + int(0.05 * FS)
                search_end = next_ms

                if search_start < search_end:
                    window = sig[search_start:search_end]
                    if len(window) > 0:
                        to_idx = search_start + np.argmin(window)

                        stance_t = (to_idx - curr_hs) / FS
                        swing_t = (next_hs - to_idx) / FS

                        # Physiological Filter (Filter out impossible values)
                        if 0.2 < stance_t < 2.0 and 0.2 < swing_t < 2.0:
                            stance_times.append(stance_t)
                            swing_times.append(swing_t)
                            stride_times.append(stride_t)

        # If no data left after filtering
        if len(stride_times) < 2:
            return None

        # 4. Final Aggregation
        return {
            "max_gyr_ms": float(np.mean(max_gyr_values)),
            "val_gyr_hs": float(np.mean(val_gyr_values)),
            "swing_time": float(np.mean(swing_times)),
            "stance_time": float(np.mean(stance_times)),
            "stride_cv": float((np.std(stride_times) / np.mean(stride_times)) * 100),
            # --- NEW RELIABILITY METRICS ---
            "stride_time": float(np.mean(stride_times)),
            "n_strides": len(stride_times),
        }

    def _train_model(self):
        if len(self.normal_windows) < 2:
            return  # Must have at least 2 to train

        X_train = np.array(self.normal_windows)
        n_samples = len(X_train)

        # Use n-1 formula (Golden Formula)
        # If there are 10 items -> k=9 (Best)
        # If there are 20 items -> k=15 (Max Cap)
        n_neighbors = min(15, n_samples - 1)
        if n_neighbors < 1:
            n_neighbors = 1

        self.scaler.fit(X_train)
        X_train_scaled = self.scaler.transform(X_train)

        self.model = LocalOutlierFactor(n_neighbors=n_neighbors, contamination=0.01, metric="manhattan", novelty=True)
        self.model.fit(X_train_scaled)

        self.is_calibrated = True
        print(f"Model Retrained: {n_samples} windows, k={n_neighbors}")
