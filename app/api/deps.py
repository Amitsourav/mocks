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


async def get_current_user(auth: AuthenticatedUser = Depends(get_auth_user)) -> CurrentUser:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        insert into users (auth_user_id, phone, email)
        values ($1, $2, $3)
        on conflict (auth_user_id) do update
            set phone = coalesce(users.phone, excluded.phone),
                email = coalesce(users.email, excluded.email)
        returning id, auth_user_id, full_name, email, phone, address,
                  target_country, target_examination_id, role, profile_completed
        """,
        auth.auth_user_id,
        auth.phone,
        auth.email,
    )
    return CurrentUser(
        id=row["id"],
        auth_user_id=row["auth_user_id"],
        full_name=row["full_name"],
        email=row["email"],
        phone=row["phone"],
        address=row["address"],
        target_country=row["target_country"],
        target_examination_id=row["target_examination_id"],
        role=row["role"],
        profile_completed=row["profile_completed"],
    )


def require_role(*roles: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dep
