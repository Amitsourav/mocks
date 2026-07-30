"""Unit tests for the Admitverse CRM lead forward (pure logic, no network).

Covers payload assembly (required fields, omitting empty optionals) and the two
skip guards (missing email+phone; not configured) — the behaviours that keep the
student's profile save safe and the CRM secret from leaking empty rows.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import crm


def test_payload_has_required_fields():
    p = crm._build_payload(
        full_name="Rahul Sharma", email="rahul@example.com", phone="+919876543210",
        external_id="user-123", extra_fields={"courses": ["MBBS"]},
    )
    assert p["form_key"] == "av_mock_test"
    assert p["form_name"] == "AV — Mock Test Signup"
    assert p["source"] == "mock_test"
    assert p["external_id"] == "user-123"
    assert p["full_name"] == "Rahul Sharma"
    assert p["email"] == "rahul@example.com"
    assert p["phone"] == "+919876543210"
    assert p["extra_fields"] == {"courses": ["MBBS"]}


def test_payload_requires_email_or_phone():
    # Neither → None (don't send; CRM would 422).
    assert crm._build_payload(
        full_name="X", email=None, phone=None, external_id="u1", extra_fields=None
    ) is None
    # Empty strings count as missing.
    assert crm._build_payload(
        full_name="X", email="  ", phone="", external_id="u1", extra_fields=None
    ) is None


def test_payload_omits_empty_optional_fields():
    # Phone-only student: email must be omitted entirely, not sent as null/"".
    p = crm._build_payload(
        full_name=None, email="", phone="9876543210", external_id="u2", extra_fields=None,
    )
    assert "email" not in p
    assert "full_name" not in p
    assert p["phone"] == "9876543210"
    assert p["extra_fields"] == {}


async def test_send_skips_when_not_configured(monkeypatch):
    class _S:
        crm_api_url = ""
        crm_website_lead_secret = ""

    monkeypatch.setattr(crm, "get_settings", lambda: _S())
    # Must return without raising and without any network call.
    await crm.send_mock_lead_to_crm(
        full_name="X", email="a@b.com", phone="+919876543210", external_id="u3",
    )


async def test_send_skips_when_no_contact(monkeypatch):
    class _S:
        crm_api_url = "https://crm.example.com"
        crm_website_lead_secret = "secret"

    monkeypatch.setattr(crm, "get_settings", lambda: _S())
    await crm.send_mock_lead_to_crm(
        full_name="X", email=None, phone=None, external_id="u4",
    )
