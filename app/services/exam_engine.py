"""Exam runtime engine.

Responsibilities:
- Attempt lifecycle (start / resume / submit) with one-active-attempt enforcement.
- Section entry with SERVER-AUTHORITATIVE deadlines (stored in
  `attempt_sections.deadline_at`, mirrored to Redis for fast checks).
- Secure section delivery: questions + options are returned WITHOUT the
  `is_correct` / answer-key fields — those never leave the server mid-test.
- Answer upsert with deadline enforcement.
- Append-only event ingestion (timing + integrity).

All timestamps are server time (`now()` in Postgres / `datetime.now(tz=utc)`),
never trusted from the client.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

from app.core.redis import get_redis

# Small grace for network latency when enforcing a section deadline.
DEADLINE_GRACE_SECONDS = 2

# Whitelist mirrors mock_db.event_type — reject anything else before it hits SQL.
VALID_EVENT_TYPES = {
    "section_entered", "section_completed", "question_viewed", "answer_submitted",
    "question_revisited", "marked_for_review", "focus_lost", "focus_regained",
    "fullscreen_exit", "fullscreen_enter",
}


class EngineError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _deadline_cache_set(attempt_id: UUID, section_id: UUID, deadline: datetime) -> None:
    try:
        r = get_redis()
        ttl = max(1, int((deadline - _utcnow()).total_seconds()) + 60)
        await r.set(f"attempt:{attempt_id}:sec:{section_id}:deadline", deadline.isoformat(), ex=ttl)
    except Exception:  # noqa: BLE001 - cache is best-effort; DB is authoritative
        pass


# --------------------------------------------------------------------------
# Attempt lifecycle
# --------------------------------------------------------------------------

async def start_attempt(pool: asyncpg.Pool, user_id: UUID, exam_id: UUID) -> UUID:
    exam = await pool.fetchrow(
        "select id, total_duration_seconds, is_active from examinations where id = $1",
        exam_id,
    )
    if exam is None or not exam["is_active"]:
        raise EngineError("exam_not_found", "Exam not found or inactive", 404)

    now = _utcnow()
    expires_at = now + timedelta(seconds=exam["total_duration_seconds"] or 0) if exam["total_duration_seconds"] else None

    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                attempt_id = await conn.fetchval(
                    """
                    insert into attempts (user_id, examination_id, status, started_at, expires_at)
                    values ($1, $2, 'in_progress', $3, $4)
                    returning id
                    """,
                    user_id, exam_id, now, expires_at,
                )
            except asyncpg.UniqueViolationError as exc:
                raise EngineError(
                    "attempt_already_active",
                    "You already have an in-progress attempt for this exam.",
                    409,
                ) from exc

            # Pre-create per-section state rows (not_started).
            await conn.execute(
                """
                insert into attempt_sections (attempt_id, section_id, status)
                select $1, s.id, 'not_started'
                from exam_sections s
                where s.examination_id = $2
                """,
                attempt_id, exam_id,
            )

            # Freeze the paper: sample `question_count` random published questions
            # per section, ordered linearly by (section position, random). This is
            # the exact set the student will see and submit against.
            await conn.execute(
                """
                insert into attempt_questions (attempt_id, question_id, section_id, position)
                select $1, x.id, x.section_id, row_number() over (order by x.module_pos, x.section_pos, x.rn)
                from (
                    select q.id, q.section_id, m.position as module_pos, s.position as section_pos,
                           s.question_count,
                           row_number() over (partition by q.section_id order by random()) as rn
                    from questions q
                    join exam_sections s on s.id = q.section_id
                    join exam_modules m on m.id = s.module_id
                    where q.examination_id = $2 and q.status = 'published'
                ) x
                where x.rn <= x.question_count
                """,
                attempt_id, exam_id,
            )
    return attempt_id


async def get_attempt_state(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID) -> dict:
    attempt = await pool.fetchrow(
        """
        select id, user_id, examination_id, status, started_at, submitted_at,
               expires_at, current_section_id
        from attempts where id = $1
        """,
        attempt_id,
    )
    if attempt is None or attempt["user_id"] != user_id:
        raise EngineError("attempt_not_found", "Attempt not found", 404)

    sections = await pool.fetch(
        """
        select s.id as section_id, s.code, s.name, s.position,
               a.status, a.started_at, a.deadline_at, a.submitted_at
        from attempt_sections a
        join exam_sections s on s.id = a.section_id
        where a.attempt_id = $1
        order by s.position
        """,
        attempt_id,
    )
    return {"attempt": dict(attempt), "sections": [dict(s) for s in sections]}


async def submit_attempt(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID) -> None:
    result = await pool.execute(
        """
        update attempts set status = 'submitted', submitted_at = now()
        where id = $1 and user_id = $2 and status = 'in_progress'
        """,
        attempt_id, user_id,
    )
    if result.endswith(" 0"):
        raise EngineError("attempt_not_submittable", "Attempt not found or not in progress", 409)


async def current_attempt(pool: asyncpg.Pool, user_id: UUID, exam_id: UUID) -> dict | None:
    """Resume helper: the user's in-progress attempt for this exam, or None."""
    row = await pool.fetchrow(
        """
        select id from attempts
        where user_id = $1 and examination_id = $2 and status = 'in_progress'
        limit 1
        """,
        user_id, exam_id,
    )
    if row is None:
        return None
    return await get_attempt_state(pool, user_id, row["id"])


