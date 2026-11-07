# E3 — Database and Technology Documentation (Database)

MySQL schema managed entirely by Django migrations (the ORM is the source of
truth). **25 business tables** across five apps, plus Django framework tables
(auth/permissions, sessions, content types, admin log, migrations). All
application primary keys are integer `AutoField`; all cross-row foreign keys use
`on_delete=PROTECT` for historical integrity, except two deliberate exceptions
noted below (`Assessment.current_version` and `FinanceAuditLog.actor` →
`SET_NULL`). Monetary fields are `DecimalField` (never float).

The final ERD (Mermaid) and its differences from the original pre-Milestone
`erd_artifacts/` are in [erd/ERD_NOTES.md](erd/ERD_NOTES.md).

---

## 1. Entities by app

### accounts
- **User** (`app_user`) — extends Django `AbstractUser`. Adds `middle_name`,
  `phone`, `address`, and `role` (ADMINISTRATOR/REGISTRAR/CASHIER/INSTRUCTOR/
  STUDENT). PK `id`. Unique: `username` (AbstractUser).

### academics (9 tables)
- **College** (`college`) — `college_code` (unique), `name`, `is_active`.
- **Program** (`program`) — FK→College; `program_code` (unique), `name`,
  `is_active`.
- **Curriculum** (`curriculum`) — FK→Program; `curriculum_code`,
  `effective_year` (CHECK ≥1). Unique `(program, curriculum_code)`.
- **Course** (`course`) — `course_code` (unique), `title`, `units`
  (Decimal, CHECK >0), `is_active`.
- **CurriculumCourse** (`curriculum_course`) — FK→Curriculum, FK→Course;
  `year_level` (CHECK ≥1), `recommended_semester` (CHECK ≥1), `course_category`.
  Unique `(curriculum, course)`.
- **CoursePrerequisite** (`course_prerequisite`) — FK→Course `prerequisites`,
  FK→Course `required_for`. Unique `(course, prerequisite_course)`; CHECK
  not-self.
- **AcademicTerm** (`academic_term`) — `academic_year`, `semester_number`
  (CHECK ≥1), `start_date`, `end_date` (CHECK end ≥ start), `enrollment_open`.
  Unique `(academic_year, semester_number)`.
- **Student** (`student`) — OneToOne→User; FK→Curriculum; `student_number`
  (unique), `year_level` (CHECK ≥1).
- **Instructor** (`instructor`) — OneToOne→User; `employee_number` (unique).

### scheduling (2 tables)
- **Room** (`room`) — `room_code` (unique), `name`, optional `building`,
  optional `capacity` (CHECK null or ≥1), `is_active`. *(Milestone A)*
- **Section** (`section`) — FK→Course, FK→AcademicTerm, nullable FK→Instructor,
  nullable FK→Room; `section_code`, `capacity` (CHECK ≥1), legacy free-text
  `room_code`, `day_of_week` (0–6, nullable=TBA), `start_time`, `end_time`,
  `status` (OPEN/CLOSED/CANCELLED). Unique `(course, term, section_code)`;
  CHECK end>start; CHECK day 0–6.

### enrollment (2 tables)
- **Enrollment** (`enrollment`) — FK→Student, FK→AcademicTerm;
  `enrollment_date`, `status` (DRAFT/CONFIRMED/CANCELLED). Unique
  `(student, term)`.
- **EnrollmentDetail** (`enrollment_detail`) — FK→Enrollment, FK→Section;
  `status` (ENROLLED/DROPPED/COMPLETED), `final_grade` (Decimal, CHECK in the
  PSU 1.00–5.00 set or null), `result_status`, `recorded_at`. Unique
  `(enrollment, section)`. Course is derived via `section.course`.

### finance (11 tables) — *Milestone B*
- **FeeRule** (`fee_rule`) — `name`, `category`, `scope`
  (COURSE/PROGRAM/GENERAL), nullable FK→Course, nullable FK→Program,
  `computation` (PER_UNIT/FIXED), `amount` (Decimal), optional `year_level`,
  optional FK→AcademicTerm, `is_active`, `is_demo`. CHECK amount ≥0; CHECK
  scope/target consistency.
