from datetime import date, datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

class BaseAverageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: int
    total_windows_analyzed: Optional[int]
    total_steps: Optional[int]
    total_calories: Optional[float]
    total_distance_m: Optional[float]

    avg_max_gyr_ms: Optional[float]
    avg_val_gyr_hs: Optional[float]
    avg_swing_time: Optional[float]
    avg_stance_time: Optional[float]
    avg_stride_cv: Optional[float]

    anomaly_count: Optional[int]


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

    anomaly_score: Optional[float]
    root_cause_feature: Optional[str]
    z_score: Optional[float]
    current_val: Optional[float]
    normal_ref: Optional[float]


T = TypeVar("T")

class ComparisonReportSchema(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)
    previous: Optional[T] = None
    latest: Optional[T] = None


class FallAnalysisResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    week: ComparisonReportSchema[WeeklyAverageSchema]
    month: ComparisonReportSchema[MonthlyAverageSchema]
    year: ComparisonReportSchema[YearlyAverageSchema]