# --------------------------------------------------------------------------
# Whole-paper delivery (linear flow) — one call serves all 76 questions
# --------------------------------------------------------------------------

async def get_paper(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID) -> dict:
    """Return the entire frozen paper for the attempt in linear order, WITHOUT any
    answer-key fields, plus the overall timer and any previously-saved selections."""
    attempt = await pool.fetchrow(
        """
        select a.id, a.user_id, a.examination_id, a.status, a.started_at,
               a.submitted_at, a.expires_at, e.code as exam_code
        from attempts a
        join examinations e on e.id = a.examination_id
        where a.id = $1
        """,
        attempt_id,
    )
    if attempt is None or attempt["user_id"] != user_id:
        raise EngineError("attempt_not_found", "Attempt not found", 404)

    # Frozen questions (NO is_correct / numeric_answer_key / explanation).
    questions = await pool.fetch(
        """
        select aq.position, q.id, q.question_type, q.content_md, q.stimulus_id,
               s.code as section_code, s.name as section_name,
               st.content_md as stimulus_md
        from attempt_questions aq
        join questions q on q.id = aq.question_id
        join exam_sections s on s.id = aq.section_id
        left join stimuli st on st.id = q.stimulus_id
        where aq.attempt_id = $1
        order by aq.position
        """,
        attempt_id,
    )
    q_ids = [q["id"] for q in questions]

    options = await pool.fetch(
        """
        select id, question_id, label, content_md, position
        from question_options
        where question_id = any($1::uuid[])
        order by question_id, position
        """,
        q_ids,
    )
    options_by_q: dict[UUID, list[dict]] = {}
    for o in options:
        options_by_q.setdefault(o["question_id"], []).append(
            {"id": o["id"], "label": o["label"], "content_md": o["content_md"], "position": o["position"]}
        )

    # Previously-saved selections (for resume).
    saved = await pool.fetch(
        "select question_id, selected_option_id, is_marked_for_review "
        "from student_answers where attempt_id = $1",
        attempt_id,
    )
    saved_by_q = {s["question_id"]: s for s in saved}

    # Section labels/counts.
    sections = await pool.fetch(
        """
        select s.code, s.name, count(aq.id) as count
        from attempt_questions aq
        join exam_sections s on s.id = aq.section_id
        join exam_modules m on m.id = s.module_id
        where aq.attempt_id = $1
        group by s.code, s.name, m.position, s.position
        order by m.position, s.position
        """,
        attempt_id,
    )

    expires_at = attempt["expires_at"]
    now = _utcnow()
    remaining = int((expires_at - now).total_seconds()) if expires_at else 0

    return {
        "attempt_id": attempt_id,
        "exam_code": attempt["exam_code"],
        "status": attempt["status"],
        "expires_at": expires_at,
        "server_time": now,
        "remaining_seconds": max(0, remaining),
        "total_questions": len(questions),
        "sections": [{"code": s["code"], "name": s["name"], "count": int(s["count"])} for s in sections],
        "questions": [
            {
                "id": q["id"],
                "section_code": q["section_code"],
                "section_name": q["section_name"],
                "position": q["position"],
                "question_type": q["question_type"],
                "content_md": q["content_md"],
                "stimulus_md": q["stimulus_md"],
                "options": options_by_q.get(q["id"], []),
                "selected_option_id": (saved_by_q.get(q["id"]) or {}).get("selected_option_id"),
                "is_marked_for_review": bool((saved_by_q.get(q["id"]) or {}).get("is_marked_for_review")),
            }
            for q in questions
        ],
    }


