from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.catalog import (
    AttemptDetail,
    AttemptListItem,
    DashboardSummary,
    OptionReviewOut,
    QuestionResultOut,
    QuestionReviewOut,
    SectionResultOut,
    SkillResultOut,
    SkillTagOut,
    SkillStat,
)
from app.schemas.insights import (
    AttemptInsightOut,
    ConceptMasteryOut,
    StrategyOut,
    StudentInsightOut,
)
from app.schemas.predictor import (
    AdmissionSummary,
    CollegeReadinessOut,
    DaadProgramOut,
    DmatFieldOut,
    DmatStandingOut,
    EligibilityOut,
    ReadinessBreakdown,
    TargetProgramsOut,
    TierSummary,
    UniUsingDmat,
)
from app.schemas.social import LeaderboardEntry, LeaderboardMe, LeaderboardOut
from app.schemas.user import CurrentUser

# The dMAT stream this predictor is scoped to (catalog_exams.code).
_DMAT_CODE = "DMAT"

# The only two German universities that currently use the dMAT SCORE as a formal
# selection criterion, per the official d-mat.de site (2026): "Derzeit nutzen die
# RWTH Aachen und die Georg-August-Universität Göttingen den dMAT als
# Auswahlkriterium für die Zulassung." Neither has published a numeric cutoff.
_DMAT_UNIVERSITIES = [
    UniUsingDmat(
        name="RWTH Aachen University",
        program="M.Sc. Battery Science and Technology",
        note="dMAT counts for roughly 80% of the admission decision.",
    ),
    UniUsingDmat(
        name="Georg-August University Göttingen",
        program="M.Sc. Applied Data Science",
        note="dMAT is used as a selection criterion.",
    ),
]

# The bigger picture: only 2 universities score the dMAT, but from Summer 2027 it
# is a MANDATORY part of the APS process for every applicant in the notified
# fields — so effectively every public university sees it. (aps-india.de/dmat)
_DMAT_ADMISSION_NOTE = (
    "From Summer 2027 the dMAT is a mandatory part of your APS application for degrees in "
    "Engineering, Commerce/Finance/Economics, or Business/Management — so every German "
    "public university you apply to in your field receives your dMAT. Admission stays "
    "holistic: each university weighs it alongside your grades and documents."
)

# The three dMAT notified UG fields → the DAAD subject keywords that identify
# matching Master's programmes. Graduates in these fields must take the dMAT
# from Summer 2027. Keys kept in sync with me._DMAT_FIELD_KEYS.
_DMAT_FIELDS: dict[str, dict] = {
    "engineering": {
        "label": "Engineering",
        "keywords": [
            "engineering", "mechanical", "electrical", "civil", "chemical", "automation",
            "materials", "manufacturing", "renewable", "electronic", "mechatronic",
            "aerospace", "automotive", "robotic", "computer science", "information technology",
            "data science", "geodesy", "energy", "bioengineering", "production",
        ],
    },
    "commerce_finance_economics": {
        "label": "Commerce / Accounting / Finance / Economics",
        "keywords": [
            "economic", "finance", "financial", "accounting", "commerce", "insurance",
            "banking", "actuarial", "quantitative",
        ],
    },
    "business_management": {
        "label": "Business / Management",
        "keywords": [
            "business", "management", "administration", "marketing", "logistics",
            "entrepreneur", "supply chain",
        ],
    },
}

_DMAT_DISCLAIMER = (
    "dMAT's first India cohort is 2026, so no official score cut-offs are published yet. "
    "This is an estimate from your degree's Anabin recognition status and your dMAT "
    "percentile — not a guarantee of admission."
)

_ELIGIBILITY_MEANING = {
    "H+": "Your degree is recognized in Germany (Anabin H+) — you clear the eligibility bar.",
    "H+/-": "Recognition is case-by-case for your university (Anabin H+/−) — verify your specific programme.",
    "H-": "Your degree is not recognized in Germany (Anabin H−) — this blocks admission on its own.",
}


