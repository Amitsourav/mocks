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

    # Supabase issues tokens with this issuer; pinning it stops a validly-signed
    # token from a *different* project being accepted.
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1" if settings.supabase_url else None

    try:
        if alg == "HS256":
            # Legacy shared-secret projects. Newer Supabase projects use
            # asymmetric signing keys (ES256/RS256) served via JWKS — check the
            # project's JWKS endpoint if tokens are rejected with an alg error.
            if not settings.supabase_jwt_secret:
                raise AuthError("Server missing SUPABASE_JWT_SECRET")
            key = settings.supabase_jwt_secret
        else:
            if not settings.supabase_jwks_url:
                raise AuthError("Server missing SUPABASE_JWKS_URL for asymmetric JWT verification")
            key = _get_jwk_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token).key

        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience="authenticated",
            issuer=issuer,
            options={"require": ["exp", "sub"], "verify_iss": bool(issuer)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc
    except jwt.PyJWKClientError as exc:
        # No matching `kid` in the JWKS (e.g. a forged token signed with the
        # wrong algorithm, or a key that has been rotated out). This is an auth
        # failure, not a server fault — must surface as 401, never 500.
        raise AuthError("Invalid token: no matching signing key") from exc
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001 - never let key resolution 500
        raise AuthError("Invalid token") from exc

    sub = claims.get("sub")
    if not sub:
        raise AuthError("Token missing subject")

    return AuthenticatedUser(
        auth_user_id=sub,
        phone=claims.get("phone"),
        email=claims.get("email"),
        claims=claims,
    )
