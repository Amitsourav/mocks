from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.catalog import MockCatalogOut, MockTestOut, SubjectGroup
from app.schemas.user import CurrentUser
from app.services.streams import get_current_stream

router = APIRouter(prefix="/mock-tests", tags=["mock-tests"])


def _to_mock(r) -> MockTestOut:
    return MockTestOut(
        id=r["id"],
        scope=r["scope"],
        title=r["title"],
        description=r["description"],
        subject_code=r["subject_code"],
        subject_name=r["subject_name"],
        chapter_code=r["chapter_code"],
        chapter_name=r["chapter_name"],
        variant_code=r["variant_code"],
        duration_seconds=r["duration_seconds"],
        total_questions=r["total_questions"],
        difficulty=r["difficulty"],
        is_playable=r["linked_examination_id"] is not None,
    )


@router.get("", response_model=MockCatalogOut)
async def list_mock_tests(user: CurrentUser = Depends(get_current_user)) -> MockCatalogOut:
    """Mocks for the user's CURRENT exam stream (latest stream-log entry).

    Grouped into full mocks, category-shared sectionals, and per-subject
    (subject + chapter mocks) for browsing.
    """
    pool = get_pool()
    stream = await get_current_stream(pool, user.id)
    if stream is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_stream", "message": "No exam stream selected yet."},
        )

    rows = await pool.fetch(
        """
        select mt.id, mt.scope::text as scope, mt.title, mt.description,
               mt.duration_seconds, mt.total_questions, mt.difficulty,
               mt.linked_examination_id, mt.position,
               ss.code as subject_code, ss.name as subject_name,
               ss.position as subject_position, ss.catalog_exam_id as subject_exam_id,
               sc.code as chapter_code, sc.name as chapter_name,
               ev.code as variant_code
        from mock_tests mt
        left join syllabus_subjects ss on ss.id = mt.subject_id
        left join syllabus_chapters sc on sc.id = mt.chapter_id
        left join exam_variants ev on ev.id = mt.variant_id
        join catalog_exams ce on ce.code = $1
        left join mock_categories mc on mc.code = $2
        where mt.is_active = true
          and ( mt.catalog_exam_id = ce.id
                or (mt.catalog_exam_id is null and mt.category_id = mc.id) )
        order by ss.position nulls first, mt.position, mt.title
        """,
        stream["catalog_exam_code"], stream["category_code"],
    )

    full: list[MockTestOut] = []
    sectional: list[MockTestOut] = []            # category-shared subject mocks
    subject_map: dict[str, dict] = {}            # exam subject_code -> group

    for r in rows:
        mock = _to_mock(r)
        if r["scope"] == "full":
            full.append(mock)
        elif r["subject_code"] is None:
            sectional.append(mock)               # safety: subjectless sectional
        elif r["subject_exam_id"] is None:
            sectional.append(mock)               # subject owned by category => shared sectional
        else:
            grp = subject_map.setdefault(
                r["subject_code"],
                {"name": r["subject_name"], "position": r["subject_position"],
                 "subject_mocks": [], "chapter_mocks": []},
            )
            (grp["chapter_mocks"] if r["scope"] == "chapter" else grp["subject_mocks"]).append(mock)

    subjects = [
        SubjectGroup(
            subject_code=code,
            subject_name=g["name"],
            subject_mocks=g["subject_mocks"],
            chapter_mocks=g["chapter_mocks"],
        )
        for code, g in sorted(subject_map.items(), key=lambda kv: kv[1]["position"])
    ]

    return MockCatalogOut(
        category_code=stream["category_code"],
        catalog_exam_code=stream["catalog_exam_code"],
        catalog_exam_name=stream["catalog_exam_name"],
        full_mocks=full,
        sectional_mocks=sectional,
        subjects=subjects,
    )


@router.get("/{mock_id}", response_model=MockTestOut)
async def get_mock_test(mock_id: UUID, _: CurrentUser = Depends(get_current_user)) -> MockTestOut:
    r = await get_pool().fetchrow(
        """
        select mt.id, mt.scope::text as scope, mt.title, mt.description,
               mt.duration_seconds, mt.total_questions, mt.difficulty, mt.linked_examination_id,
               ss.code as subject_code, ss.name as subject_name,
               sc.code as chapter_code, sc.name as chapter_name,
               ev.code as variant_code
        from mock_tests mt
        left join syllabus_subjects ss on ss.id = mt.subject_id
        left join syllabus_chapters sc on sc.id = mt.chapter_id
        left join exam_variants ev on ev.id = mt.variant_id
        where mt.id = $1 and mt.is_active = true
        """,
        mock_id,
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mock test not found")
    return _to_mock(r)
