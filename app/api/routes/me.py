from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.user import CurrentUser, ProfileUpdate

router = APIRouter(prefix="/me", tags=["me"])

# Lenient E.164: leading '+', 8–15 digits. UI collects country code + number.
_E164 = re.compile(r"^\+\d{8,15}$")


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )


@router.get("", response_model=CurrentUser)
async def get_me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


@router.post("/profile", response_model=CurrentUser)
async def update_profile(
    payload: ProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Fill the cascading registration form and mark the profile complete.

    Validates every selection against the reference catalog server-side so a
    forged/stale client cannot store codes that don't exist or an exam that
    doesn't belong to the chosen category.
    """
    pool = get_pool()

    phone = payload.phone.strip()
    if not _E164.match(phone):
        raise _bad("invalid_phone", "Enter a valid phone number with country code, e.g. +919876543210.")

    # State must exist.
    if await pool.fetchval("select 1 from states where code = $1", payload.state_code) is None:
        raise _bad("invalid_state", "Unknown state.")

    # Catalog exam must exist AND belong to the chosen mock category. One query
    # returns existence + pairing + the country rules for that exam.
    exam = await pool.fetchrow(
        """
        select ce.requires_country, ce.default_country_code, mc.code as category_code
        from catalog_exams ce
        join mock_categories mc on mc.id = ce.category_id
        where ce.code = $1 and ce.is_active = true
        """,
        payload.catalog_exam_code,
    )
    if exam is None:
        raise _bad("invalid_exam", "Unknown exam.")
    if exam["category_code"] != payload.mock_category_code:
        raise _bad("exam_category_mismatch", "That exam does not belong to the selected mock type.")

    # Country: required only when the exam requires it; fall back to the exam's
    # default (e.g. d-MAT → Germany). Forced null when the exam has no country.
    country_code: str | None = None
    if exam["requires_country"]:
        country_code = (payload.target_country_code or "").strip() or exam["default_country_code"]
        if not country_code:
            raise _bad("country_required", "Select a target country for this exam.")
        if await pool.fetchval("select 1 from countries where code = $1", country_code) is None:
            raise _bad("invalid_country", "Unknown country.")

    row = await pool.fetchrow(
        """
        update users set
            full_name = $2,
            phone = $3,
            state_code = $4,
            mock_category_code = $5,
            catalog_exam_code = $6,
            target_country_code = $7,
            profile_completed = true
        where id = $1
        returning id, auth_user_id, full_name, email, phone, role, profile_completed,
                  state_code, mock_category_code, catalog_exam_code, target_country_code
        """,
        user.id,
        payload.full_name.strip(),
        phone,
        payload.state_code,
        payload.mock_category_code,
        payload.catalog_exam_code,
        country_code,
    )
    return CurrentUser(**dict(row))
