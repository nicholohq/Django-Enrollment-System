# E1 — Functional Requirements Documentation

Controlling reference: the instructor's transcribed requirements (groups A–G).
Status values: **Implemented** (working user-facing workflow + server-side
behavior), **Partial** (works with a documented gap), **Not Implemented**.
A database model alone is never counted as complete.

Status key for the actor/UI: paths are Django URL names. Roles use the
server-side permission mixins/decorators in `accounts/permissions.py`.

---

## A. Student Registration

### FR-A1 — Student personal, academic, and contact information
- **Description:** Register a student with personal, contact, and academic details.
- **Expected:** Create a student account capturing name, contact info, student number, curriculum, year level.
- **Actual:** Registrar creates accounts via `people:student_create`; `accounts.services.create_student_account` atomically creates the `User` (first/last/middle name, email, phone, address) and the `Student` profile (student_number, curriculum, year_level). Password validated via Django validators.
- **Page/model/service:** `accounts/people_views.py: StudentCreateView`; `accounts/services.py: create_student_account`; models `accounts.User`, `academics.Student`.
- **Inputs:** account form (username, password, names, contact, student_number, curriculum, year_level). **Outputs:** persisted Student + redirect to detail.
- **Status:** **Implemented.**
- **Evidence:** `accounts/tests.py` (people/account tests); live HTTP: Registrar can open `/people/students/add/`.
- **Limitations:** Registration is Registrar-performed (no public self-signup — matches the role design).

### FR-A2 — Unique student ID
- **Description:** Each student has a unique student ID.
- **Expected:** System guarantees unique student IDs.
- **Actual:** `student_number` is **entered by the Registrar** and uniqueness is enforced by DB constraint `uq_student_student_number`. It is **not auto-generated**.
- **Page/model/service:** `academics.Student.student_number` (UniqueConstraint).
- **Inputs:** student_number (manual). **Outputs:** rejected on duplicate.
- **Status:** **Partial** (uniqueness guaranteed; automatic generation not implemented — deferred enhancement).
- **Evidence:** model constraint; account tests cover duplicate rejection.
- **Limitations:** No auto-ID generator.

### FR-A3 — Student record retrieval and updates
- **Description:** Retrieve and update student information.
- **Actual:** `people:student_list` / `student_detail` (Registrar + Administrator read) and `people:student_update` (`update_student_profile`, Registrar).
- **Page/model/service:** `people_views.StudentListView/DetailView/StudentUpdateView`; `update_student_profile`.
- **Status:** **Implemented.** **Evidence:** account tests; HTTP 200 on list/detail for Registrar/Admin.

---

## B. Subject and Curriculum Management

### FR-B1 — Course creation and management
- **Actual:** Registrar create/update courses via `academics:course_create` / `course_update`. **No delete UI** (FKs are `PROTECT`); `is_active` acts as a soft-disable, and the Django admin can edit.
- **Page/model/service:** `academics/views.py: Course*View`; model `academics.Course`.
- **Status:** **Partial** (create/update implemented; course deletion/deactivation workflow deferred).
- **Evidence:** `academics/tests.py`.

### FR-B2 — Program and year-level relationships
- **Actual:** `Program` belongs to a `College`; `CurriculumCourse` places each course at a `year_level` + `recommended_semester` within a curriculum.
- **Model:** `academics.Program`, `academics.CurriculumCourse`.
- **Status:** **Implemented.** **Evidence:** academics tests; seed catalog.

### FR-B3 — Curriculum management
- **Actual:** Registrar CRUD for `Curriculum` (`academics:curriculum_*`) and `CurriculumCourse` placements.
- **Status:** **Implemented.**

### FR-B4 — Prerequisites
- **Actual:** `CoursePrerequisite` CRUD (`academics:course_prerequisite_*`); enforced at enrollment (see FR-C2). Self-prerequisite blocked by check constraint.
- **Status:** **Implemented.** **Evidence:** enrollment prerequisite tests.

