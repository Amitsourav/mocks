from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.user import CurrentUser, ProfileUpdate

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=CurrentUser)
async def get_me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


@router.post("/profile", response_model=CurrentUser)
async def update_profile(
    payload: ProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Fill the post-signup profile form. Marks the profile complete."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        update users set
            full_name = $2,
            email = coalesce($3, email),
            address = $4,
            target_country = $5,
            target_examination_id = $6,
            profile_completed = true
        where id = $1
        returning id, auth_user_id, full_name, email, phone, address,
                  target_country, target_examination_id, role, profile_completed
        """,
        user.id,
        payload.full_name,
        payload.email,
        payload.address,
        payload.target_country,
        payload.target_examination_id,
    )
    return CurrentUser(**dict(row))
