# Study-in-India Exam Syllabi (seed data)

Machine-readable data: [`study_india.json`](./study_india.json) — `group: study_india`.

Maps to `mock_db.catalog_exams.code` values **JEE_MAINS, JEE_ADVANCED, CAT, NEET**
(seeded in `migrations/0005_seed_registration_catalog.sql`, category `STUDY_INDIA`).

Code convention: all `code` values are `UPPER_SNAKE`, globally unique, exam-prefixed
(`JEEM_` JEE Main, `JEEA_` JEE Advanced, `CAT_`, `NEET_`). Chapter codes use a subject
segment (`_PHY_`, `_CHE_`, `_MAT_`, `_BOT_`, `_ZOO_`, `_VARC_`, `_DILR_`, `_QA_`); skill
codes carry a `_SKL_` segment to guarantee they never collide with chapter codes.

## Coverage summary

| Exam | Subjects (chapters) | Skills | Mocks |
|------|--------------------|--------|-------|
| JEE_MAINS | Physics (20), Chemistry (20), Mathematics (14) | 13 | full×1, subject×3, chapter×6 |
| JEE_ADVANCED | Physics (20), Chemistry (29), Mathematics (11) | 13 | full×1, subject×3, chapter×6 |
| CAT | VARC (6), DILR (10), QA (14) | 11 | full×1, subject×3, chapter×6 |
| NEET | Physics (20), Chemistry (20), Botany (19), Zoology (13) | 20 | full×1, subject×4, chapter×5 |

Every mock's `subject_code` / `chapter_code` resolves to a code defined in the same exam
(validated at generation time), and all 284 codes are globally unique.

## Per-exam notes

### JEE Main (`JEE_MAINS`)
- Source of truth: official NTA "Syllabus for JEE (Main) 2025" PDF, Paper 1 (B.E./B.Tech.).
- Physics = 20 units (Unit 20 = Experimental Skills). Mathematics = 14 units.
  Chemistry = 20 units grouped Physical (1–8), Inorganic (9–12), Organic (13–20).
- Chapter names are the exact official unit titles. Actual paper: 75 questions,
  300 marks, 180 min → reflected in the full mock; subject mocks use 25 questions (20 MCQ + 5 NVT).

### JEE Advanced (`JEE_ADVANCED`)
- Source of truth: official jeeadv.ac.in (IIT Kanpur) JEE Advanced 2025 syllabus PDF.
- The official document organises each subject into broad topic *sections*
  (Physics: General, Mechanics, Thermal Physics, Electricity & Magnetism, Optics,
  Modern Physics; Chemistry: Physical / Inorganic / Organic groups; Mathematics:
  Algebra, Matrices, Probability, Trigonometry, Analytical Geometry, Differential
  Calculus, Integral Calculus, Vectors). These sections are expanded here into the
  standard chapter-level subdivisions that fall within them, for finer mock targeting.
- Relative to JEE Main, the Advanced set **excludes** Electromagnetic Waves and
  Electronic Devices/Semiconductors (not in the Advanced syllabus) and adds
  Advanced-only depth (e.g. surface chemistry, nuclear chemistry, extractive metallurgy).

### CAT (`CAT`)
- The IIMs (iimcat.ac.in) **do not publish an official topic-wise syllabus**. The
  three sections — VARC, DILR, QA — and the exam pattern (3 sections, 40 min each,
  +3/−1 marking) are official; the topic areas listed as "chapters" are compiled from
  the last several years of actual CAT papers and are widely-used preparation areas,
  not an official enumeration.
- Full mock: 120 min / 66 questions (approx. recent pattern: VARC 24, DILR 22, QA 22).

### NEET (`NEET`)
- Source of truth: official NTA/NMC "Syllabus for NEET UG 2025" PDF.
- Physics (20 units) and Chemistry (20 units) chapter names are the exact official unit
  titles. The official document lists **Biology as 10 combined units**; here Biology is
  split into **Botany** and **Zoology** subjects with NCERT-chapter-level names, matching
  how NEET is actually administered (Biology = 90 questions split Botany 45 + Zoology 45).
  This split follows the standard NEET Botany/Zoology convention and does not change the
  underlying official topic coverage.
- Full mock: 200 min / 180 questions (all four subjects).

## Sources
- **JEE Main** — NTA official syllabus: https://jeemain.nta.nic.in/document/syllabus-for-jee-main-2025/
  (PDF: `cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2024/10/2024102841.pdf`)
- **JEE Advanced** — IIT Kanpur official syllabus: https://jeeadv.ac.in (JEE Advanced 2025 syllabus PDF)
- **NEET UG** — NTA/NMC official syllabus: https://nta.ac.in/Download/Notice/Notice_20241230193629.pdf
- **CAT** — IIM CAT: https://iimcat.ac.in (official pattern only; topic areas compiled from past papers)