---

## C. Enrollment Management

### FR-C1 — Course selection based on curriculum
- **Actual:** `enrollment.services.enroll_in_section` rejects a course not in the student's curriculum (`CurriculumCourse` lookup). Enrollment is Registrar-managed; the student portal is read-only.
- **Page/model/service:** `enrollment/views.py: EnrollmentAddSectionView`; `enroll_in_section`.
- **Status:** **Implemented.** **Note:** enrollment is not gated by the course's recommended year level (a deferred soft-warning enhancement).
- **Evidence:** enrollment tests (curriculum check); seed scenarios.

### FR-C2 — Prerequisite validation
- **Actual:** `missing_prerequisites` / `passed_course_ids` require each prerequisite to be a prior-term `COMPLETED` + `PASSED` detail; enforced in `enroll_in_section`.
- **Status:** **Implemented.** **Evidence:** prerequisite tests; seed scenario (S11 rejected).

### FR-C3 — Schedule-conflict validation
- **Actual:** Student same-day/overlap conflict (`enroll_in_section`), instructor conflict and **room conflict** (`scheduling.services.create_section`/`update_section`).
- **Status:** **Implemented.** **Evidence:** `scheduling/tests.py`, `scheduling/tests_room.py`, enrollment tests; seed scenario (S12 schedule conflict).

### FR-C4 — Enrollment records (courses, sections, semester)
- **Actual:** `Enrollment` (student + term) with `EnrollmentDetail` per section (course derived via section); DRAFT → CONFIRMED lifecycle; one enrollment per student/term.
- **Status:** **Implemented.** **Evidence:** enrollment confirmation tests; seed (20 enrollments).

---

## D. Fee Assessment and Payment

### FR-D1 — Automatic fee calculation
- **Actual:** `FeeRule` engine (`finance.services.compute_fee_breakdown`) with category-aware stacking and COURSE > PROGRAM > GENERAL precedence; PER_UNIT / FIXED; Decimal arithmetic. A DRAFT assessment is auto-created when an enrollment is confirmed (via `EnrollmentConfirmView`).
- **Page/model/service:** `finance/services.py`; models `FeeRule`, `AssessmentVersion`, `AssessmentLine`.
- **Status:** **Implemented.** **Evidence:** `finance/tests_finance_b.py` (fee computation suite); seed fee rules.
- **Limitations:** Fee amounts are **fictional DEMO** values, not official HTU fees.

### FR-D2 — Detailed assessment breakdown
- **Actual:** Itemized `AssessmentLine` rows (category, description, qty, rate, amount) shown on the cashier/registrar assessment detail page (`finance:assessment_detail`), with totals, amount paid, and balance.
- **Status:** **Implemented.** **Evidence:** finance tests; live HTTP (cashier detail 200).

### FR-D3 — Payment recording
- **Actual:** Cashier records payments (`finance:record_payment` → `record_payment`); methods CASH/CHECK/BANK_TRANSFER/ONLINE/E_WALLET; states PENDING/RECEIVED/CANCELLED/REVERSED; unique receipt numbers; printable receipt (`finance:receipt`).
- **Status:** **Implemented.** **Evidence:** finance payment/allocation tests; live HTTP (record payment page 200).

### FR-D4 — Balance calculation and updates
- **Actual:** One authoritative service (`assessment_balance`): current-version total − received allocations across the assessment's versions − approved credits − approved scholarship + approved refunds. Received payments carry forward across revisions (allocations are never moved). Pending/cancelled/reversed never count; legacy assessments use a compatible fallback.
- **Status:** **Implemented.** **Evidence:** finance balance tests; seed scenario balances verified (e.g., S06 2,950; S07 0; S08 reversed unchanged).

---

## E. Class Scheduling

### FR-E1 — Day, time, room, and instructor assignments
- **Actual:** `Section` carries day_of_week, start/end time, a normalized `Room` FK (+ legacy `room_code`), and an optional `Instructor`. Single weekly meeting per section (documented design).
- **Status:** **Implemented.**

