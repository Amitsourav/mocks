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
            # Retire any attempt whose overall clock has run out, so a lapsed
            # attempt cannot hold the one-active-attempt index and lock the
            # student out of ever starting another.
            await conn.execute(
                """
                update attempts set status = 'expired'
                where user_id = $1 and examination_id = $2 and status = 'in_progress'
                  and expires_at is not null and now() > expires_at
                """,
                user_id, exam_id,
            )
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
        join exam_modules m on m.id = s.module_id
        where a.attempt_id = $1
        order by m.position, s.position
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


# --------------------------------------------------------------------------
# Section entry + secure delivery
# --------------------------------------------------------------------------

async def _load_attempt_for_write(conn: asyncpg.Connection, user_id: UUID, attempt_id: UUID) -> asyncpg.Record:
    attempt = await conn.fetchrow(
        "select id, user_id, examination_id, status, expires_at from attempts where id = $1",
        attempt_id,
    )
    if attempt is None or attempt["user_id"] != user_id:
        raise EngineError("attempt_not_found", "Attempt not found", 404)
    if attempt["status"] != "in_progress":
        raise EngineError("attempt_not_active", "Attempt is not in progress", 409)
    # Overall attempt clock: server-authoritative, same grace as section deadlines.
    # NOTE: do not flip the row to 'expired' here — this runs inside the caller's
    # transaction, so raising would roll the write back. `start_attempt` sweeps
    # stale attempts instead, which is also what frees the one-active index.
    if attempt["expires_at"] is not None:
        if _utcnow() > attempt["expires_at"] + timedelta(seconds=DEADLINE_GRACE_SECONDS):
            raise EngineError("attempt_expired", "Attempt time is over", 409)
    return attempt


async def enter_section(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID, section_id: UUID) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            attempt = await _load_attempt_for_write(conn, user_id, attempt_id)

            section = await conn.fetchrow(
                """
                select s.id, s.examination_id, s.code, s.name, s.time_limit_seconds,
                       s.navigation_locked, s.position as section_position,
                       m.position as module_position,
                       e.allows_revisit_within_section, e.section_navigation_locked
                from exam_sections s
                join exam_modules m on m.id = s.module_id
                join examinations e on e.id = s.examination_id
                where s.id = $1
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

            # Locked navigation: a section may only be opened once every earlier
            # section (module order, then section order) is finished. A section
            # whose deadline has passed counts as finished, so a student whose
            # time ran out is never trapped. Resuming an already-open section is
            # always allowed.
            if section["section_navigation_locked"] and astate["status"] == "not_started":
                unfinished = await conn.fetchval(
                    """
                    select count(*)
                    from attempt_sections a
                    join exam_sections s on s.id = a.section_id
                    join exam_modules m on m.id = s.module_id
                    where a.attempt_id = $1
                      and (m.position, s.position) < ($2, $3)
                      and a.status <> 'completed'
                      and (a.deadline_at is null or now() <= a.deadline_at)
                    """,
                    attempt_id, section["module_position"], section["section_position"],
                )
                if unfinished:
                    raise EngineError(
                        "section_out_of_order",
                        "Finish the previous section before starting this one.",
                        409,
                    )

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
        "allows_revisit": section["allows_revisit_within_section"],
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

            q = await conn.fetchrow(
                "select id, section_id, examination_id from questions where id = $1",
                payload.question_id,
            )
            if q is None or q["examination_id"] != attempt["examination_id"]:
                raise EngineError("question_not_found", "Question not found for this exam", 404)

            asec = await conn.fetchrow(
                "select status, deadline_at from attempt_sections where attempt_id = $1 and section_id = $2",
                attempt_id, q["section_id"],
            )
            if asec is None or asec["status"] == "not_started":
                raise EngineError("section_not_started", "Enter the section before answering", 409)
            if asec["status"] == "completed":
                raise EngineError("section_completed", "Section already completed", 409)
            if asec["deadline_at"] is not None:
                if _utcnow() > asec["deadline_at"] + timedelta(seconds=DEADLINE_GRACE_SECONDS):
                    raise EngineError("section_expired", "Section time is over; answer rejected", 409)

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
