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
    QuestionResultOut,
    SectionResultOut,
    SkillResultOut,
    SkillStat,
)
from app.schemas.insights import (
    AttemptInsightOut,
    ConceptMasteryOut,
    StrategyOut,
    StudentInsightOut,
)
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _f(v):
    return float(v) if v is not None else None


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
