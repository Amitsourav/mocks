from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.insights import AttemptInsightOut


# ---- Exam stream (profile switch) ----

class StreamOut(BaseModel):
    category_code: str
    catalog_exam_code: str
    catalog_exam_name: str | None = None
    variant_code: str | None = None
    target_country_code: str | None = None
    source: str
    selected_at: datetime


class StreamSwitchIn(BaseModel):
    catalog_exam_code: str
    variant_code: str | None = None
    target_country_code: str | None = None


# ---- Mock test catalog ----

class MockTestOut(BaseModel):
    id: UUID
    scope: str
    title: str
    description: str | None
    subject_code: str | None
    subject_name: str | None
    chapter_code: str | None
    chapter_name: str | None
    variant_code: str | None
    duration_seconds: int | None
    total_questions: int | None
    difficulty: str | None
    is_playable: bool  # true only when linked to real engine content (dMAT)


class SubjectGroup(BaseModel):
    subject_code: str
    subject_name: str
    subject_mocks: list[MockTestOut]
    chapter_mocks: list[MockTestOut]


class MockCatalogOut(BaseModel):
    category_code: str
    catalog_exam_code: str
    catalog_exam_name: str | None
    full_mocks: list[MockTestOut]
    sectional_mocks: list[MockTestOut]   # category-shared sectionals (e.g. govt English)
    subjects: list[SubjectGroup]


# ---- Dashboard ----

class DashboardSummary(BaseModel):
    total_attempts: int
    avg_score: float | None
    best_score: float | None
    avg_accuracy_pct: float | None
    latest_percentile: float | None
    first_accuracy_pct: float | None
    improvement_pct: float | None  # latest - first accuracy
    total_time_seconds: int


class AttemptListItem(BaseModel):
    id: UUID
    mock_title: str | None
    catalog_exam_code: str | None
    submitted_at: datetime | None
    duration_seconds: int | None
    total_questions: int | None
    correct: int | None
    score: float | None
    max_score: float | None
    percentile: float | None
    accuracy_pct: float | None


class SkillStat(BaseModel):
    skill_code: str | None
    skill_name: str
    attempts: int
    avg_accuracy_pct: float | None
    avg_time_ms: int | None


class SectionResultOut(BaseModel):
    section_name: str
    total: int | None
    correct: int | None
    wrong: int | None
    skipped: int | None
    score: float | None
    accuracy_pct: float | None
    avg_time_ms: int | None


class SkillResultOut(BaseModel):
    skill_code: str | None
    skill_name: str
    total: int | None
    correct: int | None
    accuracy_pct: float | None
    avg_time_ms: int | None


class QuestionResultOut(BaseModel):
    question_no: int
    section_name: str | None
    skill_code: str | None
    kc_code: str | None = None
    error_type: str | None = None
    is_correct: bool | None
    time_spent_ms: int | None
    difficulty: str | None
    marked_for_review: bool


class AttemptDetail(BaseModel):
    attempt: AttemptListItem
    sections: list[SectionResultOut]
    skills: list[SkillResultOut]
    questions: list[QuestionResultOut]
    insight: AttemptInsightOut | None = None