- **Assessment** (`assessment`) — OneToOne→Enrollment; `total_amount`, `status`
  (DRAFT/FINALIZED) — compatibility mirrors of the current version; FK→
  AssessmentVersion `current_version` (**SET_NULL**); `needs_review`. CHECK
  total ≥0.
- **AssessmentVersion** (`assessment_version`) — FK→Assessment; `version_number`,
  `status` (DRAFT/FINALIZED/SUPERSEDED), `total_amount`, `created_by`/
  `finalized_by` (FK→User), `revision_reason`. Unique `(assessment,
  version_number)`; CHECK total ≥0.
- **AssessmentLine** (`assessment_line`) — FK→AssessmentVersion; `fee_category`,
  `description`, `quantity`, `unit_amount`, `line_total` (CHECK ≥0), nullable
  FK→FeeRule + snapshot (`fee_rule_name`, `fee_rule_scope`).
- **Payment** (`payment`) — FK→Assessment, FK→User `received_by`;
  `receipt_number` (unique), `amount` (CHECK >0), `method`
  (CASH/CHECK/BANK_TRANSFER/ONLINE/E_WALLET), `status`
  (PENDING/RECEIVED/CANCELLED/REVERSED), `reference_note`, `reversed_at`.
- **PaymentAllocation** (`payment_allocation`) — FK→Payment, FK→
  AssessmentVersion; `amount` (CHECK >0), `created_by`.
- **Adjustment** (`adjustment`) — type (CREDIT/REFUND/REVERSAL/CORRECTION),
  `amount` (CHECK >0), `reason`, nullable FK→Assessment/Version/Payment,
  `created_by`/`approved_by` (FK→User), `status` (PENDING/APPROVED/REJECTED).
  **CHECK `approved_by` IS NULL OR ≠ `created_by`** (separation of duties).
- **ScholarshipAward** (`scholarship_award`) — FK→Student, `sponsor`, `amount`
  (CHECK >0), nullable FK→Assessment/Version, `status`
  (PENDING/APPROVED/APPLIED/CANCELLED), `created_by`/`approved_by`, `is_demo`.
  Same creator≠approver CHECK.
- **FinancePolicy** (`finance_policy`) — single row; `previous_term_balance`
  (WARN/BLOCK/OFF), `overpayment_becomes_credit`,
  `credit_application_requires_approval`, `refund_requires_approval`.
- **Reconciliation** (`reconciliation`) — nullable FK→AcademicTerm, `method`,
  period, `recorded_total`/`verified_total`/`discrepancy`, `status`,
  `performed_by`. *(data model + service; no UI)*
- **FinanceAuditLog** (`finance_audit_log`) — `actor` (FK→User, **SET_NULL**),
  `action`, `detail`, `created_at`. Append-only.

---

## 2. Keys, constraints, referential integrity

- **Primary keys:** integer surrogate `AutoField` on every table.
- **Foreign keys:** `PROTECT` everywhere (cannot delete a parent while
  referenced) — preserves historical records; the two `SET_NULL` exceptions keep
  the audit log and the assessment's current-version pointer from blocking
  legitimate deletions.
- **Unique constraints:** natural keys on all catalog/identity rows (college,
  program, curriculum+code, course, curriculum+course, term year+sem,
  student_number, employee_number, room_code, section course+term+code,
  enrollment student+term, enrollment_detail enrollment+section, payment
  receipt_number, assessment_version assessment+number).
- **Check constraints:** positive units/capacity/amounts; valid PSU grade set;
  time range (end>start); day-of-week 0–6; fee-rule scope/target consistency;
  **adjustment/scholarship approver ≠ creator**.
