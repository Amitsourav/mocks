from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StudentInsightOut(BaseModel):
    """The headline 'story' — evolving student profile."""
    stream_catalog_exam_code: str | None
    summary: str | None
    persistent_strengths: list[str]
    persistent_gaps: list[str]
    predicted_score: float | None
    predicted_band_low: float | None
    predicted_band_high: float | None
    study_plan: list[dict]
    generated_by: str
    created_at: datetime


class ConceptMasteryOut(BaseModel):
    kc_code: str
    kc_name: str
    subject_name: str | None
    p_mastery: float | None
    retention_probability: float | None
    gap_priority: float | None
    careless_rate: float | None
    conceptual_gap_score: float | None
    n_opportunities: int


class StrategyOut(BaseModel):
    """Behavioral / test-strategy view aggregated across attempts."""
    attempts: int
    error_distribution: dict[str, int]     # correct/careless/conceptual/guess/unattempted
    careless_share_pct: float | None       # of all wrong answers
    avg_guess_rate: float | None
    total_negative_marking_loss: float | None
    avg_calibration_gap: float | None
    dominant_archetype: str | None
    pacing_note: str | None


class AttemptInsightOut(BaseModel):
    headline: str | None
    goal: str | None
    current_status: str | None
    gap_diagnosis: str | None
    calibration_note: str | None
    next_actions: list[str]
    recommended_method: str | None
    behavior_archetype: str | None
    pacing_note: str | None
    negative_marking_loss: float | None
    guess_rate: float | None
    calibration_gap: float | None
    generated_by: str
