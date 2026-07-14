"""Supabase JWT verification.

Supports both HS256 (legacy shared JWT secret) and asymmetric ES256/RS256
(Supabase signing keys via JWKS). The verified token's `sub` claim is the
Supabase `auth.users.id`, which maps 1:1 to `mock_db.users.auth_user_id`.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or invalid."""


@dataclass(frozen=True)
class AuthenticatedUser:
    auth_user_id: str          # Supabase auth.users.id (JWT `sub`)
    phone: str | None
    email: str | None
    claims: dict


_jwk_client: PyJWKClient | None = None


def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwk_client


def verify_token(token: str) -> AuthenticatedUser:
    settings = get_settings()
    alg = settings.supabase_jwt_alg.upper()

    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthError("Server missing SUPABASE_JWT_SECRET")
            claims = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["exp", "sub"]},
            )
        else:
            signing_key = _get_jwk_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience="authenticated",
                options={"require": ["exp", "sub"]},
            )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise AuthError("Token missing subject")

    return AuthenticatedUser(
        auth_user_id=sub,
        phone=claims.get("phone"),
        email=claims.get("email"),
        claims=claims,
    )