- **Cross-row business rules** (not expressible as row constraints) live in
  service modules with `transaction.atomic` and `select_for_update`
  (prerequisites, capacity, schedule/room/instructor conflicts, fee computation,
  finalization, allocation, balance).

---

## 3. Normalization

- **1NF:** all columns atomic; no repeating groups (e.g., a student's multiple
  sections are separate `EnrollmentDetail` rows, not list columns).
- **2NF:** no partial dependency on part of a composite key — surrogate integer
  PKs are used throughout, and attributes depend on the whole row (e.g.,
  `CurriculumCourse.year_level` depends on the specific curriculum+course row).
- **3NF:** no transitive dependencies — e.g., a section's course **units** live
  only on `Course` (not copied onto `Section`); a student's personal name/contact
  live only on `User` (not duplicated on `Student`/`Instructor`); a payment's
  course list is not stored on `Payment` (reached via assessment→enrollment).
  Derived values (assessment balance, amount paid) are **computed by services**,
  not stored, avoiding update anomalies. The compatibility mirrors
  `Assessment.total_amount`/`status` are the one intentional denormalization,
  kept consistent with the current version by the finalize/revise services.

**Milestone A (Room):** `room_code` was a free-text attribute on `Section`
(an embedded, unnormalized room identity). It is normalized into a `Room` entity
with its own key; `Section.room` is the authoritative FK, and `room_code` is
retained only for display/compatibility during the transition.

---

## 4. Finance design (accurate description)

**Assessment versioning.** `Assessment` stays 1-to-1 with `Enrollment` (the
enrollment-level parent). Each assessment owns ordered **immutable**
`AssessmentVersion` snapshots; `Assessment.current_version` points at the one
version that determines the current amount due. Finalizing sets a version
FINALIZED (immutable); a **revision** supersedes the current version and creates
a new DRAFT version — old versions and their allocations are **never edited or
summed into the current total**.

**Itemized lines.** Each version has `AssessmentLine` rows produced by the fee
engine, with a snapshot of the source fee rule so the figure remains explainable
even if the rule later changes.

**Payment allocation.** Money is linked to a specific version through explicit
`PaymentAllocation` rows (never implicitly), so a payment is traceable and never
double-counted. On revision, allocations stay on their original version (they are
never moved); prior RECEIVED payments carry forward into the balance because the
paid amount is summed across all of the assessment's versions.

**Authoritative balance.** `assessment_balance` =
`current_version.total − received allocations across the assessment's versions −
approved credits − approved/applied scholarship + approved refunds`. PENDING/
CANCELLED/REVERSED payments never count. Legacy assessments (no version) use a
compatible `total_amount − RECEIVED payments` fallback.

**Integrity controls.** Adjustments and scholarships require approval with a
database-enforced **creator ≠ approver** rule; reversals mark a payment REVERSED
and record an approved REVERSAL adjustment; an append-only `FinanceAuditLog`
records finance actions.

---

## 5. Verified limitations

- **Legacy assessments on the disposable DB:** two assessments (demo students
  S06/S07) remain flat-total legacy records from an earlier seed and use the
  fallback balance; a fresh seed makes all assessments fee-rule-computed.
- **Previous-term balance policy:** `FinancePolicy.previous_term_balance` is
  WARN by default, but there is **no enrollment-time enforcement hook** — the
  outstanding-balance data exists for reporting, not for blocking.
- **Reconciliation:** data model + `run_reconciliation` service exist, but there
  is **no dedicated reconciliation UI** (admin can view records read-only).
- **Overpayment:** retained as an unallocated payment amount (balance floored at
  0); converting it to a formal CREDIT is a manual adjustment step.
- **GUI browser testing** was unavailable in the dev environment (localhost not
  reachable by the Chrome automation extension); verified via automated tests
  and HTTP-session checks instead.
- **Partial instructor requirements:** manual student-ID entry (FR-A2), no course
  delete UI (FR-B1); exports are CSV + browser print-to-PDF (no native xlsx/
  server PDF). See `functional_requirements.md`.