def _pct_band(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct >= 80:
        return "top"
    if pct >= 60:
        return "strong"
    if pct >= 40:
        return "mid"
    return "low"

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _f(v):
    return float(v) if v is not None else None


def _display_name(full_name: str | None) -> str:
    """Safe leaderboard name: first name + last initial. Never email/phone.

    'Amit Kumar' -> 'Amit K.'  ·  'Priya' -> 'Priya'  ·  '' / None -> 'Student'.
    """
    parts = (full_name or "").strip().split()
    if not parts:
        return "Student"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


def _attempt_item(r) -> AttemptListItem:
    return AttemptListItem(
        id=r["id"],
        mock_title=r.get("mock_title") if isinstance(r, dict) else r["mock_title"],
        catalog_exam_code=r["catalog_exam_code"],
        submitted_at=r["submitted_at"],
        duration_seconds=r["duration_seconds"],
        total_questions=r["total_questions"],
        correct=r["correct"],
        score=_f(r["score"]),
        max_score=_f(r["max_score"]),
        percentile=_f(r["percentile"]),
        accuracy_pct=_f(r["accuracy_pct"]),
    )


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(user: CurrentUser = Depends(get_current_user)) -> DashboardSummary:
    # Single round-trip: aggregates + latest/first via ordered array_agg.
    agg = await get_pool().fetchrow(
        """
        select count(*) as n,
               avg(score) as avg_score,
               max(score) as best_score,
               avg(accuracy_pct) as avg_acc,
               coalesce(sum(duration_seconds), 0) as total_time,
               (array_agg(accuracy_pct order by submitted_at desc nulls last))[1] as latest_acc,
               (array_agg(percentile   order by submitted_at desc nulls last))[1] as latest_pct,
               (array_agg(accuracy_pct order by submitted_at asc  nulls last))[1] as first_acc
        from attempt_results
        where user_id = $1
        """,
        user.id,
    )
    latest_acc = _f(agg["latest_acc"])
    first_acc = _f(agg["first_acc"])
    improvement = round(latest_acc - first_acc, 2) if (latest_acc is not None and first_acc is not None) else None

    return DashboardSummary(
        total_attempts=agg["n"],
        avg_score=round(_f(agg["avg_score"]), 2) if agg["avg_score"] is not None else None,
        best_score=_f(agg["best_score"]),
        avg_accuracy_pct=round(_f(agg["avg_acc"]), 2) if agg["avg_acc"] is not None else None,
        latest_percentile=_f(agg["latest_pct"]),
        first_accuracy_pct=first_acc,
        improvement_pct=improvement,
        total_time_seconds=agg["total_time"],
    )


@router.get("/attempts", response_model=list[AttemptListItem])
async def dashboard_attempts(user: CurrentUser = Depends(get_current_user)) -> list[AttemptListItem]:
    rows = await get_pool().fetch(
        """
        select ar.id, mt.title as mock_title, ar.catalog_exam_code, ar.submitted_at,
               ar.duration_seconds, ar.total_questions, ar.correct, ar.score,
               ar.max_score, ar.percentile, ar.accuracy_pct
        from attempt_results ar
        left join mock_tests mt on mt.id = ar.mock_test_id
        where ar.user_id = $1
        order by ar.submitted_at asc nulls last
        """,
        user.id,
    )
    return [_attempt_item(dict(r)) for r in rows]


@router.get("/skills", response_model=list[SkillStat])
async def dashboard_skills(user: CurrentUser = Depends(get_current_user)) -> list[SkillStat]:
    """Per-skill accuracy aggregated across all the user's attempts (radar/weakness)."""
    rows = await get_pool().fetch(
        """
        select sr.skill_code, sr.skill_name,
               count(distinct sr.attempt_result_id) as attempts,
               round(avg(sr.accuracy_pct), 2) as avg_acc,
               round(avg(sr.avg_time_ms))::int as avg_time
        from attempt_skill_results sr
        join attempt_results ar on ar.id = sr.attempt_result_id
        where ar.user_id = $1
        group by sr.skill_code, sr.skill_name
        order by avg_acc asc nulls last
        """,
        user.id,
    )
    return [
        SkillStat(
            skill_code=r["skill_code"],
            skill_name=r["skill_name"],
            attempts=r["attempts"],
            avg_accuracy_pct=_f(r["avg_acc"]),
            avg_time_ms=r["avg_time"],
        )
        for r in rows
    ]


@router.get("/attempts/{attempt_id}", response_model=AttemptDetail)
async def dashboard_attempt_detail(
    attempt_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> AttemptDetail:
    pool = get_pool()
    # All five reads are independent — fire them concurrently (one round-trip of
    # wall-clock instead of five). Ownership is checked on the attempt row after.
    ar, sections, skills, questions, ins = await asyncio.gather(
        pool.fetchrow(
            """
            select ar.id, mt.title as mock_title, ar.catalog_exam_code, ar.submitted_at,
                   ar.duration_seconds, ar.total_questions, ar.correct, ar.score,
                   ar.max_score, ar.percentile, ar.accuracy_pct, ar.user_id
            from attempt_results ar
            left join mock_tests mt on mt.id = ar.mock_test_id
            where ar.id = $1
            """,
            attempt_id,
        ),
        pool.fetch(
            "select section_name,total,correct,wrong,skipped,score,accuracy_pct,avg_time_ms "
            "from attempt_section_results where attempt_result_id=$1 order by position",
            attempt_id,
        ),
        pool.fetch(
            "select skill_code,skill_name,total,correct,accuracy_pct,avg_time_ms "
            "from attempt_skill_results where attempt_result_id=$1 order by accuracy_pct asc nulls last",
            attempt_id,
        ),
        pool.fetch(
            "select question_no,section_name,skill_code,kc_code,error_type::text as error_type,"
            "is_correct,time_spent_ms,difficulty,marked_for_review "
            "from attempt_question_results where attempt_result_id=$1 order by question_no",
            attempt_id,
        ),
        pool.fetchrow(
            """select headline,goal,current_status,gap_diagnosis,calibration_note,next_actions,
                      recommended_method,behavior_archetype,pacing_note,negative_marking_loss,
                      guess_rate,calibration_gap,generated_by::text as generated_by
               from attempt_insights where attempt_result_id=$1""",
            attempt_id,
        ),
    )
    if ar is None or ar["user_id"] != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found")

    return AttemptDetail(
        attempt=_attempt_item(dict(ar)),
        sections=[SectionResultOut(**{k: (_f(v) if k in ("score", "accuracy_pct") else v)
                                      for k, v in dict(s).items()}) for s in sections],
        skills=[SkillResultOut(**{k: (_f(v) if k == "accuracy_pct" else v)
                                  for k, v in dict(s).items()}) for s in skills],
        questions=[QuestionResultOut(**dict(q)) for q in questions],
        insight=_to_attempt_insight(ins) if ins else None,
    )


@router.get("/attempts/{attempt_id}/questions/{question_no}", response_model=QuestionReviewOut)
async def dashboard_question_review(
    attempt_id: UUID, question_no: int, user: CurrentUser = Depends(get_current_user)
) -> QuestionReviewOut:
    """Grid drill-down: full review of one question in a submitted attempt — the question
    body, every option (correct one + the candidate's pick both flagged), the worked
    solution, and per-question stats. Answer keys are revealed (post-submission review)."""
    pool = get_pool()
    # Ownership + the engine attempt this result came from, plus the snapshot row (which
    # always exists even when the underlying question was later deleted / is demo data).
    ar, snap = await asyncio.gather(
        pool.fetchrow(
            "select id, user_id, engine_attempt_id from attempt_results where id=$1", attempt_id),
        pool.fetchrow(
            "select section_name, skill_code, error_type::text as error_type, is_correct, "
            "time_spent_ms, difficulty, marked_for_review "
            "from attempt_question_results where attempt_result_id=$1 and question_no=$2",
            attempt_id, question_no),
    )
    if ar is None or ar["user_id"] != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found")

    eng = ar["engine_attempt_id"]
    # Resolve the real question via the frozen paper (question_no == attempt_questions.position).
    qrow = None
    if eng is not None:
        qrow = await pool.fetchrow(
            """
            select q.id as qid, q.question_type::text as qtype, q.content_md, q.difficulty,
                   st.content_md as stimulus_md, s.name as section_name
            from attempt_questions aq
            join questions q on q.id = aq.question_id
            join exam_sections s on s.id = aq.section_id
            left join stimuli st on st.id = q.stimulus_id
            where aq.attempt_id = $1 and aq.position = $2
            """,
            eng, question_no,
        )

    if qrow is None:
        # Demo/dummy attempt (no engine attempt) or the question was deleted after the
        # attempt — return the snapshot-only view so the UI can show a graceful message.
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
        return QuestionReviewOut(
            question_no=question_no, section_name=snap["section_name"], question_type="single_choice",
            difficulty=snap["difficulty"], content_md="", options=[], selected_label=None,
            correct_label=None, is_correct=snap["is_correct"], error_type=snap["error_type"],
            time_spent_ms=snap["time_spent_ms"], marked_for_review=snap["marked_for_review"],
            skills=[], detail_available=False,
        )

    qid = qrow["qid"]
    opts, ans, sol, skills = await asyncio.gather(
        pool.fetch(
            "select id, label, content_md, is_correct, position from question_options "
            "where question_id=$1 order by position", qid),
        pool.fetchrow(
            "select selected_option_id, time_spent_ms, is_marked_for_review "
            "from student_answers where attempt_id=$1 and question_id=$2", eng, qid),
        pool.fetchrow(
            "select solution_md, final_answer, correct_label from solutions where question_id=$1", qid),
        pool.fetch(
            "select sk.code, sk.name from question_skill_tags qst "
            "join skills sk on sk.id=qst.skill_id where qst.question_id=$1", qid),
    )
    selected_id = ans["selected_option_id"] if ans else None
    selected_label = correct_label = None
    options = []
    for o in opts:
        is_sel = selected_id is not None and o["id"] == selected_id
        if is_sel:
            selected_label = o["label"]
        if o["is_correct"]:
            correct_label = o["label"]
        options.append(OptionReviewOut(
            id=str(o["id"]), label=o["label"], content_md=o["content_md"],
            is_correct=o["is_correct"], is_selected=is_sel))
    is_correct = None if selected_id is None else (selected_label == correct_label)

    return QuestionReviewOut(
        question_no=question_no,
        section_name=qrow["section_name"] or (snap["section_name"] if snap else None),
        question_type=qrow["qtype"], difficulty=qrow["difficulty"],
        content_md=qrow["content_md"], stimulus_md=qrow["stimulus_md"],
        options=options, selected_label=selected_label,
        correct_label=correct_label or (sol["correct_label"] if sol else None),
        is_correct=is_correct,
        error_type=snap["error_type"] if snap else None,
        time_spent_ms=(ans["time_spent_ms"] if ans and ans["time_spent_ms"] is not None
                       else (snap["time_spent_ms"] if snap else None)),
        marked_for_review=bool(ans["is_marked_for_review"]) if ans else (
            snap["marked_for_review"] if snap else False),
        skills=[SkillTagOut(code=s["code"], name=s["name"]) for s in skills],
        solution_md=sol["solution_md"] if sol else None,
        final_answer=sol["final_answer"] if sol else None,
        detail_available=True,
    )


def _to_attempt_insight(r) -> AttemptInsightOut:
    d = dict(r)
    na = d.get("next_actions")
    if isinstance(na, str):
        na = json.loads(na)
    return AttemptInsightOut(
        headline=d["headline"], goal=d["goal"], current_status=d["current_status"],
        gap_diagnosis=d["gap_diagnosis"], calibration_note=d["calibration_note"],
        next_actions=na or [], recommended_method=d["recommended_method"],
        behavior_archetype=d["behavior_archetype"], pacing_note=d["pacing_note"],
        negative_marking_loss=_f(d["negative_marking_loss"]), guess_rate=_f(d["guess_rate"]),
        calibration_gap=_f(d["calibration_gap"]), generated_by=d["generated_by"],
    )


@router.get("/insight", response_model=StudentInsightOut | None)
async def dashboard_insight(user: CurrentUser = Depends(get_current_user)) -> StudentInsightOut | None:
    """The headline story: current evolving student profile (predicted score, gaps, plan)."""
    r = await get_pool().fetchrow(
        """select stream_catalog_exam_code, summary, persistent_strengths, persistent_gaps,
                  predicted_score, predicted_band_low, predicted_band_high, study_plan,
                  generated_by::text as generated_by, created_at
           from student_insights where user_id=$1 order by created_at desc limit 1""",
        user.id,
    )
    if r is None:
        return None
    d = dict(r)
    for k in ("persistent_strengths", "persistent_gaps", "study_plan"):
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return StudentInsightOut(
        stream_catalog_exam_code=d["stream_catalog_exam_code"], summary=d["summary"],
        persistent_strengths=d["persistent_strengths"], persistent_gaps=d["persistent_gaps"],
        predicted_score=_f(d["predicted_score"]), predicted_band_low=_f(d["predicted_band_low"]),
        predicted_band_high=_f(d["predicted_band_high"]), study_plan=d["study_plan"],
        generated_by=d["generated_by"], created_at=d["created_at"],
    )


@router.get("/concepts", response_model=list[ConceptMasteryOut])
async def dashboard_concepts(user: CurrentUser = Depends(get_current_user)) -> list[ConceptMasteryOut]:
    """Concept mastery map / 'ready to fix next' — ranked by gap_priority (weakest first)."""
    rows = await get_pool().fetch(
        """select kc.code as kc_code, kc.name as kc_name, ss.name as subject_name,
                  m.p_mastery, m.retention_probability, m.gap_priority,
                  m.careless_rate, m.conceptual_gap_score, m.n_opportunities
           from student_concept_mastery m
           join knowledge_components kc on kc.id = m.kc_id
           left join syllabus_subjects ss on ss.id = kc.subject_id
           where m.user_id=$1
           order by m.gap_priority desc nulls last""",
        user.id,
    )
    return [
        ConceptMasteryOut(
            kc_code=r["kc_code"], kc_name=r["kc_name"], subject_name=r["subject_name"],
            p_mastery=_f(r["p_mastery"]), retention_probability=_f(r["retention_probability"]),
            gap_priority=_f(r["gap_priority"]), careless_rate=_f(r["careless_rate"]),
            conceptual_gap_score=_f(r["conceptual_gap_score"]), n_opportunities=r["n_opportunities"],
        )
        for r in rows
    ]


@router.get("/leaderboard", response_model=LeaderboardOut)
async def dashboard_leaderboard(
    timeframe: str = "all", user: CurrentUser = Depends(get_current_user)
) -> LeaderboardOut:
    """Best-score ranking within the user's exam stream. Top 10, a slice around
    me when I'm outside it, and always my own row.

    - Metric: best_score. `timeframe`: "all" (default) or "week" (best score from
      attempts in the last 7 days only).
    - Stream = the user's current catalog_exam_code; JEE ranks against JEE.
    - Tie rule: same best score -> earlier attempt ranks higher (deterministic
      row_number, so ranks are unique).
    - delta_rank: real movement vs the ranking as of 7 days ago (positive = climbed).
      Null for the "week" board and for anyone with no attempt older than 7 days.
    - All values are computed live from attempt_results — nothing is seeded.
    """
    tf = "week" if timeframe == "week" else "all"
    pool = get_pool()
    stream_code = await pool.fetchval("select catalog_exam_code from users where id = $1", user.id)
    if not stream_code:
        return LeaderboardOut(
            scope="stream", metric="best_score", stream_code=None, timeframe=tf,
            entries=[], me=LeaderboardMe(rank=None, value=None, total_participants=0),
        )

    rows = await pool.fetch(
        """
        with best as (
            -- each user's best-scoring attempt in the stream (earliest on ties),
            -- optionally restricted to the last 7 days for the weekly board
            select distinct on (ar.user_id)
                   ar.user_id, ar.score, ar.submitted_at
            from attempt_results ar
            where ar.catalog_exam_code = $2 and ar.score is not null
              and ($3 = 'all' or ar.submitted_at >= now() - interval '7 days')
            order by ar.user_id, ar.score desc, ar.submitted_at asc
        ),
        ranked as (
            select b.user_id, b.score, u.full_name,
                   row_number() over (order by b.score desc, b.submitted_at asc) as rnk,
                   count(*) over () as total
            from best b
            join users u on u.id = b.user_id
        ),
        prev as (
            -- ranking as it stood 7 days ago (all-time board only), for movement
            select bp.user_id,
                   row_number() over (order by bp.score desc, bp.submitted_at asc) as rnk_prev
            from (
                select distinct on (ar.user_id) ar.user_id, ar.score, ar.submitted_at
                from attempt_results ar
                where ar.catalog_exam_code = $2 and ar.score is not null
                  and ar.submitted_at <= now() - interval '7 days'
                order by ar.user_id, ar.score desc, ar.submitted_at asc
            ) bp
        ),
        me_rank as (select rnk from ranked where user_id = $1)
        select r.user_id, r.score, r.full_name, r.rnk, r.total,
               case when $3 = 'all' and p.rnk_prev is not null
                    then p.rnk_prev - r.rnk else null end as delta_rank
        from ranked r
        left join prev p on p.user_id = r.user_id
        where r.rnk <= 10
           or r.user_id = $1
           or abs(r.rnk - (select rnk from me_rank)) <= 2
        order by r.rnk
        """,
        user.id, stream_code, tf,
    )

    total = rows[0]["total"] if rows else 0
    me = LeaderboardMe(rank=None, value=None, total_participants=total)
    entries: list[LeaderboardEntry] = []
    near: list[LeaderboardEntry] = []
    for r in rows:
        is_me = r["user_id"] == user.id
        entry = LeaderboardEntry(
            rank=r["rnk"], display_name=_display_name(r["full_name"]),
            value=_f(r["score"]), is_me=is_me, delta_rank=r["delta_rank"],
        )
        if r["rnk"] <= 10:
            entries.append(entry)
        else:
            near.append(entry)
        if is_me:
            me = LeaderboardMe(
                rank=r["rnk"], value=_f(r["score"]),
                total_participants=total, delta_rank=r["delta_rank"],
            )

    # around_me only when I'm actually outside the top-10.
    around_me = near if (me.rank is not None and me.rank > 10 and near) else None

    return LeaderboardOut(
        scope="stream", metric="best_score", stream_code=stream_code, timeframe=tf,
        entries=entries, around_me=around_me, me=me,
    )


@router.get("/strategy", response_model=StrategyOut)
async def dashboard_strategy(user: CurrentUser = Depends(get_current_user)) -> StrategyOut:
    """Behavioral / test-strategy view aggregated across all the user's attempts."""
    pool = get_pool()
    dist_rows, agg, arch = await asyncio.gather(
        pool.fetch(
            """select coalesce(q.error_type::text,'unknown') as et, count(*) as n
               from attempt_question_results q
               join attempt_results ar on ar.id = q.attempt_result_id
               where ar.user_id=$1 group by q.error_type""",
            user.id,
        ),
        pool.fetchrow(
            """select count(*) as n, round(avg(guess_rate),2) as gr,
                      round(sum(negative_marking_loss),2) as nml, round(avg(calibration_gap),2) as cg
               from attempt_insights ai join attempt_results ar on ar.id = ai.attempt_result_id
               where ar.user_id=$1""",
            user.id,
        ),
        pool.fetchrow(
            """select behavior_archetype, count(*) c
               from attempt_insights ai join attempt_results ar on ar.id = ai.attempt_result_id
               where ar.user_id=$1 and behavior_archetype is not null
               group by behavior_archetype order by c desc limit 1""",
            user.id,
        ),
    )
    dist = {r["et"]: r["n"] for r in dist_rows}
    wrong = dist.get("careless", 0) + dist.get("conceptual", 0) + dist.get("procedural", 0)
    careless_share = round(100 * dist.get("careless", 0) / wrong, 2) if wrong else None
    return StrategyOut(
        attempts=agg["n"] or 0,
        error_distribution=dist,
        careless_share_pct=careless_share,
        avg_guess_rate=_f(agg["gr"]),
        total_negative_marking_loss=_f(agg["nml"]),
        avg_calibration_gap=_f(agg["cg"]),
        dominant_archetype=arch["behavior_archetype"] if arch else None,
        pacing_note=(f"{careless_share:.0f}% of your wrong answers were careless (fast-wrong) — "
                     f"pacing discipline is your cheapest win." if careless_share else None),
    )


# ---- The readiness formula: R = C × E --------------------------------------
# C = 0.55·A + 0.35·D + 0.10·T   (UG grade dominant, dMAT secondary, 12th minor)
_W_ACADEMIC, _W_DMAT, _W_TWELFTH = 0.55, 0.35, 0.10
_E_BY_STATUS = {"H+": 1.0, "H+/-": 0.5, "H-": 0.0}


def _german_grade(ug: float) -> float:
    """Modified Bavarian Formula: UG% → German grade (1.0 best … 4.0 pass)."""
    return round(1 + (100 - ug) / 20, 2)


def _academic_score(ug: float | None) -> float | None:
    if ug is None:
        return None
    if ug < 60:                      # floor: below 60% UG contributes nothing
        return 0.0
    return round(max(0.0, min(100.0, 100 * (4.0 - _german_grade(ug)) / 3.0)), 1)


def _dmat_score(pct: float | None) -> float | None:
    if pct is None:
        return None
    if pct < 70:                     # floor: below the 70th percentile → 0
        return 0.0
    return round(max(0.0, min(100.0, (pct - 70) / 30 * 100)), 1)


def _twelfth_score(t: float | None) -> float | None:
    if t is None:
        return None
    return round(max(0.0, min(100.0, (t - 60) / 40 * 100)), 1)


def _readiness_band(r: float) -> str:
    if r >= 75:
        return "strong"
    if r >= 55:
        return "target"
    if r >= 40:
        return "reach"
    return "low"


@router.get("/college-predictions", response_model=CollegeReadinessOut)
async def college_predictions(user: CurrentUser = Depends(get_current_user)) -> CollegeReadinessOut:
    """dMAT college-readiness — R = C × E.

    Honest by construction (no invented score→college cut-offs; none exist for the
    2026 first cohort):
      - E (eligibility gate): the student's university's Anabin status — H+ =1.0,
        H+/- =0.5, H- =0.
      - C (competitiveness): 0.55·A + 0.35·D + 0.10·T where A = UG grade
        (Modified Bavarian, floored below 60%), D = dMAT percentile (floored below
        the 70th), T = 12th% (minor).
    dMAT-scoped via `applicable`.
    """
    pool = get_pool()
    urow, inst, agg = await asyncio.gather(
        pool.fetchrow(
            "select catalog_exam_code, ug_percentage, twelfth_percentage from users where id = $1",
            user.id,
        ),
        pool.fetchrow(
            """select ai.id, ai.name, ai.status
               from anabin_institutions ai
               join users u on u.anabin_institution_id = ai.id
               where u.id = $1""",
            user.id,
        ),
        pool.fetchrow(
            """select max(score) as best,
                      (array_agg(percentile order by submitted_at desc nulls last))[1] as latest_pct
               from attempt_results where user_id = $1 and score is not null""",
            user.id,
        ),
    )

    applicable = urow["catalog_exam_code"] == _DMAT_CODE
    ug = _f(urow["ug_percentage"])
    twelfth = _f(urow["twelfth_percentage"])
    pct = _f(agg["latest_pct"]) if agg else None

    # Component scores.
    A = _academic_score(ug)
    D = _dmat_score(pct)
    T = _twelfth_score(twelfth)
    status_code = inst["status"] if inst else None
    E = _E_BY_STATUS.get(status_code) if status_code else None

    # Eligibility view — null until a university is selected (the client shows the
    # picker), otherwise the recognition verdict.
    eligibility = None if inst is None else EligibilityOut(
        institution_id=inst["id"], institution_name=inst["name"], status=status_code,
        recognized=(status_code == "H+"), meaning=_ELIGIBILITY_MEANING.get(status_code, ""),
    )

    # What's still needed for a real score. UG + university are essential; dMAT
    # counts as missing only until the first mock (D floors to 0 meanwhile).
    missing: list[str] = []
    if inst is None:
        missing.append("university")
    if ug is None:
        missing.append("ug_percentage")
    if pct is None:
        missing.append("dmat_percentile")

    competitiveness = readiness_score = None
    can_score = inst is not None and ug is not None
    if can_score:
        C = round(_W_ACADEMIC * (A or 0) + _W_DMAT * (D or 0) + _W_TWELFTH * (T or 0), 1)
        competitiveness = C
        readiness_score = round(C * E, 1)  # E is set whenever inst is set

    breakdown = ReadinessBreakdown(
        ug_percentage=ug, german_grade=_german_grade(ug) if ug is not None else None,
        academic_score=A, dmat_percentile=pct, dmat_score=D,
        twelfth_percentage=twelfth, twelfth_score=T,
        competitiveness=competitiveness, eligibility_multiplier=E if E is not None else 0.0,
        readiness_score=readiness_score,
    )

    # Readiness verdict.
    if not can_score:
        readiness = "unknown"
        need = " and ".join(m.replace("_", " ") for m in missing if m != "dmat_percentile") or "a few details"
        note = f"Add your {need} to see your college readiness."
    elif status_code in ("H-", "H+/-"):
        readiness = "eligibility_risk"
        note = ("Your degree's recognition status is the blocker — a strong dMAT can't offset it. "
                "Resolve eligibility first.")
    else:  # H+, scored
        readiness = _readiness_band(readiness_score)
        note = {
            "strong": "Recognized degree with strong academics/dMAT — a competitive profile.",
            "target": "Recognized degree with solid academics — a realistic target with room to push your dMAT.",
            "reach":  "Recognized, but academics/dMAT sit on the lower side — treat selective programmes as a reach.",
            "low":    "Recognized degree, but the numbers are low — focus on lifting your dMAT and shortlisting accessible programmes.",
        }[readiness]
        if pct is None:
            note += " Take a dMAT mock to complete the picture."

    # dMAT standing — null until the student has a mock with a percentile.
    dmat = None if pct is None else DmatStandingOut(
        percentile=pct, band=_pct_band(pct), best_score=_f(agg["best"]) if agg else None
    )

    return CollegeReadinessOut(
        applicable=applicable,
        eligibility=eligibility,
        dmat=dmat,
        readiness=readiness,
        readiness_note=note,
        readiness_score=readiness_score,
        breakdown=breakdown,
        missing_inputs=missing,
        universities_scoring_dmat=_DMAT_UNIVERSITIES,
        dmat_admission_note=_DMAT_ADMISSION_NOTE,
        disclaimer=_DMAT_DISCLAIMER,
    )


# ---- Reach / Target / Safe tiering for the target-programme list -----------
# Honest by construction — the bucket comes only from a programme's real
# admission mode plus the student's Anabin eligibility, never a fabricated
# admission percentage (dMAT's first cohort has no published cut-offs):
#   open admission  -> Safe   — admitted if you meet the requirements, BUT only
#                      when the degree is recognized (H+); otherwise eligibility,
#                      not the programme, is the blocker, so it can't be "safe".
#   restricted (NC) -> Reach  — selective; competitive, worth a shot.
#   unknown mode    -> Target — can't call it safe, not clearly a reach.
def _program_tier(admission_mode: str | None, eligible: bool) -> str:
    if admission_mode == "open":
        return "safe" if eligible else "target"
    if admission_mode == "restricted":
        return "reach"
    return "target"


@router.get("/target-programs", response_model=TargetProgramsOut)
async def target_programs(
    field: str | None = None,
    q: str = "",
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
) -> TargetProgramsOut:
    """German PUBLIC university Master's programmes the student can apply to, in
    their dMAT field (DAAD data), overlaid with their Anabin eligibility.

    Scope: only state-run (public, tuition-free) universities — the realistic
    target for Indian applicants, and the ones that from Summer 2027 receive the
    dMAT via APS. Auto-scoped to the student's stored `dmat_field` (override with
    `?field=`); `q` refines further by keyword.

    Honest by construction: DAAD publishes no per-programme grade cut-off, so this
    returns REAL programmes in the field + the eligibility gate — not a fabricated
    'guaranteed to get in'. Grade-tier fit lives in the readiness endpoint.
    """
    pool = get_pool()
    query = q.strip()
    urow, inst = await asyncio.gather(
        pool.fetchrow("select catalog_exam_code, dmat_field from users where id = $1", user.id),
        pool.fetchrow(
            """select ai.id, ai.name, ai.status from anabin_institutions ai
               join users u on u.anabin_institution_id = ai.id where u.id = $1""",
            user.id,
        ),
    )

    # Eligibility view — null until a university is selected.
    eligibility = None if inst is None else EligibilityOut(
        institution_id=inst["id"], institution_name=inst["name"], status=inst["status"],
        recognized=(inst["status"] == "H+"), meaning=_ELIGIBILITY_MEANING.get(inst["status"], ""),
    )

    # Resolve the field: explicit override wins, else the student's stored field.
    field_key = field if field in _DMAT_FIELDS else (urow["dmat_field"] if urow else None)
    field_out = (
        DmatFieldOut(key=field_key, label=_DMAT_FIELDS[field_key]["label"])
        if field_key in _DMAT_FIELDS else None
    )

    # Build the WHERE: always public; scope by field keywords; refine by q.
    where = ["is_public is true"]
    args: list = []
    if field_key in _DMAT_FIELDS:
        args.append([f"%{k}%" for k in _DMAT_FIELDS[field_key]["keywords"]])
        where.append(f"(subject ilike any(${len(args)}) or name ilike any(${len(args)}))")
    if len(query) >= 2:
        args.append(f"%{query}%")
        where.append(f"(name ilike ${len(args)} or subject ilike ${len(args)})")
    where_sql = " and ".join(where)

    args.append(min(max(limit, 1), 50))
    limit_pos = len(args)
    # One aggregate over the whole matched set: total + admission-mode counts.
    agg_row = await pool.fetchrow(
        f"""select count(*) as total,
                   count(*) filter (where admission_mode = 'open') as open,
                   count(*) filter (where admission_mode = 'restricted') as restricted,
                   count(*) filter (where admission_mode is null) as unknown
            from daad_programs where {where_sql}""",
        *args[:-1],
    )
    total = agg_row["total"]
    summary = AdmissionSummary(
        open=agg_row["open"], restricted=agg_row["restricted"], unknown=agg_row["unknown"]
    )
    # Tier counts over the whole matched set, derived from the admission-mode
    # counts + eligibility (H+). Open is "safe" only for a recognized degree;
    # otherwise it folds into "target" because eligibility is the real blocker.
    eligible = inst is not None and inst["status"] == "H+"
    tier_summary = TierSummary(
        safe=agg_row["open"] if eligible else 0,
        target=agg_row["unknown"] if eligible else agg_row["open"] + agg_row["unknown"],
        reach=agg_row["restricted"],
    )
    rows = await pool.fetch(
        f"""select name, university, city, languages, subject, tuition, duration,
                   application_deadline, link, admission_mode
            from daad_programs
            where {where_sql}
            order by university, name
            limit ${limit_pos}""",
        *args,
    )

    # Note: eligibility gate first, then field-scope context.
    field_phrase = f"in {field_out.label}" if field_out else "in your field"
    if inst is None:
        note = (f"Public German universities with Master's programmes {field_phrase}. "
                "Add your university to check whether your degree is recognized.")
    elif inst["status"] == "H+":
        note = (f"Your degree is recognized (H+). Real Master's programmes at German PUBLIC "
                f"universities {field_phrase} — grade fit is in your readiness. From Summer 2027 "
                "you'll apply to these with your dMAT via APS.")
    else:
        note = ("Your degree's recognition status is a blocker (see readiness) — resolve eligibility "
                "before targeting these programmes.")
    if field_out is None:
        note += " Set your dMAT field to auto-scope this list."

    return TargetProgramsOut(
        applicable=(urow["catalog_exam_code"] == _DMAT_CODE),
        eligibility=eligibility,
        field=field_out,
        public_only=True,
        total_matched=total or 0,
        admission_summary=summary,
        tier_summary=tier_summary,
        programs=[
            DaadProgramOut(**dict(r), tier=_program_tier(r["admission_mode"], eligible))
            for r in rows
        ],
        note=note,
    )
