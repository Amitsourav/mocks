"""AI insight pipeline via OpenRouter (OpenAI-compatible API).

Built now, DORMANT until OPENROUTER_API_KEY is set. Two tiers:
  - GRADE model (fast, high-volume): per-answer concept + error-type extraction.
  - SYNTH model (best reasoning, e.g. Opus): per-attempt + student-profile narrative.

Prompts encode the learning-science rules that make feedback actually work
(Hattie feed-up/back/forward, process-level not praise, ONE prioritized next
action, retrieval+spacing method, name the calibration blind spot). The output
JSON shapes match the `attempt_insights` / `student_insights` / question error
fields exactly, so crafted sample data and real AI output are interchangeable.
"""

from __future__ import annotations

import json

import httpx

from app.core.config import get_settings


class AINotConfigured(Exception):
    """Raised when the AI pipeline is called without OPENROUTER_API_KEY set."""


class AIError(Exception):
    """Raised on an OpenRouter API / parsing failure."""


# --- System prompts (the pedagogy lives here) ---

_GRADE_SYSTEM = """You are an expert exam grader for Indian/international competitive exams.
Given a question, the student's chosen answer, the correct answer, response time, and item
difficulty, output STRICT JSON:
{"kc_name": "<the single specific concept/formula the item hinges on, e.g. 'Pythagorean identity sin^2x+cos^2x=1'>",
 "kc_code": "<UPPER_SNAKE stable code for that concept>",
 "kc_type": "fact|procedure|concept",
 "error_type": "correct|careless|conceptual|procedural|guess|unattempted",
 "misconception": "<if wrong: the specific misconception the chosen option reveals, else null>"}
Rules: a fast wrong answer on a known concept = careless; a slow wrong answer = conceptual or procedural;
a fast correct answer on a hard item may be a guess. Output ONLY the JSON object."""

_ATTEMPT_SYSTEM = """You are an elite exam coach writing feedback that CHANGES BEHAVIOR, grounded in
Hattie & Timperley and formative-assessment research. Write at the PROCESS level, never praise.
Structure feedback as: where the student is going (goal), where they are now (status, the pattern not the grade),
WHY the gap exists (conceptual vs careless vs pacing vs over-confidence), and ONE prioritized next action
using active retrieval + spacing (never 're-read the chapter'). Name any confidence-vs-performance blind spot.
Output STRICT JSON:
{"headline": "<one punchy sentence>",
 "goal": "<the concrete target>",
 "current_status": "<process-level status incl. the key pattern>",
 "gap_diagnosis": "<the mechanism: why marks are lost>",
 "calibration_note": "<confidence vs actual, or null>",
 "next_actions": ["<one specific, do-it-today action>", "<optional second>"],
 "recommended_method": "<retrieval/spacing method>",
 "behavior_archetype": "<e.g. Rusher, Gambler, Marathoner, Jumping Around>"}
Output ONLY the JSON object."""

_PROFILE_SYSTEM = """You are an elite exam coach writing a student's EVOLVING profile across many mock attempts.
Synthesize persistent strengths and gaps (not one-off), predict the likely real-exam score with a band,
and give a prioritized study plan of active-retrieval steps. Process-level, forward-looking, never praise.
Output STRICT JSON:
{"summary": "<2-3 sentence narrative ending in what-to-do-next>",
 "persistent_strengths": ["<concept/skill>", ...],
 "persistent_gaps": ["<concept/skill>", ...],
 "predicted_score": <number>,
 "predicted_band_low": <number>,
 "predicted_band_high": <number>,
 "study_plan": [{"step": 1, "focus": "<what>", "action": "<retrieval-based how>"}, ...]}
Output ONLY the JSON object."""


async def _chat(model: str, system: str, user_payload: dict) -> dict:
    settings = get_settings()
    if not settings.ai_enabled:
        raise AINotConfigured("OPENROUTER_API_KEY is not set; AI insight pipeline is dormant.")

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "X-Title": settings.openrouter_app_title,
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.4,
    }
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
        raise AIError(f"OpenRouter call/parse failed: {exc}") from exc


async def grade_answer(payload: dict) -> dict:
    """Per-answer: extract concept, error type, misconception (GRADE model)."""
    settings = get_settings()
    return await _chat(settings.openrouter_model_grade, _GRADE_SYSTEM, payload)


async def generate_attempt_insight(context: dict) -> dict:
    """Per-attempt qualitative narrative (SYNTH model)."""
    settings = get_settings()
    result = await _chat(settings.openrouter_model_synth, _ATTEMPT_SYSTEM, context)
    result["_model"] = settings.openrouter_model_synth
    return result


async def generate_student_profile(context: dict) -> dict:
    """Evolving student profile: strengths, gaps, predicted score, plan (SYNTH model)."""
    settings = get_settings()
    result = await _chat(settings.openrouter_model_synth, _PROFILE_SYSTEM, context)
    result["_model"] = settings.openrouter_model_synth
    return result
