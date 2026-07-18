"""Exam-stream helpers.

The user's CURRENT stream is the LATEST row in the append-only
`user_stream_selections` log — never an UPDATE. Switching appends a new row
(source='switch') and mirrors the current values onto `users.*` for convenience.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg


class StreamError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


async def get_current_stream(pool: asyncpg.Pool, user_id: UUID) -> dict | None:
    row = await pool.fetchrow(
        """
        select s.category_code, s.catalog_exam_code, s.variant_code,
               s.target_country_code, s.source, s.created_at as selected_at,
               ce.name as catalog_exam_name
        from user_stream_selections s
        join catalog_exams ce on ce.code = s.catalog_exam_code
        where s.user_id = $1
        order by s.created_at desc
        limit 1
        """,
        user_id,
    )
    return dict(row) if row else None


async def switch_stream(
    pool: asyncpg.Pool,
    user_id: UUID,
    catalog_exam_code: str,
    variant_code: str | None,
    target_country_code: str | None,
) -> dict:
    """Append a new stream selection (validated like the profile cascade)."""
    exam = await pool.fetchrow(
        """
        select ce.requires_country, ce.default_country_code, mc.code as category_code
        from catalog_exams ce
        join mock_categories mc on mc.id = ce.category_id
        where ce.code = $1 and ce.is_active = true
        """,
        catalog_exam_code,
    )
    if exam is None:
        raise StreamError("invalid_exam", "Unknown exam.")

    if variant_code is not None:
        ok = await pool.fetchval(
            """
            select 1 from exam_variants v
            join catalog_exams ce on ce.id = v.catalog_exam_id
            where v.code = $1 and ce.code = $2
            """,
            variant_code, catalog_exam_code,
        )
        if ok is None:
            raise StreamError("invalid_variant", "That variant does not belong to the selected exam.")

    country_code: str | None = None
    if exam["requires_country"]:
        country_code = (target_country_code or "").strip() or exam["default_country_code"]
        if not country_code:
            raise StreamError("country_required", "Select a target country for this exam.")
        if await pool.fetchval("select 1 from countries where code = $1", country_code) is None:
            raise StreamError("invalid_country", "Unknown country.")

    category_code = exam["category_code"]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                insert into user_stream_selections
                    (user_id, category_code, catalog_exam_code, variant_code, target_country_code, source)
                values ($1,$2,$3,$4,$5,'switch')
                """,
                user_id, category_code, catalog_exam_code, variant_code, country_code,
            )
            # mirror onto users for cheap reads (log stays authoritative + historical)
            await conn.execute(
                """
                update users set
                    mock_category_code = $2,
                    catalog_exam_code = $3,
                    target_country_code = $4
                where id = $1
                """,
                user_id, category_code, catalog_exam_code, country_code,
            )

    return await get_current_stream(pool, user_id)
