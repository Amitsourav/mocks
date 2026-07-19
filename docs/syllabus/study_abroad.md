# Study Abroad Admission Tests — Syllabus Seed

Machine-readable companion: [`study_abroad.json`](./study_abroad.json).

Each exam **section** is modelled as a *subject*; each section's **question types / topic areas** are *chapters*; measurable competencies are *skills* (3–6 per subject). Codes are `UPPER_SNAKE`, globally unique, exam-prefixed. `catalog_exam_code` maps to `mock_db.catalog_exams.code` (DMAT, GMAT, GRE, TOEFL, IELTS).

| Exam | Subjects | Chapters | Skills | Mocks |
|------|---------:|---------:|-------:|------:|
| DMAT  | 4 | 14 | 16 | 5 |
| GMAT  | 3 | 11 | 12 | 4 |
| GRE   | 3 |  8 | 12 | 4 |
| TOEFL | 4 | 12 | 16 | 5 |
| IELTS | 4 | 16 | 16 | 5 |

---

## DMAT — d-MAT (Digital Master Test)

Platform flagship. Core module measures general study aptitude via three timed subtests; the General Academic module is a subject-specific module. Each core subtest = 20 items in 25 minutes.

| Subject | Chapters (question/topic types) |
|---------|----------------------------------|
| Figure Sequences | Movement Rules; Colour Rules; Orientation & Rotation Rules; Matrix Series Continuation |
| Mathematical Equations | Systems of Equations; Integer Solutions; Substitution & Elimination |
| Latin Squares | Grid Completion; Constraint Satisfaction; Deductive Elimination |
| General Academic Module | Reading Comprehension; Quantitative Problem Solving; Data & Diagram Interpretation; Critical Reasoning |

Mocks: full (Core + General Academic, ~180 min, ~90 items) plus one per subtest/module (Figure Sequences 20q/25m, Mathematical Equations 20q/25m, Latin Squares 20q/25m, General Academic ~40q/90m). Full-mock and General-Academic item counts are seed estimates (official item counts published per subtest only).

## GMAT — GMAT Focus Edition

Three equally weighted sections, 64 questions in 2h15m (135 min). Adaptive. Sentence Correction and Geometry were removed in the Focus Edition; Data Insights is now a full section.

| Subject | Time / Qs | Chapters |
|---------|-----------|----------|
| Quantitative Reasoning | 45 min / 21 | Arithmetic; Algebra; Word Problems; Number Properties |
| Verbal Reasoning | 45 min / 23 | Reading Comprehension; Critical Reasoning |
| Data Insights | 45 min / 20 | Data Sufficiency; Multi-Source Reasoning; Table Analysis; Graphics Interpretation; Two-Part Analysis |

Mocks: full (135 min / 64q) + one section mock per subject.

## GRE — GRE General Test

Shorter GRE (since Sept 2023): 5 sections, 55 questions, ~1h58m. Analytical Writing is always first (single "Analyze an Issue" task); Verbal and Quant each run as two subsections.

| Subject | Time / Qs | Chapters |
|---------|-----------|----------|
| Verbal Reasoning | 41 min / 27 | Reading Comprehension; Text Completion; Sentence Equivalence |
| Quantitative Reasoning | 47 min / 27 | Arithmetic; Algebra; Geometry; Data Analysis |
| Analytical Writing | 30 min / 1 task | Analyze an Issue |

Mocks: full (~118 min / 55q) + one section mock per subject.

## TOEFL — TOEFL iBT (January 2026 format)

Reflects the **new adaptive TOEFL iBT** launched 21 Jan 2026 (~2 hours total). Section item counts/timing vary as the test adapts; values below are the ETS reference figures. Section set (Reading, Listening, Speaking, Writing) is unchanged; task types are the 2026 ones.

| Subject | Time / Items | Chapters (task types) |
|---------|--------------|-----------------------|
| Reading | ~30 min / 50 | Complete the Words; Read in Daily Life; Read an Academic Passage |
| Listening | ~29 min / 47 | Listen and Choose a Response; Listen to a Conversation; Listen to an Announcement; Listen to an Academic Talk |
| Speaking | ~8 min / 11 | Listen and Repeat; Take an Interview |
| Writing | ~23 min / 12 | Build a Sentence; Write an Email; Write for an Academic Discussion |

Mocks: full (~120 min, ~120 items) + one section mock per subject.

## IELTS — IELTS Academic

Four sections, 2h45m. Listening and Reading are 40 questions each; Writing has two tasks; Speaking is a 3-part face-to-face interview.

| Subject | Time / Qs | Chapters (task types) |
|---------|-----------|-----------------------|
| Listening | 30 min / 40 | Multiple Choice; Matching; Plan/Map/Diagram Labelling; Form/Note/Table/Flow-chart/Summary Completion; Sentence Completion |
| Reading | 60 min / 40 | Multiple Choice; Identifying Information (T/F/NG); Matching Headings; Matching Information & Features; Completion tasks; Short-answer Questions |
| Writing | 60 min / 2 tasks | Task 1 — Report (Graph/Table/Chart/Diagram); Task 2 — Essay |
| Speaking | 11–14 min / 3 parts | Part 1 — Interview; Part 2 — Long Turn (Cue Card); Part 3 — Discussion |

Mocks: full (~165 min) + one section mock per subject.

---

## Sources (official)

- **d-MAT** — <https://www.d-mat.de/en/> and the official dMAT preparatory materials (d-mat.de). GMAC-style aptitude test administered by ITB Consulting for German master's admissions.
- **GMAT Focus Edition** — GMAC / mba.com Exam Structure: <https://www.mba.com/exams/gmat-exam/about/exam-structure>
- **GRE General Test** — ETS Test Structure: <https://www.ets.org/gre/test-takers/general-test/prepare/test-structure.html>
- **TOEFL iBT (2026)** — ETS Test Content: <https://www.ets.org/toefl/test-takers/ibt/about/content.html>
- **IELTS Academic** — IELTS.org Academic test format: <https://ielts.org/take-a-test/test-types/ielts-academic-test>

_Note: Test formats change. TOEFL iBT was substantially revised on 21 Jan 2026 (adaptive Reading/Listening, new task types) — figures above reflect that revision. Verify against the official source before each admissions cycle._