# --------------------------------------------------------------------------
# Section entry + secure delivery
# --------------------------------------------------------------------------

async def _load_attempt_for_write(conn: asyncpg.Connection, user_id: UUID, attempt_id: UUID) -> asyncpg.Record:
    attempt = await conn.fetchrow(
        "select id, user_id, examination_id, status from attempts where id = $1",
        attempt_id,
    )
    if attempt is None or attempt["user_id"] != user_id:
        raise EngineError("attempt_not_found", "Attempt not found", 404)
    if attempt["status"] != "in_progress":
        raise EngineError("attempt_not_active", "Attempt is not in progress", 409)
    return attempt


async def enter_section(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID, section_id: UUID) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            attempt = await _load_attempt_for_write(conn, user_id, attempt_id)

            section = await conn.fetchrow(
                """
                select id, examination_id, code, name, time_limit_seconds,
                       navigation_locked
                from exam_sections where id = $1
                """,
                section_id,
            )
            if section is None or section["examination_id"] != attempt["examination_id"]:
                raise EngineError("section_not_found", "Section not found for this exam", 404)

            astate = await conn.fetchrow(
                "select status, started_at, deadline_at from attempt_sections where attempt_id = $1 and section_id = $2",
                attempt_id, section_id,
            )
            if astate is None:
                raise EngineError("section_not_in_attempt", "Section not part of this attempt", 400)
            if astate["status"] == "completed":
                raise EngineError("section_completed", "Section already completed", 409)

            now = _utcnow()
            if astate["status"] == "not_started":
                limit = section["time_limit_seconds"] or 0
                deadline = now + timedelta(seconds=limit) if limit else None
                await conn.execute(
                    """
                    update attempt_sections
                    set status = 'in_progress', started_at = $3, deadline_at = $4
                    where attempt_id = $1 and section_id = $2
                    """,
                    attempt_id, section_id, now, deadline,
                )
                await conn.execute(
                    "update attempts set current_section_id = $2 where id = $1",
                    attempt_id, section_id,
                )
            else:
                # resume — keep existing deadline
                deadline = astate["deadline_at"]

            await conn.execute(
                """
                insert into question_events (attempt_id, section_id, event_type, occurred_at)
                values ($1, $2, 'section_entered', now())
                """,
                attempt_id, section_id,
            )

            # Stimuli (shared passages) for the section.
            stimuli = await conn.fetch(
                """
                select id, content_md from stimuli
                where section_id = $1 and status = 'published'
                order by created_at
                """,
                section_id,
            )
            # Questions — NO is_correct / numeric_answer_key fields.
            questions = await conn.fetch(
                """
                select id, question_type, content_md, position, marks, stimulus_id
                from questions
                where section_id = $1 and status = 'published'
                order by position
                """,
                section_id,
            )
            q_ids = [q["id"] for q in questions]
            options = await conn.fetch(
                """
                select id, question_id, label, content_md, position
                from question_options
                where question_id = any($1::uuid[])
                order by position
                """,
                q_ids,
            )

    if deadline is not None:
        await _deadline_cache_set(attempt_id, section_id, deadline)

    options_by_q: dict[UUID, list[dict]] = {}
    for o in options:
        options_by_q.setdefault(o["question_id"], []).append(
            {"id": o["id"], "label": o["label"], "content_md": o["content_md"], "position": o["position"]}
        )

    remaining = int((deadline - _utcnow()).total_seconds()) if deadline else 0
    return {
        "attempt_id": attempt_id,
        "section_id": section_id,
        "section_code": section["code"],
        "section_name": section["name"],
        "deadline_at": deadline,
        "server_time": _utcnow(),
        "remaining_seconds": max(0, remaining),
        "navigation_locked": section["navigation_locked"],
        "stimuli": [{"id": s["id"], "content_md": s["content_md"]} for s in stimuli],
        "questions": [
            {
                "id": q["id"],
                "question_type": q["question_type"],
                "content_md": q["content_md"],
                "position": q["position"],
                "marks": float(q["marks"]),
                "stimulus_id": q["stimulus_id"],
                "options": options_by_q.get(q["id"], []),
            }
            for q in questions
        ],
    }


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------

