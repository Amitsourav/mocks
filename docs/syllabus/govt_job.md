# Government-Job Competitive Exams — Syllabus Seed

Seed reference for the `govt_job` group. The platform shares **sectional** mocks across all
government-job exams at the **category (JOB)** level, while each exam adds its own
exam-specific subjects. Machine-readable data lives in [`govt_job.json`](./govt_job.json).

Code convention (UPPER_SNAKE, globally unique):
- `JOB_*` — cross-exam shared sections attached to category **JOB**
- `IBPS_*`, `SSC_*`, `RRB_*`, `UPSC_*`, `PCS_*` — exam-specific subjects/chapters/skills

---

## Category-shared subjects (category `JOB`)

Cross-exam sections usable by Bank / SSC / Railway aspirants alike. Each has a
subject-scope sectional mock (`category_shared_mocks`).

| Code | Section | Chapters | Skills |
|------|---------|----------|--------|
| `JOB_ENGLISH` | English Language | Grammar, Reading Comprehension, Verbal Ability, Error Detection & Sentence Correction | Vocabulary, Cloze Test, Para/Sentence Rearrangement |
| `JOB_QUANT` | Quantitative Aptitude | Number System, Arithmetic, Data Interpretation, Algebra/Geometry/Mensuration | Simplification & Approximation, Speed Calculation, Word Problems |
| `JOB_REASONING` | Reasoning Ability | Verbal Reasoning, Non-Verbal Reasoning, Puzzles & Seating Arrangement, Analytical Reasoning | Syllogism, Coding-Decoding, Blood Relations & Directions |
| `JOB_GA` | General Awareness | Current Affairs, Static GK, Indian Polity, Indian & World Geography | History & Culture, Sports/Awards/Books |

Shared sectional mocks: English (20 min / 30 Q), Quant (20 / 30), Reasoning (20 / 30),
General Awareness (15 / 30) — all `difficulty: medium`.

---

## Per-exam structure (one popular variant each)

### BANK — IBPS PO (`IBPS_PO`)
Official 3-stage flow: Prelims → Mains → Interview.
- **Prelims** (100 Q / 100 marks / 60 min): English Language, Reasoning Ability, Quantitative Aptitude — all covered by shared sections.
- **Mains** adds: Reasoning & Computer Aptitude, General/Economy/Banking Awareness, English, Data Interpretation, Descriptive.
- Exam-specific subjects: `IBPS_BANKING_AWARENESS` (Banking & Financial Awareness), `IBPS_COMPUTER` (Computer Aptitude).
- Full mock: **IBPS PO — Prelims Full Mock** (60 min / 100 Q / medium).

### SSC — SSC CGL (`SSC_CGL`)
- **Tier I** (100 Q / 200 marks / 60 min, four sections of 25 Q each): General Intelligence & Reasoning, General Awareness, Quantitative Aptitude, English Comprehension — the four map onto the shared sections.
- Exam-specific subjects capture SSC's emphasis: `SSC_GENERAL_SCIENCE` (General Science within GA), `SSC_STATIC_AWARENESS` (static GK, polity, schemes, current affairs).
- Full mock: **SSC CGL — Tier I Full Mock** (60 min / 100 Q / medium).

### RAILWAY — RRB NTPC (`RRB_NTPC`)
- **CBT 1** (100 Q / 100 marks / 90 min): General Awareness (40 Q), Mathematics (30 Q), General Intelligence & Reasoning (30 Q) — Mathematics/Reasoning map to shared Quant/Reasoning.
- Exam-specific subjects: `RRB_GENERAL_SCIENCE` (Physics/Chemistry/Life Science, Class-10 level), `RRB_GENERAL_AWARENESS` (current affairs, Indian Railways & transport, static GK).
- Full mock: **RRB NTPC — CBT 1 Full Mock** (90 min / 100 Q / medium).

### UPSC — Civil Services Prelims (`CSE_PRELIMS`)
Two papers, 200 marks each, same day; CSAT is qualifying (33%). 1/3 negative marking.
- Exam-specific subjects:
  - `UPSC_GS1` — **General Studies Paper I**: History & Indian National Movement, Indian & World Geography, Indian Polity & Governance, Economic & Social Development, Environment/Ecology/Biodiversity, General Science & Technology, Current Events.
  - `UPSC_CSAT` — **CSAT (GS Paper II)**: Comprehension, Logical Reasoning & Analytical Ability, Basic Numeracy (Class X), Data Interpretation, Decision Making & Problem Solving.
- Full mock: **UPSC CSE Prelims — GS Paper I Full Mock** (120 min / 100 Q / hard).

### STATE_PCS — Generic State PCS Prelims (`PCS_PRELIMS`)
Mirrors the UPSC prelims pattern (GS + CSAT), adapted for state-level static content.
- Exam-specific subjects:
  - `PCS_GS` — **General Studies (Prelims)**: national History/Polity/Economy, state-specific History/Geography/Culture, Geography, Environment & General Science, current affairs.
  - `PCS_CSAT` — **CSAT (Aptitude)**: Comprehension, Logical Reasoning, Quantitative Aptitude (Class X), Data Interpretation.
- Full mock: **State PCS Prelims — GS Paper I Full Mock** (120 min / 150 Q / medium).

---

## Sources (official)

- IBPS PO/MT — <https://www.ibps.in/> (official notifications & exam pattern)
- SSC CGL — <https://ssc.gov.in/> (Tier I scheme of examination)
- RRB NTPC — <https://www.rrbcdg.gov.in/> (CBT 1 exam pattern)
- UPSC Civil Services Prelims — <https://upsc.gov.in/> (GS Paper I & CSAT Paper II syllabus)

> Marks/question counts reflect the exam patterns published for the recent (2025) cycles and
> should be re-verified against the current-year official notification before each seeding run,
> as boards periodically revise section weightage.
