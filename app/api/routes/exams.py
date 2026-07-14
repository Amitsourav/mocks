from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.exam import (
    ExaminationDetail,
    ExaminationSummary,
    ModuleOut,
    SectionOut,
)
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/exams", tags=["exams"])


@router.get("", response_model=list[ExaminationSummary])
async def list_exams(_: CurrentUser = Depends(get_current_user)) -> list[ExaminationSummary]:
    rows = await get_pool().fetch(
        """
        select id, code, name, description, language, total_duration_seconds, scoring_type
        from examinations
        where is_active = true
        order by name
        """
    )
    return [ExaminationSummary(**dict(r)) for r in rows]


@router.get("/{exam_id}", response_model=ExaminationDetail)
async def get_exam(
    exam_id: UUID,
    _: CurrentUser = Depends(get_current_user),
) -> ExaminationDetail:
    pool = get_pool()
    exam = await pool.fetchrow(
        """
        select id, code, name, description, language, total_duration_seconds, scoring_type,
               has_single_choice, has_multi_select, has_numeric_entry, has_essay,
               has_negative_marking, penalizes_unanswered, has_sectional_time_limits,
               section_navigation_locked, allows_revisit_within_section, has_shared_stimulus,
               has_images, has_math, default_time_per_question_seconds, scoring_config
        from examinations
        where id = $1 and is_active = true
        """,
        exam_id,
    )
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    module_rows = await pool.fetch(
        """
        select id, code, name, position, duration_seconds, has_break_after
        from exam_modules
        where examination_id = $1
        order by position
        """,
        exam_id,
    )
    section_rows = await pool.fetch(
        """
        select id, module_id, code, name, position, time_limit_seconds,
               question_count, navigation_locked
        from exam_sections
        where examination_id = $1
        order by position
        """,
        exam_id,
    )

    sections_by_module: dict[UUID, list[SectionOut]] = {}
    for s in section_rows:
        sections_by_module.setdefault(s["module_id"], []).append(
            SectionOut(
                id=s["id"],
                code=s["code"],
                name=s["name"],
                position=s["position"],
                time_limit_seconds=s["time_limit_seconds"],
                question_count=s["question_count"],
                navigation_locked=s["navigation_locked"],
            )
        )

    modules = [
        ModuleOut(
            id=m["id"],
            code=m["code"],
            name=m["name"],
            position=m["position"],
            duration_seconds=m["duration_seconds"],
            has_break_after=m["has_break_after"],
            sections=sections_by_module.get(m["id"], []),
        )
        for m in module_rows
    ]

    data = dict(exam)
    # asyncpg returns jsonb as str; normalize to dict for the response model.
    if isinstance(data.get("scoring_config"), str):
        data["scoring_config"] = json.loads(data["scoring_config"])
    data["modules"] = modules
    return ExaminationDetail(**data)
