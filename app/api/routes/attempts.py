from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.attempt import (
    AnswerAck,
    AnswerIn,
    AttemptSectionState,
    AttemptState,
    EventBatchAck,
    EventBatchIn,
    SectionDelivery,
)
from app.schemas.user import CurrentUser
from app.services import exam_engine
from app.services.exam_engine import EngineError

router = APIRouter(tags=["attempts"])


def _handle(exc: EngineError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message})


@router.post("/exams/{exam_id}/attempts", response_model=AttemptState, status_code=201)
async def start_attempt(exam_id: UUID, user: CurrentUser = Depends(get_current_user)) -> AttemptState:
    pool = get_pool()
    try:
        attempt_id = await exam_engine.start_attempt(pool, user.id, exam_id)
        state = await exam_engine.get_attempt_state(pool, user.id, attempt_id)
    except EngineError as exc:
        raise _handle(exc) from exc
    return _to_state(state)


@router.get("/attempts/{attempt_id}", response_model=AttemptState)
async def get_attempt(attempt_id: UUID, user: CurrentUser = Depends(get_current_user)) -> AttemptState:
    try:
        state = await exam_engine.get_attempt_state(get_pool(), user.id, attempt_id)
    except EngineError as exc:
        raise _handle(exc) from exc
    return _to_state(state)


@router.post("/attempts/{attempt_id}/sections/{section_id}/enter", response_model=SectionDelivery)
async def enter_section(
    attempt_id: UUID, section_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> SectionDelivery:
    try:
        data = await exam_engine.enter_section(get_pool(), user.id, attempt_id, section_id)
    except EngineError as exc:
        raise _handle(exc) from exc
    return SectionDelivery(**data)


@router.post("/attempts/{attempt_id}/answers", response_model=AnswerAck)
async def submit_answer(
    attempt_id: UUID, payload: AnswerIn, user: CurrentUser = Depends(get_current_user)
) -> AnswerAck:
    try:
        answered_at = await exam_engine.submit_answer(get_pool(), user.id, attempt_id, payload)
    except EngineError as exc:
        raise _handle(exc) from exc
    return AnswerAck(saved=True, attempt_id=attempt_id, question_id=payload.question_id, answered_at=answered_at)


@router.post("/attempts/{attempt_id}/events", response_model=EventBatchAck)
async def ingest_events(
    attempt_id: UUID, payload: EventBatchIn, user: CurrentUser = Depends(get_current_user)
) -> EventBatchAck:
    try:
        accepted = await exam_engine.ingest_events(get_pool(), user.id, attempt_id, payload.events)
    except EngineError as exc:
        raise _handle(exc) from exc
    return EventBatchAck(accepted=accepted)


@router.post("/attempts/{attempt_id}/sections/{section_id}/submit", status_code=204)
async def submit_section(
    attempt_id: UUID, section_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> None:
    try:
        await exam_engine.complete_section(get_pool(), user.id, attempt_id, section_id)
    except EngineError as exc:
        raise _handle(exc) from exc


@router.post("/attempts/{attempt_id}/submit", status_code=204)
async def submit_attempt(attempt_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    try:
        await exam_engine.submit_attempt(get_pool(), user.id, attempt_id)
    except EngineError as exc:
        raise _handle(exc) from exc


def _to_state(state: dict) -> AttemptState:
    a = state["attempt"]
    return AttemptState(
        id=a["id"],
        examination_id=a["examination_id"],
        status=a["status"],
        started_at=a["started_at"],
        submitted_at=a["submitted_at"],
        expires_at=a["expires_at"],
        current_section_id=a["current_section_id"],
        sections=[
            AttemptSectionState(
                section_id=s["section_id"],
                code=s["code"],
                name=s["name"],
                position=s["position"],
                status=s["status"],
                started_at=s["started_at"],
                deadline_at=s["deadline_at"],
                submitted_at=s["submitted_at"],
            )
            for s in state["sections"]
        ],
    )
