"""Unit tests for pure logic that needs no database.

Full end-to-end engine behavior is exercised by scripts/smoke_test.py against a
running server; these cover the validation/whitelist logic in isolation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.import_questions import validate  # noqa: E402
from app.services.exam_engine import VALID_EVENT_TYPES  # noqa: E402


def _base_question(**over):
    q = {
        "section_code": "MATHEQ",
        "type": "single_choice",
        "content_md": "Q?",
        "options": [
            {"label": "A", "content_md": "1", "is_correct": False},
            {"label": "B", "content_md": "2", "is_correct": True},
        ],
    }
    q.update(over)
    return q


def test_valid_single_choice_passes():
    doc = {"exam_code": "dMAT", "questions": [_base_question()]}
    assert validate(doc) == []


def test_single_choice_requires_exactly_one_correct():
    q = _base_question(options=[
        {"label": "A", "content_md": "1", "is_correct": True},
        {"label": "B", "content_md": "2", "is_correct": True},
    ])
    problems = validate({"exam_code": "dMAT", "questions": [q]})
    assert any("exactly 1 correct" in p for p in problems)


def test_numeric_entry_requires_key():
    q = {"section_code": "MATHEQ", "type": "numeric_entry", "content_md": "x=?"}
    problems = validate({"exam_code": "dMAT", "questions": [q]})
    assert any("numeric_answer_key" in p for p in problems)


def test_missing_exam_code_flagged():
    problems = validate({"questions": [_base_question()]})
    assert any("exam_code" in p for p in problems)


def test_invalid_type_flagged():
    q = _base_question(type="mystery")
    problems = validate({"exam_code": "dMAT", "questions": [q]})
    assert any("invalid type" in p for p in problems)


def test_event_type_whitelist_matches_schema():
    # These must stay in lockstep with the mock_db.event_type enum.
    expected = {
        "section_entered", "section_completed", "question_viewed", "answer_submitted",
        "question_revisited", "marked_for_review", "focus_lost", "focus_regained",
        "fullscreen_exit", "fullscreen_enter",
    }
    assert VALID_EVENT_TYPES == expected