### FR-E2 — Classroom conflict prevention
- **Actual:** `_room_has_conflict` (same term/room/day/overlap, excluding CANCELLED and self) enforced in `create_section`/`update_section`.
- **Status:** **Implemented.** **Evidence:** `scheduling/tests_room.py`.

### FR-E3 — Instructor conflict prevention
- **Actual:** `_instructor_has_conflict` enforced in the section services.
- **Status:** **Implemented.** **Evidence:** scheduling tests.

### FR-E4 — Available class sections
- **Actual:** During enrollment, `AddSectionForm(term=...)` lists the term's sections; the service rejects TBA/closed/over-capacity/conflicting choices.
- **Status:** **Implemented.**

---

## F. Reports

### FR-F1 — Enrolled students by course and year level
- **Actual:** `reports:enrolled` — filters by term/college/program/course/year/section; excludes cancelled; no duplicate rows. Registrar + Administrator.
- **Status:** **Implemented.** **Evidence:** `accounts/tests_reports.py`.

### FR-F2 — Total enrollment per semester
- **Actual:** `reports:semester` — distinct students vs active enrollment records per term, with college/program breakdown; excludes cancelled.
- **Status:** **Implemented.** **Evidence:** reports tests.

### FR-F3 — Collection reports
- **Actual:** `reports:collection` — RECEIVED payments by method with totals; scholarship funding shown separately; filters by term/method/date range. Cashier + Administrator.
- **Status:** **Implemented.** **Evidence:** reports tests.

### FR-F4 — PDF or Excel export
- **Actual:** **CSV export** for all three reports (stdlib `csv`, UTF-8 BOM, formula-injection-safe) and **print-friendly HTML** pages with a Print button for the browser's **Save as PDF**.
- **Status:** **Implemented** (meets "PDF or Excel" via CSV + browser print). **Limitations:** no native `.xlsx` and no server-side PDF engine (deliberate — no new dependency).
- **Evidence:** reports CSV tests; live HTTP (CSV 200).

---

## G. User Roles and Access

### FR-G1–G5 — Administrator, Registrar, Cashier, Instructor, Student
- **Actual:** `accounts.User.Role` defines all five; role-aware login routes each to its dashboard. Registrar manages academic/people/section/enrollment data and finalizes assessments; Cashier records payments; Administrator approves finance adjustments/scholarships/reversals and manages fee rules/policy; Instructor and Student have read-oriented access.
- **Status:** **Implemented.** (Instructor and Cashier dashboards were placeholders pre-B; the Cashier now has a full finance workflow. Instructor roster/grading remains out of scope.)

### FR-G6 — Unique credentials and role-specific permissions
- **Actual:** Unique usernames (AbstractUser); password validators; **server-side** authorization via mixins/decorators on every view (not hidden links). Django `/admin/` additionally requires `is_staff` + Administrator role.
- **Status:** **Implemented.** **Evidence:** permission tests across apps; live HTTP role matrix (cashier/registrar/admin/student).

---

## Enhancements beyond the instructor requirements

These were added for financial integrity and realism and are **not** part of the
base A–G requirements:

- **Assessment versioning** (`AssessmentVersion`/`AssessmentLine`) with immutable
  finalized snapshots and revisions.
- **Explicit payment allocation** (`PaymentAllocation`) for traceability.
- **Adjustments** (credit/refund/reversal/correction) with an approval trail and
  **separation of duties** (creator ≠ approver).
- **Scholarship awards** kept distinct from cash.
- **Configurable finance policy** (`FinancePolicy`) and an append-only
  **finance audit log**.
- **Reconciliation** data model + service (no dedicated UI yet).
- **Normalized Room** entity with double-booking prevention.

See `requirements_traceability.md` for the matrix and
`database_documentation.md` for the schema and limitations.
