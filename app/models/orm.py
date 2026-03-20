"""SQLAlchemy 2.0 ORM models for the Gait Analysis System."""

from __future__ import annotations

from datetime import date, datetime
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    caretaker: Mapped[Caretaker | None] = relationship(back_populates="user")
    patient: Mapped[Patient | None] = relationship(back_populates="user")

    __table_args__ = (CheckConstraint("role IN ('caretaker', 'patient')", name="ck_users_role"),)

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"


class Caretaker(Base):
    __tablename__ = "caretakers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="caretaker")
    patients: Mapped[list[Patient]] = relationship(back_populates="caretaker")

    def __repr__(self) -> str:
        return f"<Caretaker id={self.id} name={self.first_name!r} {self.last_name!r}>"


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
        index=True,
    )
    caretaker_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("caretakers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    telemetry_token: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User | None] = relationship(back_populates="patient")
    caretaker: Mapped[Caretaker | None] = relationship(back_populates="patients")
    window_reports: Mapped[list[WindowReport]] = relationship(back_populates="patient")
    daily_averages: Mapped[list[DailyAverage]] = relationship(back_populates="patient")
    weekly_averages: Mapped[list[WeeklyAverage]] = relationship(back_populates="patient")
    monthly_averages: Mapped[list[MonthlyAverage]] = relationship(back_populates="patient")
    yearly_averages: Mapped[list[YearlyAverage]] = relationship(back_populates="patient")
    anomaly_logs: Mapped[list[AnomalyLog]] = relationship(back_populates="patient")

    def __repr__(self) -> str:
        return f"<Patient id={self.id} name={self.first_name!r} {self.last_name!r}>"


class WindowReport(Base):
    __tablename__ = "window_reports"

    window_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patients.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), primary_key=True, index=True
    )

    status: Mapped[str | None] = mapped_column(String)
    gait_health: Mapped[str | None] = mapped_column(String)

    anomaly_score: Mapped[float | None] = mapped_column(Float)

    max_gyr_ms: Mapped[float | None] = mapped_column(Float)
    val_gyr_hs: Mapped[float | None] = mapped_column(Float)
    swing_time: Mapped[float | None] = mapped_column(Float)
    stance_time: Mapped[float | None] = mapped_column(Float)
    stride_time: Mapped[float | None] = mapped_column(Float)
    stride_cv: Mapped[float | None] = mapped_column(Float)
    n_strides: Mapped[int | None] = mapped_column(Integer)

    steps: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)

    patient: Mapped[Patient] = relationship(back_populates="window_reports")
    anomaly_log: Mapped[AnomalyLog | None] = relationship(back_populates="window_report")

    __table_args__ = (
        CheckConstraint(
            "status IN ('CALIBRATING', 'MONITORING')",
            name="ck_window_reports_status",
        ),
        CheckConstraint(
            "gait_health IN ('NORMAL', 'ANOMALY_DETECTED')",
            name="ck_window_reports_gait_health",
        ),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    def __repr__(self) -> str:
        return f"<WindowReport id={self.window_report_id!r} patient={self.patient_id}>"


class DailyAverage(Base):
    __tablename__ = "daily_averages"

    daily_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patients.id"))
    report_date: Mapped[date] = mapped_column(Date)

    total_windows_analyzed: Mapped[int | None] = mapped_column(Integer)
    total_steps: Mapped[int | None] = mapped_column(Integer)
    total_calories: Mapped[float | None] = mapped_column(Float)
    total_distance_m: Mapped[float | None] = mapped_column(Float)

    avg_max_gyr_ms: Mapped[float | None] = mapped_column(Float)
    avg_val_gyr_hs: Mapped[float | None] = mapped_column(Float)
    avg_swing_time: Mapped[float | None] = mapped_column(Float)
    avg_stance_time: Mapped[float | None] = mapped_column(Float)
    avg_stride_cv: Mapped[float | None] = mapped_column(Float)

    anomaly_count: Mapped[int | None] = mapped_column(Integer)

    patient: Mapped[Patient] = relationship(back_populates="daily_averages")

    __table_args__ = (Index("ix_daily_averages_patient_date", "patient_id", "report_date", unique=True),)

    def __repr__(self) -> str:
        return f"<DailyAverage id={self.daily_report_id!r} date={self.report_date}>"


class WeeklyAverage(Base):
    __tablename__ = "weekly_averages"

    weekly_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patients.id"))

    report_week: Mapped[str] = mapped_column(String)

    total_windows_analyzed: Mapped[int | None] = mapped_column(Integer)
    total_steps: Mapped[int | None] = mapped_column(Integer)
    total_calories: Mapped[float | None] = mapped_column(Float)
    total_distance_m: Mapped[float | None] = mapped_column(Float)

    avg_max_gyr_ms: Mapped[float | None] = mapped_column(Float)
    avg_val_gyr_hs: Mapped[float | None] = mapped_column(Float)
    avg_swing_time: Mapped[float | None] = mapped_column(Float)
    avg_stance_time: Mapped[float | None] = mapped_column(Float)
    avg_stride_cv: Mapped[float | None] = mapped_column(Float)

    anomaly_count: Mapped[int | None] = mapped_column(Integer)

    patient: Mapped[Patient] = relationship(back_populates="weekly_averages")

    __table_args__ = (Index("ix_weekly_averages_patient_week", "patient_id", "report_week", unique=True),)

    def __repr__(self) -> str:
        return f"<WeeklyAverage id={self.weekly_report_id!r} week={self.report_week}>"


class MonthlyAverage(Base):
    __tablename__ = "monthly_averages"

    monthly_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patients.id"))
    report_month: Mapped[str] = mapped_column(String)

    total_windows_analyzed: Mapped[int | None] = mapped_column(Integer)
    total_steps: Mapped[int | None] = mapped_column(Integer)
    total_calories: Mapped[float | None] = mapped_column(Float)
    total_distance_m: Mapped[float | None] = mapped_column(Float)

    avg_max_gyr_ms: Mapped[float | None] = mapped_column(Float)
    avg_val_gyr_hs: Mapped[float | None] = mapped_column(Float)
    avg_swing_time: Mapped[float | None] = mapped_column(Float)
    avg_stance_time: Mapped[float | None] = mapped_column(Float)
    avg_stride_cv: Mapped[float | None] = mapped_column(Float)

    anomaly_count: Mapped[int | None] = mapped_column(Integer)

    patient: Mapped[Patient] = relationship(back_populates="monthly_averages")

    __table_args__ = (Index("ix_monthly_averages_patient_month", "patient_id", "report_month", unique=True),)

    def __repr__(self) -> str:
        return f"<MonthlyAverage id={self.monthly_report_id!r} month={self.report_month}>"


class YearlyAverage(Base):
    __tablename__ = "yearly_averages"

    yearly_report_id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patients.id"))
    report_year: Mapped[int] = mapped_column(Integer)

    total_windows_analyzed: Mapped[int | None] = mapped_column(Integer)
    total_steps: Mapped[int | None] = mapped_column(Integer)
    total_calories: Mapped[float | None] = mapped_column(Float)
    total_distance_m: Mapped[float | None] = mapped_column(Float)

    avg_max_gyr_ms: Mapped[float | None] = mapped_column(Float)
    avg_val_gyr_hs: Mapped[float | None] = mapped_column(Float)
    avg_swing_time: Mapped[float | None] = mapped_column(Float)
    avg_stance_time: Mapped[float | None] = mapped_column(Float)
    avg_stride_cv: Mapped[float | None] = mapped_column(Float)

    anomaly_count: Mapped[int | None] = mapped_column(Integer)

    patient: Mapped[Patient] = relationship(back_populates="yearly_averages")

    __table_args__ = (Index("ix_yearly_averages_patient_year", "patient_id", "report_year", unique=True),)

    def __repr__(self) -> str:
        return f"<YearlyAverage id={self.yearly_report_id!r} year={self.report_year}>"


class AnomalyLog(Base):
    __tablename__ = "anomaly_logs"

    anomaly_id: Mapped[str] = mapped_column(String, primary_key=True)
    window_id: Mapped[str] = mapped_column(
        String,
        index=True,
    )
    patient_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("patients.id", ondelete="RESTRICT"), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), primary_key=True, index=True
    )

    anomaly_score: Mapped[float | None] = mapped_column(Float)
    root_cause_feature: Mapped[str | None] = mapped_column(String)
    z_score: Mapped[float | None] = mapped_column(Float)
    current_val: Mapped[float | None] = mapped_column(Float)
    normal_ref: Mapped[float | None] = mapped_column(Float)

    patient: Mapped[Patient] = relationship(back_populates="anomaly_logs")
    window_report: Mapped[WindowReport] = relationship(back_populates="anomaly_log")

    __table_args__ = (
        ForeignKeyConstraint(
            ["window_id", "timestamp"],
            ["window_reports.window_report_id", "window_reports.timestamp"],
        ),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    def __repr__(self) -> str:
        return f"<AnomalyLog id={self.anomaly_id!r} score={self.anomaly_score}>"
