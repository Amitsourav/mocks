#!/usr/bin/env python3
"""End-to-end smoke test against a running API server.

Drives the full student flow: profile -> list exams -> start attempt ->
enter each section (asserting NO correct-answer field is present) -> answer +
mark for review -> emit events -> submit sections -> submit attempt.

Requires:
  API_BASE_URL   e.g. http://localhost:8000
  ACCESS_TOKEN   a valid Supabase JWT for a test user (from a phone-OTP login)

Run:
  API_BASE_URL=http://localhost:8000 ACCESS_TOKEN=xxx python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
TOKEN = os.environ.get("ACCESS_TOKEN")

FORBIDDEN_KEYS = {"is_correct", "numeric_answer_key", "correct", "answer_key"}


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  ok: {msg}")


def _no_answer_leak(payload) -> bool:
    """Recursively assert none of the forbidden answer-key fields appear."""
    if isinstance(payload, dict):
        if FORBIDDEN_KEYS & set(payload.keys()):
            return False
        return all(_no_answer_leak(v) for v in payload.values())
    if isinstance(payload, list):
        return all(_no_answer_leak(v) for v in payload)
    return True


def main() -> int:
    if not TOKEN:
        print("ACCESS_TOKEN not set", file=sys.stderr)
        return 2

    h = {"Authorization": f"Bearer {TOKEN}"}
    c = httpx.Client(base_url=BASE, headers=h, timeout=15)

    print("health:")
    _assert(c.get("/health").status_code == 200, "server is up")

    print("profile:")
    r = c.post("/me/profile", json={
        "full_name": "Smoke Test", "target_country": "Germany",
        "email": "smoke@example.com", "address": "Test",
    })
    _assert(r.status_code == 200, "profile saved")

    print("catalog:")
    r = c.get("/exams")
    _assert(r.status_code == 200 and len(r.json()) >= 1, "at least one active exam")
    exam = next((e for e in r.json() if e["code"] == "dMAT"), r.json()[0])
    detail = c.get(f"/exams/{exam['id']}").json()
    _assert(_no_answer_leak(detail), "exam detail has no answer keys")

    print("start attempt:")
    r = c.post(f"/exams/{exam['id']}/attempts")
    _assert(r.status_code in (201, 409), "start attempt (201) or already-active (409)")
    if r.status_code == 409:
        print("  (already had an active attempt — resolve manually to re-run cleanly)")
        return 0
    attempt = r.json()
    attempt_id = attempt["id"]

    print("enter sections + answer:")
    answered_any = False
    for sec in attempt["sections"]:
        er = c.post(f"/attempts/{attempt_id}/sections/{sec['section_id']}/enter")
        _assert(er.status_code == 200, f"entered section {sec['code']}")
        delivery = er.json()
        _assert(_no_answer_leak(delivery), f"section {sec['code']} delivery has NO answer keys")

        for q in delivery["questions"]:
            if q["options"]:
                opt = q["options"][0]["id"]
                ar = c.post(f"/attempts/{attempt_id}/answers", json={
                    "question_id": q["id"], "selected_option_id": opt,
                    "is_marked_for_review": True,
                })
                _assert(ar.status_code == 200, f"answered question in {sec['code']}")
                answered_any = True
            c.post(f"/attempts/{attempt_id}/events", json={"events": [
                {"event_type": "question_viewed", "section_id": sec["section_id"], "question_id": q["id"]},
            ]})
        c.post(f"/attempts/{attempt_id}/sections/{sec['section_id']}/submit")

    print("submit attempt:")
    sr = c.post(f"/attempts/{attempt_id}/submit")
    _assert(sr.status_code == 204, "attempt submitted")

    print(f"\nSMOKE TEST PASSED (answered_any={answered_any})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
