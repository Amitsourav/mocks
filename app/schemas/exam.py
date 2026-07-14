from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ExaminationSummary(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    language: str
    total_duration_seconds: int | None
    scoring_type: str


class SectionOut(BaseModel):
    id: UUID
    code: str
    name: str
    position: int
    time_limit_seconds: int | None
    question_count: int | None
    navigation_locked: bool


class ModuleOut(BaseModel):
    id: UUID
    code: str
    name: str
    position: int
    duration_seconds: int | None
    has_break_after: bool
    sections: list[SectionOut]


class ExaminationDetail(ExaminationSummary):
    # capability flags that drive the exam-specific UI
    has_single_choice: bool
    has_multi_select: bool
    has_numeric_entry: bool
    has_essay: bool
    has_negative_marking: bool
    penalizes_unanswered: bool
    has_sectional_time_limits: bool
    section_navigation_locked: bool
    allows_revisit_within_section: bool
    has_shared_stimulus: bool
    has_images: bool
    has_math: bool
    default_time_per_question_seconds: int | None
    scoring_config: dict
    modules: list[ModuleOut]