async def submit_answer(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID, payload) -> datetime:
    async with pool.acquire() as conn:
        async with conn.transaction():
            attempt = await _load_attempt_for_write(conn, user_id, attempt_id)

            # Linear flow: the question must belong to THIS attempt's frozen paper.
            q = await conn.fetchrow(
                """
                select aq.section_id
                from attempt_questions aq
                where aq.attempt_id = $1 and aq.question_id = $2
                """,
                attempt_id, payload.question_id,
            )
            if q is None:
                raise EngineError("question_not_in_paper", "Question is not part of this attempt", 404)

            # Overall exam timer (attempt-level), with a small grace for latency.
            expires_at = await conn.fetchval("select expires_at from attempts where id = $1", attempt_id)
            if expires_at is not None and _utcnow() > expires_at + timedelta(seconds=DEADLINE_GRACE_SECONDS):
                raise EngineError("attempt_expired", "Time is over; answer rejected", 409)

            answered_at = _utcnow()
            await conn.execute(
                """
                insert into student_answers
                    (attempt_id, question_id, user_id, selected_option_id, selected_option_ids,
                     numeric_answer, text_answer, is_marked_for_review, answered_at)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                on conflict (attempt_id, question_id) do update set
                    selected_option_id = excluded.selected_option_id,
                    selected_option_ids = excluded.selected_option_ids,
                    numeric_answer = excluded.numeric_answer,
                    text_answer = excluded.text_answer,
                    is_marked_for_review = excluded.is_marked_for_review,
                    answered_at = excluded.answered_at
                """,
                attempt_id, payload.question_id, user_id,
                payload.selected_option_id, payload.selected_option_ids,
                payload.numeric_answer, payload.text_answer,
                payload.is_marked_for_review, answered_at,
            )
            await conn.execute(
                """
                insert into question_events
                    (attempt_id, section_id, question_id, event_type, occurred_at, client_occurred_at)
                values ($1,$2,$3,'answer_submitted', now(), $4)
                """,
                attempt_id, q["section_id"], payload.question_id, payload.client_occurred_at,
            )
    return answered_at


async def complete_section(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID, section_id: UUID) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _load_attempt_for_write(conn, user_id, attempt_id)
            result = await conn.execute(
                """
                update attempt_sections set status = 'completed', submitted_at = now()
                where attempt_id = $1 and section_id = $2 and status = 'in_progress'
                """,
                attempt_id, section_id,
            )
            if result.endswith(" 0"):
                raise EngineError("section_not_in_progress", "Section not in progress", 409)
            await conn.execute(
                """
                insert into question_events (attempt_id, section_id, event_type, occurred_at)
                values ($1, $2, 'section_completed', now())
                """,
                attempt_id, section_id,
            )


# --------------------------------------------------------------------------
# Event ingestion (timing + integrity)
# --------------------------------------------------------------------------

async def ingest_events(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID, events: list) -> int:
    # Ownership check (one round-trip) before bulk insert.
    owner = await pool.fetchval("select user_id from attempts where id = $1", attempt_id)
    if owner is None or owner != user_id:
        raise EngineError("attempt_not_found", "Attempt not found", 404)

    rows = []
    for e in events:
        if e.event_type not in VALID_EVENT_TYPES:
            raise EngineError("invalid_event_type", f"Unknown event_type: {e.event_type}", 400)
        rows.append((attempt_id, e.section_id, e.question_id, e.event_type, e.client_occurred_at, e.metadata))

    if not rows:
        return 0

    await pool.executemany(
        """
        insert into question_events
            (attempt_id, section_id, question_id, event_type, occurred_at, client_occurred_at, metadata)
        values ($1, $2, $3, $4::mock_db.event_type, now(), $5, $6::jsonb)
        """,
        [(r[0], r[1], r[2], r[3], r[4], json.dumps(r[5])) for r in rows],
    )
    return len(rows)
