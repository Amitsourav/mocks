"""Forward a completed mock-test profile as a lead to the Admitverse CRM.

Fires once on profile completion (POST /me/profile), server-side only. It lands
in the CRM's Website Leads inbox as status='new' for a counsellor to review — no
auto-conversion. The mock test writes into the same Admitverse database via the
same secret already configured for admitverse.com (do not mint a new one).

Best-effort by design: our own DB is the system of record, so this call must NEVER
break or delay the student's profile save. It runs as a FastAPI background task
(after the response is sent) and swallows every error (logging it). A run of
`[crm] ... FAILED` logs means leads are silently missing — watch for it.

Idempotent by external_id = student user id: the CRM enforces one submission per
(company, external_id), so a student editing their profile five times produces ONE
lead, not five. We never track "already sent" — we just always pass the user id.

Config: when CRM_API_URL or CRM_WEBSITE_LEAD_SECRET is unset the call is skipped,
so local dev needs no CRM. The secret stays server-side — never send it to a
browser.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("mock_exam")

_INGEST_PATH = "/api/v1/internal/website/ingest"
_FORM_KEY = "av_mock_test"
_FORM_NAME = "AV — Mock Test Signup"
_TIMEOUT = 15.0  # CRM ingest legitimately takes ~2s; keep clear margin


def _clean(value: str | None) -> str | None:
    """Trim to a non-empty string, else None (never send null/empty fields)."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _build_payload(
    *,
    full_name: str | None,
    email: str | None,
    phone: str | None,
    external_id: str,
    extra_fields: dict | None,
) -> dict | None:
    """Assemble the ingest body. Returns None when neither email nor phone is
    present (the CRM requires at least one — don't send until we have one)."""
    email = _clean(email)
    phone = _clean(phone)
    if not email and not phone:
        return None

    payload: dict = {
        "form_key": _FORM_KEY,
        "form_name": _FORM_NAME,
        "source": "mock_test",
        "page": "/profile",
        "external_id": external_id,
        "extra_fields": extra_fields or {},
    }
    # Omit empty optional fields rather than sending null/"".
    if _clean(full_name):
        payload["full_name"] = _clean(full_name)
    if email:
        payload["email"] = email
    if phone:
        payload["phone"] = phone
    return payload


async def send_mock_lead_to_crm(
    *,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    external_id: str,
    extra_fields: dict | None = None,
) -> None:
    settings = get_settings()
    # .strip() guards against a stray space in the Railway env var (a leading
    # space in CRM_API_URL makes httpx reject the URL before sending anything).
    url = (settings.crm_api_url or "").strip().rstrip("/")
    secret = (settings.crm_website_lead_secret or "").strip()
    logger.info("[crm] task running for %s (url_set=%s, secret_set=%s)",
                external_id, bool(url), bool(secret))
    if not url or not secret:
        logger.warning("[crm] not configured — skipping mock-test lead")
        return

    payload = _build_payload(
        full_name=full_name, email=email, phone=phone,
        external_id=external_id, extra_fields=extra_fields,
    )
    if payload is None:
        logger.warning("[crm] no email or phone — skipping mock-test lead for %s", external_id)
        return

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{url}{_INGEST_PATH}",
                headers={"Content-Type": "application/json", "X-Internal-Secret": secret},
                json=payload,
            )
        if resp.status_code == 201:
            body = resp.json() if resp.content else {}
            if body.get("status") == "duplicate_submission":
                logger.info("[crm] mock-test lead already present (duplicate) for %s", external_id)
            else:
                logger.info("[crm] mock-test lead sent for %s (submission %s)",
                            external_id, body.get("submission_id"))
        elif resp.status_code == 403:
            # Bad/missing secret — leads are being LOST. This should alert.
            logger.error("[crm] 403 forbidden — bad/missing X-Internal-Secret; LEADS ARE BEING LOST")
        elif resp.status_code == 429:
            logger.warning("[crm] 429 rate-limited — mock-test lead dropped for %s", external_id)
        else:
            logger.error("[crm] mock-test lead FAILED %s: %s", resp.status_code, resp.text[:300])
    except Exception as exc:  # noqa: BLE001 — the student's save must never fail on the CRM
        logger.error("[crm] mock-test lead FAILED for %s: %s", external_id, exc)
