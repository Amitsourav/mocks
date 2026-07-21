from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AttemptSectionState(BaseModel):
    section_id: UUID
    code: str
    name: str
    position: int
    status: str
    started_at: datetime | None
    deadline_at: datetime | None
    submitted_at: datetime | None


class AttemptState(BaseModel):
    id: UUID
    examination_id: UUID
    status: str
    started_at: datetime | None
    submitted_at: datetime | None
    expires_at: datetime | None
    current_section_id: UUID | None
    sections: list[AttemptSectionState]


# ---- Question delivery (NO correct-answer fields) ----

class OptionOut(BaseModel):
    id: UUID
    label: str | None
    content_md: str
    position: int


class QuestionOut(BaseModel):
    id: UUID
    question_type: str
    content_md: str
    position: int
    marks: float
    stimulus_id: UUID | None
    options: list[OptionOut]


class StimulusOut(BaseModel):
    id: UUID
    content_md: str


class SectionDelivery(BaseModel):
    attempt_id: UUID
    section_id: UUID
    section_code: str
    section_name: str
    deadline_at: datetime | None      # None when the section has no time limit
    server_time: datetime
    remaining_seconds: int
    navigation_locked: bool
    allows_revisit: bool = True
    stimuli: list[StimulusOut]
    questions: list[QuestionOut]


# ---- Whole-paper delivery (linear flow) ----

class PaperOptionOut(BaseModel):
    id: UUID
    label: str | None
    content_md: str
    position: int


class PaperQuestionOut(BaseModel):
    id: UUID
    section_code: str
    section_name: str
    position: int
    question_type: str
    content_md: str
    stimulus_md: str | None
    options: list[PaperOptionOut]
    selected_option_id: UUID | None      # prior selection, for resume
    is_marked_for_review: bool


class PaperSectionOut(BaseModel):
    code: str
    name: str
    count: int


class PaperOut(BaseModel):
    attempt_id: UUID
    exam_code: str
    status: str
    expires_at: datetime | None
    server_time: datetime
    remaining_seconds: int
    total_questions: int
    sections: list[PaperSectionOut]
    questions: list[PaperQuestionOut]


class SubmitAck(BaseModel):
    status: str
    message: str


# ---- Answer submission ----

class AnswerIn(BaseModel):
    question_id: UUID
    selected_option_id: UUID | None = None
    selected_option_ids: list[UUID] | None = None
    numeric_answer: str | None = None
    text_answer: str | None = None
    is_marked_for_review: bool = False
    client_occurred_at: datetime | None = None


class AnswerAck(BaseModel):
    saved: bool
    attempt_id: UUID
    question_id: UUID
    answered_at: datetime


# ---- Event ingestion ----

class EventIn(BaseModel):
    event_type: str
    section_id: UUID | None = None
    question_id: UUID | None = None
    client_occurred_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class EventBatchIn(BaseModel):
    events: list[EventIn]


class EventBatchAck(BaseModel):
    accepted: int
