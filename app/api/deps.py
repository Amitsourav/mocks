"""Request dependencies: authentication and the current app user.

`get_current_user` verifies the Supabase JWT and lazily provisions a
`mock_db.users` row on first authenticated request (the profile form fills the
rest later). This keeps the app-user record in sync with Supabase Auth without a
separate webhook.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.core.db import get_pool
from app.core.security import AuthenticatedUser, AuthError, verify_token
from app.schemas.user import CurrentUser


async def get_auth_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        return verify_token(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


_USER_COLUMNS = """
    id, auth_user_id, full_name, email, phone, address,
    target_country, target_examination_id, role, profile_completed
"""


async def get_current_user(auth: AuthenticatedUser = Depends(get_auth_user)) -> CurrentUser:
    """Resolve the app user for a verified token, provisioning on first sight.

    Read-first: this runs on EVERY authenticated request, so the common path must
    be a cheap indexed SELECT (idx_users_auth_user_id). Doing an unconditional
    upsert here would write — and fire the updated_at trigger — on every single
    API call, which is ruinous during a live exam with many concurrent students.
    The INSERT only happens on a user's very first authenticated request.
    """
    pool = get_pool()
    row = await pool.fetchrow(
        f"select {_USER_COLUMNS} from users where auth_user_id = $1",
        auth.auth_user_id,
    )
    if row is None:
        # First request for this auth user. ON CONFLICT resolves the race where
        # two concurrent first requests both miss the SELECT above.
        row = await pool.fetchrow(
            f"""
            insert into users (auth_user_id, phone, email)
            values ($1, $2, $3)
            on conflict (auth_user_id) do update
                set phone = coalesce(users.phone, excluded.phone),
                    email = coalesce(users.email, excluded.email)
            returning {_USER_COLUMNS}
            """,
            auth.auth_user_id,
            auth.phone,
            auth.email,
        )
    return CurrentUser(**dict(row))


def require_role(*roles: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dep


async def require_complete_profile(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Server-side gate: the profile form must be filled before taking a test.

    The frontend drives the UX from `/me.profile_completed`; this is the safety
    net so the form cannot be skipped by calling the API directly. Browsing the
    exam catalog stays open deliberately.
    """
    if not user.profile_completed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "profile_incomplete",
                "message": "Complete your profile before starting a test.",
            },
        )
    return user
