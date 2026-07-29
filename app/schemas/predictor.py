"""dMAT college-readiness: Anabin institution + eligibility × dMAT-percentile."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class AnabinInstitutionOut(BaseModel):
    id: UUID
    name: str
    city: str | None
    state: str | None
    institution_type: str | None
    status: str                 # H+ | H+/- | H-


class SetInstitutionIn(BaseModel):
    institution_id: UUID


class EligibilityOut(BaseModel):
    institution_id: UUID | None
    institution_name: str | None
    status: str | None          # H+ | H+/- | H- | null (none selected)
    recognized: bool            # true only for H+
    meaning: str


class DmatStandingOut(BaseModel):
    percentile: float | None
    band: str | None            # top | strong | mid | low
    best_score: float | None


class UniUsingDmat(BaseModel):
    name: str
    program: str
    note: str


class SetAcademicsIn(BaseModel):
    ug_percentage: float | None = None
    twelfth_percentage: float | None = None
    dmat_field: str | None = None    # engineering | commerce_finance_economics | business_management


class ReadinessBreakdown(BaseModel):
    """Transparent view of the formula so the UI can show the working."""
    ug_percentage: float | None
    german_grade: float | None       # Modified Bavarian Formula (1.0–4.0)
    academic_score: float | None     # A (0–100), weight 0.55; 0 if UG < 60%
    dmat_percentile: float | None
    dmat_score: float | None         # D (0–100), weight 0.35; 0 if percentile < 70
    twelfth_percentage: float | None
    twelfth_score: float | None      # T (0–100), weight 0.10
    competitiveness: float | None    # C = 0.55·A + 0.35·D + 0.10·T
    eligibility_multiplier: float    # E: H+ =1.0, H+/- =0.5, H- =0
    readiness_score: float | None    # R = C × E (0–100)


class CollegeReadinessOut(BaseModel):
    applicable: bool            # dMAT-scoped: true only for dMAT-stream students
    eligibility: EligibilityOut | None   # null until a university is selected
    dmat: DmatStandingOut | None         # null until the student has a dMAT mock
    readiness: str              # strong | target | reach | low | eligibility_risk | unknown
    readiness_note: str
    readiness_score: float | None   # R (0–100); null until inputs are present
    breakdown: ReadinessBreakdown
    missing_inputs: list[str]   # what the student still needs to provide
    universities_scoring_dmat: list[UniUsingDmat]   # the 2 that use the dMAT SCORE
    dmat_admission_note: str    # the 2-score-vs-mandatory-via-APS reality
    disclaimer: str


# ---- Target programmes (real DAAD German Master's, overlaid with eligibility) ----

class DaadProgramOut(BaseModel):
    name: str
    university: str
    city: str | None
    languages: list[str]
    subject: str | None
    tuition: str | None
    duration: str | None
    application_deadline: str | None
    link: str | None
    admission_mode: str | None    # "open" (zulassungsfrei) | "restricted" | null (unknown)
    tier: str | None = None       # "safe" | "target" | "reach" — application-list bucket


class AdmissionSummary(BaseModel):
    open: int          # zulassungsfrei
    restricted: int    # zulassungsbeschränkt (NC / selection)
    unknown: int       # admission mode not yet known for the programme


class TierSummary(BaseModel):
    """Counts for the three application-list buckets, over the matched set.

    Honest tiering from real signals only (programme admission mode + the
    student's Anabin eligibility) — never a fabricated admission percentage.
    """
    safe: int      # open admission AND degree recognized (H+): admitted if you meet the bar
    target: int    # admission mode unknown, or open-but-eligibility-unresolved
    reach: int     # restricted (NC / selection): selective — competitive, worth a shot


class DmatFieldOut(BaseModel):
    key: str                    # engineering | commerce_finance_economics | business_management
    label: str


class TargetProgramsOut(BaseModel):
    applicable: bool            # dMAT-scoped
    eligibility: EligibilityOut | None   # null until a university is selected
    field: DmatFieldOut | None  # the resolved dMAT field the list is scoped to
    public_only: bool           # always true — only state-run universities are shown
    total_matched: int
    admission_summary: AdmissionSummary   # open/restricted/unknown over the matched set
    tier_summary: TierSummary             # safe/target/reach over the matched set
    programs: list[DaadProgramOut]
    note: str
