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
    """Append a new stream selection (validated like the profile cascade).

    Two round-trips only: (1) one query validates exam + variant + country and
    returns the exam name/category; (2) one writable CTE appends the stream-log
    row AND mirrors it onto users atomically. The response is built in memory —
    no extra read.
    """
    # Validate AND write in a SINGLE round-trip. The insert only fires when the
    # exam is valid and the variant/country checks pass; the returned flags let us
    # raise the precise error on the (rare) invalid input without a second query.
    row = await pool.fetchrow(
        """
        with exam as (
            select ce.id, ce.name, ce.requires_country, ce.default_country_code,
                   mc.code as category_code
            from catalog_exams ce join mock_categories mc on mc.id = ce.category_id
            where ce.code = $1 and ce.is_active = true
        ),
        checked as (
            select e.*,
                   ($3::text is null or exists (select 1 from exam_variants v
                        where v.code = $3 and v.catalog_exam_id = e.id)) as variant_ok,
                   coalesce($4::text, e.default_country_code) as country_code
            from exam e
        ),
        gated as (
            select c.*,
                   (not c.requires_country or c.country_code is not null) as country_present,
                   (c.country_code is null
                     or exists (select 1 from countries co where co.code = c.country_code)) as country_ok
            from checked c
        ),
        ins as (
            insert into user_stream_selections
                (user_id, category_code, catalog_exam_code, variant_code, target_country_code, source)
            select $2, category_code, $1, $3, country_code, 'switch'
            from gated where variant_ok and country_present and country_ok
            returning created_at
        ),
        upd as (
            update users set mock_category_code = (select category_code from gated),
                             catalog_exam_code = $1,
                             target_country_code = (select country_code from gated)
            where id = $2 and exists (select 1 from ins)
        )
        select g.name as exam_name, g.category_code, g.country_code,
               g.variant_ok, g.country_present, g.country_ok,
               (select created_at from ins) as created_at
        from gated g
        """,
        catalog_exam_code, user_id, variant_code, (target_country_code or None),
    )
    if row is None:
        raise StreamError("invalid_exam", "Unknown exam.")
    if not row["variant_ok"]:
        raise StreamError("invalid_variant", "That variant does not belong to the selected exam.")
    if not row["country_present"]:
        raise StreamError("country_required", "Select a target country for this exam.")
    if not row["country_ok"]:
        raise StreamError("invalid_country", "Unknown country.")

    return {
        "category_code": row["category_code"],
        "catalog_exam_code": catalog_exam_code,
        "catalog_exam_name": row["exam_name"],
        "variant_code": variant_code,
        "target_country_code": row["country_code"],
        "source": "switch",
        "selected_at": row["created_at"],
    }
