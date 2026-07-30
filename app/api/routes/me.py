from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.deps import get_current_user, invalidate_user_cache
from app.core.db import get_pool
from app.schemas.catalog import StreamOut, StreamSwitchIn
from app.schemas.predictor import AnabinInstitutionOut, SetAcademicsIn, SetInstitutionIn
from app.schemas.user import CurrentUser, ProfileUpdate
from app.services import streams
from app.services.crm import send_mock_lead_to_crm
from app.services.streams import StreamError

router = APIRouter(prefix="/me", tags=["me"])
logger = logging.getLogger("mock_exam")

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
    background_tasks: BackgroundTasks,
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
    invalidate_user_cache(user.auth_user_id)

    # Profile is now complete (name + phone + course) and committed above — this
    # is the one moment we forward the student to the Admitverse CRM as a lead.
    # Fire-and-forget AFTER the response is sent: the CRM must never delay or fail
    # the student's save. Idempotent by external_id (the user id), so repeated
    # profile edits produce one lead, not many. Not fired on login/provisioning.
    logger.info("[crm] queueing mock-test lead for user=%s", user.id)
    background_tasks.add_task(
        send_mock_lead_to_crm,
        full_name=payload.full_name,
        email=user.email,
        phone=phone,
        external_id=str(user.id),
        extra_fields={
            "mock_user_id": str(user.id),
            "catalog_exam_code": payload.catalog_exam_code,
            "mock_category_code": payload.mock_category_code,
            "state_code": payload.state_code,
            "target_country_code": country_code,
        },
    )
    return CurrentUser(**dict(row))


@router.get("/stream", response_model=StreamOut | None)
async def get_stream(user: CurrentUser = Depends(get_current_user)) -> StreamOut | None:
    """The user's CURRENT exam stream (latest entry in the append-only log)."""
    current = await streams.get_current_stream(get_pool(), user.id)
    return StreamOut(**current) if current else None


@router.post("/stream", response_model=StreamOut)
async def switch_stream(
    payload: StreamSwitchIn,
    user: CurrentUser = Depends(get_current_user),
) -> StreamOut:
    """Switch exam stream — APPENDS a new stream-log row (never overwrites history)."""
    try:
        current = await streams.switch_stream(
            get_pool(), user.id, payload.catalog_exam_code,
            payload.variant_code, payload.target_country_code,
        )
        # Note: we intentionally do NOT invalidate the auth cache here. The current
        # stream is read from the user_stream_selections LOG (not the cached user),
        # and this response returns the new stream directly. Invalidating would make
        # the very next request pay an extra auth DB round-trip. The cached user's
        # mirror columns may lag by up to the cache TTL — cosmetic only.
    except StreamError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return StreamOut(**current)


@router.post("/anabin-institution", response_model=AnabinInstitutionOut)
async def set_anabin_institution(
    payload: SetInstitutionIn, user: CurrentUser = Depends(get_current_user)
) -> AnabinInstitutionOut:
    """Store the student's own (Indian) university — the eligibility half of the
    dMAT college-readiness prediction."""
    pool = get_pool()
    inst = await pool.fetchrow(
        "select id, name, city, state, institution_type, status from anabin_institutions where id = $1",
        payload.institution_id,
    )
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "institution_not_found", "message": "Unknown institution."},
        )
    await pool.execute(
        "update users set anabin_institution_id = $2 where id = $1", user.id, payload.institution_id
    )
    return AnabinInstitutionOut(**dict(inst))


# The three dMAT notified UG fields (graduates in these fields must take the
# dMAT from Summer 2027). Kept in sync with dashboard._DMAT_FIELDS.
_DMAT_FIELD_KEYS = {"engineering", "commerce_finance_economics", "business_management"}


@router.post("/academics", response_model=CurrentUser)
async def set_academics(
    payload: SetAcademicsIn, user: CurrentUser = Depends(get_current_user)
) -> CurrentUser:
    """Store UG%, 12th% and the student's dMAT field — the academic inputs to the
    college-readiness formula and the field used to scope the programme list.

    Any field may be sent alone; a null leaves the stored value unchanged.
    Percentages must be 0–100; dmat_field must be one of the three notified fields.
    """
    for label, val in (("UG", payload.ug_percentage), ("Class XII", payload.twelfth_percentage)):
        if val is not None and not (0 <= val <= 100):
            raise _bad("invalid_percentage", f"{label} percentage must be between 0 and 100.")
    if payload.dmat_field is not None and payload.dmat_field not in _DMAT_FIELD_KEYS:
        raise _bad("invalid_field", "Unknown dMAT field.")

    row = await get_pool().fetchrow(
        """
        update users set
            ug_percentage      = coalesce($2, ug_percentage),
            twelfth_percentage = coalesce($3, twelfth_percentage),
            dmat_field         = coalesce($4, dmat_field)
        where id = $1
        returning id, auth_user_id, full_name, email, phone, role, profile_completed,
                  state_code, mock_category_code, catalog_exam_code, target_country_code
        """,
        user.id, payload.ug_percentage, payload.twelfth_percentage, payload.dmat_field,
    )
    invalidate_user_cache(user.auth_user_id)
    return CurrentUser(**dict(row))
