from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


class BaseAverageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: int
    total_windows_analyzed: int | None
    total_steps: int | None
    total_calories: float | None
    total_distance_m: float | None

    avg_max_gyr_ms: float | None
    avg_val_gyr_hs: float | None
    avg_swing_time: float | None
    avg_stance_time: float | None
    avg_stride_cv: float | None

    avg_cadence: float | None = None 

    anomaly_count: int | None


class DailyAverageSchema(BaseAverageSchema):
    daily_report_id: str
    report_date: date


class WeeklyAverageSchema(BaseAverageSchema):
    weekly_report_id: str
    report_week: str


class MonthlyAverageSchema(BaseAverageSchema):
    monthly_report_id: str
    report_month: str


class YearlyAverageSchema(BaseAverageSchema):
    yearly_report_id: str
    report_year: int


class AnomalyLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    anomaly_id: str
    window_id: str
    patient_id: int
    timestamp: datetime

    anomaly_score: float | None
    root_cause_feature: str | None
    z_score: float | None
    current_val: float | None
    normal_ref: float | None


T = TypeVar("T")


class ComparisonReportSchema(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)
    previous: T | None = None
    latest: T | None = None


class FallAnalysisResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    week: ComparisonReportSchema[WeeklyAverageSchema]
    month: ComparisonReportSchema[MonthlyAverageSchema]
    year: ComparisonReportSchema[YearlyAverageSchema]


class SingleMetricPeriod(BaseModel):
    patient_value: float | None
    cohort_avg: float | None
    cohort_size: int
    percentile: float | None
    lower_bound: float | None = None
    upper_bound: float | None = None
    label: str | None

class AllMetricsBenchmarkSchema(BaseModel):
    patient_age: int
    cohort_age_range: str
    metrics: dict[str, SingleMetricPeriod]
