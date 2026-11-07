"""Milestone B finance tests: fee rules, assessment lifecycle, payments &
allocations, adjustments/scholarships, balance integrity, and permissions."""

from datetime import time, date, datetime, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from academics.models import (
    AcademicTerm, College, Course, Curriculum, CurriculumCourse, Program, Student,
)
from enrollment.models import Enrollment, EnrollmentDetail
from scheduling.models import Section
from finance.models import (
    Adjustment, Assessment, AssessmentVersion, FeeRule, Payment,
    PaymentAllocation, ScholarshipAward,
)
from finance import services as fs

D = Decimal


class FinanceTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.college = College.objects.create(college_code="FIN-C", name="Finance College")
        cls.program = Program.objects.create(college=cls.college, program_code="FIN-BS", name="Finance Program")
        cls.curriculum = Curriculum.objects.create(program=cls.program, curriculum_code="FIN-CUR", effective_year=2026)
        cls.term = AcademicTerm.objects.create(
            academic_year="2026-2027", semester_number=1,
            start_date="2026-08-01", end_date="2026-12-15", enrollment_open=True)
        cls.course = Course.objects.create(course_code="FIN101", title="Course 1", units=D("3.0"))
        CurriculumCourse.objects.create(
            curriculum=cls.curriculum, course=cls.course, year_level=1,
            recommended_semester=1, course_category="CORE")
        cls.student_user = User.objects.create_user(username="fin_student", password="pass12345", role=User.Role.STUDENT)
        cls.student = Student.objects.create(
            user=cls.student_user, student_number="FIN-0001",
            curriculum=cls.curriculum, year_level=1)
        cls.enrollment = Enrollment.objects.create(
            student=cls.student, term=cls.term, status=Enrollment.Status.CONFIRMED)
        cls.section = Section.objects.create(
            course=cls.course, term=cls.term, section_code="F1", capacity=40,
            day_of_week=0, start_time=time(8, 0), end_time=time(9, 30))
        EnrollmentDetail.objects.create(
            enrollment=cls.enrollment, section=cls.section,
            status=EnrollmentDetail.Status.ENROLLED)
        cls.cashier = User.objects.create_user(username="fin_cashier", password="pass12345", role=User.Role.CASHIER)
        cls.registrar = User.objects.create_user(username="fin_registrar", password="pass12345", role=User.Role.REGISTRAR)
        cls.admin = User.objects.create_user(username="fin_admin", password="pass12345", role=User.Role.ADMINISTRATOR)
        cls.admin2 = User.objects.create_user(username="fin_admin2", password="pass12345", role=User.Role.ADMINISTRATOR)

    def _tuition_general(self, amount="500"):
        return FeeRule.objects.create(
            name="Tuition", category="TUITION", scope="GENERAL",
            computation="PER_UNIT", amount=D(amount), is_demo=True)

    def _misc_general(self, amount="1000"):
        return FeeRule.objects.create(
            name="Miscellaneous", category="MISCELLANEOUS", scope="GENERAL",
            computation="FIXED", amount=D(amount), is_demo=True)


class FeeComputationTests(FinanceTestBase):
    def test_general_per_unit_and_fixed_stack_across_categories(self):
        self._tuition_general("500")   # 3 units * 500 = 1500
        self._misc_general("1000")     # fixed 1000
        result = fs.compute_fee_breakdown(self.enrollment)
        self.assertEqual(result["conflicts"], [])
        total = sum(line["line_total"] for line in result["lines"])
        self.assertEqual(total, D("2500.00"))

    def test_fixed_fee_not_multiplied_by_units(self):
        self._misc_general("1000")
        line = fs.compute_fee_breakdown(self.enrollment)["lines"][0]
        self.assertEqual(line["line_total"], D("1000.00"))
        self.assertIsNone(line["quantity"])

    def test_course_scope_overrides_general_same_category(self):
        self._tuition_general("500")  # general 500/unit
        FeeRule.objects.create(
            name="Special tuition", category="TUITION", scope="COURSE",
            course=self.course, computation="PER_UNIT", amount=D("600"), is_demo=True)
        result = fs.compute_fee_breakdown(self.enrollment)
        # course rule wins for this course: 3 * 600 = 1800 (general suppressed)
        tuition = [l for l in result["lines"] if l["fee_category"] == "TUITION"]
        self.assertEqual(len(tuition), 1)
        self.assertEqual(tuition[0]["line_total"], D("1800.00"))

    def test_conflicting_equal_rules_detected(self):
        self._misc_general("1000")
        self._misc_general("1200")  # two general MISC rules -> conflict
        result = fs.compute_fee_breakdown(self.enrollment)
        self.assertTrue(result["conflicts"])

    def test_inactive_and_wrong_term_rules_ignored(self):
        r = self._tuition_general("500")
        r.is_active = False
        r.save()
        other_term = AcademicTerm.objects.create(
            academic_year="2099-2100", semester_number=1,
            start_date="2099-08-01", end_date="2099-12-15")
        FeeRule.objects.create(name="T2", category="TUITION", scope="GENERAL",
                               computation="PER_UNIT", amount=D("999"), term=other_term)
        self.assertEqual(fs.compute_fee_breakdown(self.enrollment)["lines"], [])


class AssessmentLifecycleTests(FinanceTestBase):
    def test_draft_created_only_for_confirmed_enrollment(self):
        self._tuition_general("500")
        self._misc_general("1000")
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        self.assertEqual(a.status, Assessment.Status.DRAFT)
        self.assertEqual(a.current_version.version_number, 1)
        self.assertEqual(a.total_amount, D("2500.00"))

        draft_enr = Enrollment.objects.create(
            student=self.student, term=AcademicTerm.objects.create(
                academic_year="2027-2028", semester_number=1,
                start_date="2027-08-01", end_date="2027-12-15"),
            status=Enrollment.Status.DRAFT)
        with self.assertRaises(ValidationError):
            fs.create_draft_assessment(enrollment=draft_enr, by=self.registrar)

    def test_finalize_locks_values_and_blocks_on_conflict(self):
        self._tuition_general("500")
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        v = fs.finalize_assessment(assessment=a, by=self.registrar)
        self.assertEqual(v.status, AssessmentVersion.Status.FINALIZED)
        self.assertEqual(v.finalized_by_id, self.registrar.id)
        a.refresh_from_db()
        self.assertTrue(a.is_finalized)
        # second finalize -> rejected
        with self.assertRaises(ValidationError):
            fs.finalize_assessment(assessment=a, by=self.registrar)

    def test_revision_creates_new_version_and_balance_uses_current_only(self):
        self._tuition_general("500")  # total 1500
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))
        # change fee rules, revise
        self._misc_general("1000")  # now total would be 2500
        new_v = fs.revise_assessment(assessment=a, by=self.admin, reason="added misc")
        self.assertEqual(new_v.version_number, 2)
        fs.finalize_assessment(assessment=a, by=self.admin)
        a.refresh_from_db()
        # balance uses ONLY current version total (2500), not 1500+2500
        self.assertEqual(fs.assessment_balance(assessment=a), D("2500.00"))
        self.assertEqual(AssessmentVersion.objects.filter(assessment=a).count(), 2)
        old = AssessmentVersion.objects.get(assessment=a, version_number=1)
        self.assertEqual(old.status, AssessmentVersion.Status.SUPERSEDED)
        self.assertEqual(old.total_amount, D("1500.00"))  # unchanged


class PaymentAllocationTests(FinanceTestBase):
    def _finalized(self):
        self._tuition_general("500")  # total 1500
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        return a

    def test_received_payment_reduces_balance_once(self):
        a = self._finalized()
        fs.record_payment(assessment=a, received_by=self.cashier,
                          receipt_number="R1", amount=D("1000"), method="CASH")
        self.assertEqual(fs.assessment_balance(assessment=a), D("500.00"))
        self.assertEqual(PaymentAllocation.objects.count(), 1)

    def test_pending_and_cancelled_do_not_reduce_balance(self):
        a = self._finalized()
        fs.record_payment(assessment=a, received_by=self.cashier,
                          receipt_number="P1", amount=D("1000"), method="CASH",
                          status=Payment.Status.PENDING)
        fs.record_payment(assessment=a, received_by=self.cashier,
                          receipt_number="C1", amount=D("1000"), method="CASH",
                          status=Payment.Status.CANCELLED)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))

    def test_reversed_payment_no_longer_counts(self):
        a = self._finalized()
        p = fs.record_payment(assessment=a, received_by=self.cashier,
                              receipt_number="R2", amount=D("1000"), method="CASH")
        self.assertEqual(fs.assessment_balance(assessment=a), D("500.00"))
        fs.reverse_payment(payment=p, by=self.admin, reason="error")
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.REVERSED)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))
        self.assertTrue(Adjustment.objects.filter(payment=p, adjustment_type="REVERSAL").exists())

    def test_overpayment_caps_allocation_and_balance_not_negative(self):
        a = self._finalized()
        p = fs.record_payment(assessment=a, received_by=self.cashier,
                              receipt_number="OP", amount=D("2000"), method="CASH")
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        self.assertEqual(p.allocated_amount, D("1500.00"))
        self.assertEqual(p.unallocated_amount, D("500.00"))

    def test_duplicate_receipt_rejected(self):
        a = self._finalized()
        fs.record_payment(assessment=a, received_by=self.cashier,
                          receipt_number="DUP", amount=D("100"), method="CASH")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                fs.record_payment(assessment=a, received_by=self.cashier,
                                  receipt_number="DUP", amount=D("100"), method="CASH")

    def test_allocation_cannot_exceed_unallocated(self):
        a = self._finalized()
        p = fs.record_payment(assessment=a, received_by=self.cashier,
                              receipt_number="AL", amount=D("1000"), method="CASH")
        # already auto-allocated 1000; no remainder
        with self.assertRaises(ValidationError):
            fs.allocate_payment(payment=p, version=a.current_version, amount=D("1"), by=self.cashier)


class AdjustmentScholarshipTests(FinanceTestBase):
    def _finalized(self):
        self._tuition_general("500")
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        return a

    def test_credit_requires_approval_and_creator_cannot_approve(self):
        a = self._finalized()
        adj = fs.create_adjustment(adjustment_type="CREDIT", amount=D("200"),
                                   reason="goodwill", by=self.cashier, assessment=a)
        # unapproved credit does not change balance
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))
        with self.assertRaises(ValidationError):
            fs.approve_adjustment(adjustment=adj, by=self.cashier)  # creator
        fs.approve_adjustment(adjustment=adj, by=self.admin)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1300.00"))

    def test_refund_increases_balance_after_approval(self):
        a = self._finalized()
        fs.record_payment(assessment=a, received_by=self.cashier,
                          receipt_number="PF", amount=D("1500"), method="CASH")
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        adj = fs.create_adjustment(adjustment_type="REFUND", amount=D("500"),
                                   reason="overpaid elsewhere", by=self.cashier, assessment=a)
        fs.approve_adjustment(adjustment=adj, by=self.admin)
        self.assertEqual(fs.assessment_balance(assessment=a), D("500.00"))

    def test_scholarship_counts_when_approved_and_not_as_cash(self):
        a = self._finalized()
        sch = fs.create_scholarship(student=self.student, sponsor="DemoFund",
                                    amount=D("500"), by=self.cashier, assessment=a)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))  # pending
        with self.assertRaises(ValidationError):
            fs.approve_scholarship(scholarship=sch, by=self.cashier)  # creator
        fs.approve_scholarship(scholarship=sch, by=self.admin)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1000.00"))
        # scholarship is not a payment
        self.assertEqual(Payment.objects.filter(assessment=a).count(), 0)


class FinancePermissionTests(FinanceTestBase):
    def _finalized(self):
        self._tuition_general("500")
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        return a

    def test_finance_list_access_by_role(self):
        url = reverse("finance:assessment_list")
        for who, code in [("fin_cashier", 200), ("fin_registrar", 200),
                          ("fin_admin", 200), ("fin_student", 403)]:
            self.client.login(username=who, password="pass12345")
            self.assertEqual(self.client.get(url).status_code, code, who)
            self.client.logout()

    def test_cashier_cannot_finalize_registrar_can(self):
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        self._tuition_general("500")
        url = reverse("finance:finalize", args=[a.pk])
        self.client.login(username="fin_cashier", password="pass12345")
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.logout()
        self.client.login(username="fin_registrar", password="pass12345")
        self.assertEqual(self.client.post(url).status_code, 302)  # redirect after finalize
        a.refresh_from_db()
        self.assertTrue(a.is_finalized)

    def test_record_payment_cashier_only(self):
        a = self._finalized()
        url = reverse("finance:record_payment", args=[a.pk])
        self.client.login(username="fin_registrar", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.client.login(username="fin_cashier", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_approvals_admin_only(self):
        url = reverse("finance:approvals")
        self.client.login(username="fin_cashier", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.client.login(username="fin_admin", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_student_and_instructor_blocked_from_detail(self):
        a = self._finalized()
        url = reverse("finance:assessment_detail", args=[a.pk])
        self.client.login(username="fin_student", password="pass12345")
        self.assertEqual(self.client.get(url).status_code, 403)


class ScholarshipUIBug1Tests(FinanceTestBase):
    """Regression tests for UAT Bug 1: scholarships submitted through the UI must
    link to the assessment (and its current version) so an approved award reduces
    the balance, with the student derived server-side from the assessment URL.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Instructor (role only) for authorization checks.
        cls.instructor_user = User.objects.create_user(
            username="fin_instr", password="pass12345", role=User.Role.INSTRUCTOR)
        # Second student for the forged-student-parameter / version-less checks.
        cls.other_user = User.objects.create_user(
            username="fin_student2", password="pass12345", role=User.Role.STUDENT)
        cls.other_student = Student.objects.create(
            user=cls.other_user, student_number="FIN-0002",
            curriculum=cls.curriculum, year_level=1)

    def _finalized(self, amount="500"):
        self._tuition_general(amount)  # 500/unit * 3 units = 1500.00 total
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        a.refresh_from_db()
        return a

    def _url(self, pk):
        return reverse("finance:scholarship_create", args=[pk])

    # (1) award is linked to the assessment + current version; is_demo False; redirect
    def test_cashier_submit_links_award_and_redirects(self):
        a = self._finalized()
        self.client.login(username="fin_cashier", password="pass12345")
        resp = self.client.post(self._url(a.pk), {"sponsor": "ACME Fund", "amount": "500"})
        self.assertRedirects(resp, reverse("finance:assessment_detail", args=[a.pk]))
        award = ScholarshipAward.objects.get(student=self.student)
        self.assertEqual(award.assessment_id, a.pk)
        self.assertEqual(award.version_id, a.current_version_id)
        self.assertEqual(award.status, ScholarshipAward.Status.PENDING)
        self.assertFalse(award.is_demo)

    # (2,3,4) pending no change -> approve reduces -> apply no double (via real views)
    def test_balance_pending_approve_apply(self):
        a = self._finalized()  # total 1500.00
        self.client.login(username="fin_cashier", password="pass12345")
        self.client.post(self._url(a.pk), {"sponsor": "ACME", "amount": "500"})
        award = ScholarshipAward.objects.get(student=self.student)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))  # pending
        self.client.logout()
        self.client.login(username="fin_admin", password="pass12345")  # creator != approver
        self.client.post(reverse("finance:scholarship_action", args=[award.pk, "approve"]))
        self.assertEqual(fs.assessment_balance(assessment=a), D("1000.00"))  # reduced
        self.client.post(reverse("finance:scholarship_action", args=[award.pk, "apply"]))
        self.assertEqual(fs.assessment_balance(assessment=a), D("1000.00"))  # no double
        award.refresh_from_db()
        self.assertEqual(award.status, ScholarshipAward.Status.APPLIED)

    # (5) a forged student POST param cannot attach the award to another student
    def test_forged_student_param_is_ignored(self):
        a = self._finalized()
        self.client.login(username="fin_cashier", password="pass12345")
        self.client.post(self._url(a.pk), {
            "sponsor": "X", "amount": "100", "student": self.other_student.pk})
        award = ScholarshipAward.objects.get(assessment=a)
        self.assertEqual(award.student_id, self.student.id)  # derived from the assessment
        self.assertFalse(
            ScholarshipAward.objects.filter(student=self.other_student).exists())

    # (6) version-less assessment is blocked (would otherwise not reduce the balance)
    def test_version_less_assessment_blocked(self):
        enr2 = Enrollment.objects.create(
            student=self.other_student, term=self.term,
            status=Enrollment.Status.CONFIRMED)
        a2 = Assessment.objects.create(
            enrollment=enr2, total_amount=D("8000.00"),
            status=Assessment.Status.FINALIZED)  # no current_version
        self.assertIsNone(a2.current_version_id)
        self.client.login(username="fin_cashier", password="pass12345")
        resp = self.client.post(self._url(a2.pk), {"sponsor": "Y", "amount": "100"})
        self.assertRedirects(resp, reverse("finance:assessment_detail", args=[a2.pk]))
        self.assertEqual(ScholarshipAward.objects.filter(assessment=a2).count(), 0)

    # (7) missing assessment -> 404
    def test_missing_assessment_404(self):
        self.client.login(username="fin_cashier", password="pass12345")
        self.assertEqual(self.client.get(self._url(999999)).status_code, 404)
        self.assertEqual(
            self.client.post(self._url(999999), {"sponsor": "z", "amount": "1"}).status_code,
            404)

    # (8) role gating enforced in the view independent of the UI
    def test_role_gating(self):
        a = self._finalized()
        url = self._url(a.pk)
        for who in ("fin_cashier", "fin_registrar"):
            self.client.login(username=who, password="pass12345")
            self.assertEqual(self.client.get(url).status_code, 200, who)
            self.client.logout()
        for who in ("fin_student", "fin_instr"):
            self.client.login(username=who, password="pass12345")
            self.assertEqual(self.client.get(url).status_code, 403, who)
            self.client.logout()
        # Administrator is blocked by _check_role (redirect, no award created).
        self.client.login(username="fin_admin", password="pass12345")
        resp = self.client.post(url, {"sponsor": "A", "amount": "100"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ScholarshipAward.objects.filter(assessment=a).count(), 0)

    # (9) a new PENDING award is visible on the assessment detail page
    def test_pending_award_visible_on_detail(self):
        a = self._finalized()
        self.client.login(username="fin_cashier", password="pass12345")
        self.client.post(self._url(a.pk), {"sponsor": "Visible Fund", "amount": "500"})
        resp = self.client.get(reverse("finance:assessment_detail", args=[a.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Visible Fund")
        self.assertContains(resp, "Pending")
        self.assertEqual(len(resp.context["scholarships"]), 1)

    # (10-14) creation must not modify existing financial records
    def test_creation_does_not_touch_existing_records(self):
        from finance.models import AssessmentLine
        a = self._finalized()
        fs.record_payment(assessment=a, received_by=self.cashier,
                          receipt_number="HIST-1", amount=D("300"), method="CASH")
        fs.create_scholarship(student=self.student, sponsor="Existing",
                              amount=D("200"), by=self.cashier, assessment=a)

        def snapshot(exclude_award_id=None):
            awards = ScholarshipAward.objects.all()
            if exclude_award_id is not None:
                awards = awards.exclude(id=exclude_award_id)
            return {
                "versions": set(AssessmentVersion.objects.values_list("id", "status", "total_amount")),
                "lines": set(AssessmentLine.objects.values_list("id", "line_total")),
                "payments": set(Payment.objects.values_list("id", "amount", "status")),
                "allocs": set(PaymentAllocation.objects.values_list("id", "amount", "version_id")),
                "awards": set(awards.values_list("id", "status", "amount", "assessment_id")),
            }

        before = snapshot()
        existing_award_ids = {row[0] for row in before["awards"]}

        self.client.login(username="fin_cashier", password="pass12345")
        self.client.post(self._url(a.pk), {"sponsor": "New One", "amount": "150"})

        new_awards = ScholarshipAward.objects.exclude(id__in=existing_award_ids)
        self.assertEqual(new_awards.count(), 1)
        na = new_awards.get()
        self.assertEqual(na.assessment_id, a.pk)
        self.assertEqual(na.version_id, a.current_version_id)

        after = snapshot(exclude_award_id=na.id)
        self.assertEqual(after["versions"], before["versions"])
        self.assertEqual(after["lines"], before["lines"])
        self.assertEqual(after["payments"], before["payments"])
        self.assertEqual(after["allocs"], before["allocs"])
        self.assertEqual(after["awards"], before["awards"])


class AssessmentRevisionPaymentCarryForwardTests(FinanceTestBase):
    """Regression tests for UAT Bug 2: received payments must carry forward across
    assessment revisions (scoped to the same assessment), without moving or
    rewriting any historical allocation, and negative (over-credited) balances
    must be preserved.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Second student/enrollment for cross-assessment isolation.
        cls.other_user = User.objects.create_user(
            username="cf_student2", password="pass12345", role=User.Role.STUDENT)
        cls.other_student = Student.objects.create(
            user=cls.other_user, student_number="CF-0002",
            curriculum=cls.curriculum, year_level=1)

    def _finalized(self, tuition="500"):
        self._tuition_general(tuition)  # tuition/unit * 3 units
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        a.refresh_from_db()
        return a

    def _revise_finalize(self, a, reason="re-review"):
        fs.revise_assessment(assessment=a, by=self.admin, reason=reason)
        fs.finalize_assessment(assessment=a, by=self.admin)
        a.refresh_from_db()
        return a

    def _pay(self, a, receipt, amount, status=Payment.Status.RECEIVED):
        return fs.record_payment(
            assessment=a, received_by=self.cashier, receipt_number=receipt,
            amount=D(amount), method=Payment.Method.CASH, status=status)

    # (1) fully paid, revise same total -> balance 0; allocation preserved on v1
    def test_fully_paid_revise_same_total(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "1500")
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        old_v = a.current_version
        self._revise_finalize(a)
        self.assertEqual(a.current_version.total_amount, D("1500.00"))
        self.assertNotEqual(a.current_version_id, old_v.id)
        self.assertEqual(fs.assessment_amount_paid(assessment=a), D("1500.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        alloc = PaymentAllocation.objects.get()
        self.assertEqual(alloc.version_id, old_v.id)  # never moved
        old_v.refresh_from_db()
        self.assertEqual(old_v.status, AssessmentVersion.Status.SUPERSEDED)

    # (2) fully paid, revise up -> only the difference outstanding
    def test_fully_paid_revise_up(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "1500")
        self._misc_general("1000")  # new total 2500
        self._revise_finalize(a)
        self.assertEqual(a.current_version.total_amount, D("2500.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("1000.00"))

    # (3) partially paid, revise -> payment still credited
    def test_partially_paid_revise(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "600")
        self.assertEqual(fs.assessment_balance(assessment=a), D("900.00"))
        self._revise_finalize(a)  # same total
        self.assertEqual(fs.assessment_balance(assessment=a), D("900.00"))

    # (4) unpaid, revise -> balance equals new total
    def test_unpaid_revise(self):
        a = self._finalized()  # 1500
        self._misc_general("1000")
        self._revise_finalize(a)  # 2500
        self.assertEqual(fs.assessment_balance(assessment=a), D("2500.00"))

    # (5) multiple revisions -> no double counting
    def test_multiple_revisions_no_double_count(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "1500")
        self._revise_finalize(a)
        self._revise_finalize(a)
        self.assertEqual(AssessmentVersion.objects.filter(assessment=a).count(), 3)
        self.assertEqual(fs.assessment_amount_paid(assessment=a), D("1500.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))

    # (6/7/8) pending, cancelled, reversed never count after revision
    def test_pending_payment_excluded(self):
        a = self._finalized()
        self._pay(a, "P1", "1500", status=Payment.Status.PENDING)
        self._revise_finalize(a)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))

    def test_cancelled_payment_excluded(self):
        a = self._finalized()
        self._pay(a, "C1", "1500", status=Payment.Status.CANCELLED)
        self._revise_finalize(a)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))

    def test_reversed_payment_excluded(self):
        a = self._finalized()
        p = self._pay(a, "R1", "1500")
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        fs.reverse_payment(payment=p, by=self.admin, reason="error")
        self._revise_finalize(a)
        self.assertEqual(fs.assessment_balance(assessment=a), D("1500.00"))

    # (9) overpayment then revise down -> accurate negative balance (over-credit)
    def test_revise_down_yields_negative_balance(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "1500")
        FeeRule.objects.filter(category="TUITION").update(amount=D("300"))  # -> 900
        self._revise_finalize(a)
        self.assertEqual(a.current_version.total_amount, D("900.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("-600.00"))

    # (10) cross-assessment isolation
    def test_cross_assessment_isolation(self):
        a = self._finalized()  # student 1, 1500
        self._pay(a, "R1", "1500")
        # second assessment for the other student, its own payment
        enr2 = Enrollment.objects.create(
            student=self.other_student, term=self.term,
            status=Enrollment.Status.CONFIRMED)
        EnrollmentDetail.objects.create(
            enrollment=enr2, section=self.section,
            status=EnrollmentDetail.Status.ENROLLED)
        a2 = fs.create_draft_assessment(enrollment=enr2, by=self.registrar)
        fs.finalize_assessment(assessment=a2, by=self.registrar)
        a2.refresh_from_db()
        self._pay(a2, "R2", "1500")
        self._revise_finalize(a)
        # a counts only its own payment; a2 is unaffected
        self.assertEqual(fs.assessment_amount_paid(assessment=a), D("1500.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        self.assertEqual(fs.assessment_balance(assessment=a2), D("0.00"))

    # (11) historical versions/allocations/payments immutable on revision
    def test_history_immutable_on_revision(self):
        a = self._finalized()
        self._pay(a, "R1", "1500")
        before_payments = set(Payment.objects.values_list("id", "amount", "status"))
        before_allocs = set(PaymentAllocation.objects.values_list("id", "amount", "version_id"))
        old_v = a.current_version
        before_old_lines = set(old_v.lines.values_list("id", "line_total"))
        self._revise_finalize(a)
        self.assertEqual(set(Payment.objects.values_list("id", "amount", "status")),
                         before_payments)
        self.assertEqual(set(PaymentAllocation.objects.values_list("id", "amount", "version_id")),
                         before_allocs)
        old_v.refresh_from_db()
        self.assertEqual(old_v.total_amount, D("1500.00"))
        self.assertEqual(set(old_v.lines.values_list("id", "line_total")), before_old_lines)

    # (12) a payment after revision allocates correctly to the current version
    def test_payment_after_revision_allocates(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "600")
        self._misc_general("1000")
        self._revise_finalize(a)  # total 2500, balance 2500-600=1900
        self.assertEqual(fs.assessment_balance(assessment=a), D("1900.00"))
        self._pay(a, "R2", "1900")
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))
        cur_alloc = PaymentAllocation.objects.filter(
            version=a.current_version).aggregate(t=Sum("amount"))["t"]
        self.assertEqual(cur_alloc, D("1900.00"))  # new payment on the new version

    # (13) scholarship + credit + payment are each counted once across a revision
    def test_scholarship_and_credit_not_double_counted(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "500")
        sch = fs.create_scholarship(student=self.student, sponsor="F",
                                    amount=D("300"), by=self.cashier, assessment=a)
        fs.approve_scholarship(scholarship=sch, by=self.admin)
        adj = fs.create_adjustment(adjustment_type=Adjustment.Type.CREDIT,
                                   amount=D("200"), reason="goodwill",
                                   by=self.cashier, assessment=a)
        fs.approve_adjustment(adjustment=adj, by=self.admin)
        self.assertEqual(fs.assessment_balance(assessment=a), D("500.00"))  # 1500-500-300-200
        self._revise_finalize(a)
        self.assertEqual(fs.assessment_balance(assessment=a), D("500.00"))  # unchanged, no dup

    # (14) balance/amount_paid are pure reads (stable, no writes)
    def test_balance_is_read_only_and_stable(self):
        a = self._finalized()
        self._pay(a, "R1", "1500")
        self._revise_finalize(a)
        counts = (Payment.objects.count(), PaymentAllocation.objects.count(),
                  AssessmentVersion.objects.count())
        vals = {fs.assessment_balance(assessment=a) for _ in range(3)}
        self.assertEqual(vals, {D("0.00")})
        self.assertEqual(
            (Payment.objects.count(), PaymentAllocation.objects.count(),
             AssessmentVersion.objects.count()), counts)

    # (15-19) paying into a negative balance stays unallocated; nothing erased
    def test_payment_into_negative_balance_stays_unallocated(self):
        a = self._finalized()  # 1500
        self._pay(a, "R1", "1500")
        FeeRule.objects.filter(category="TUITION").update(amount=D("300"))
        self._revise_finalize(a)  # 900 total
        self.assertEqual(fs.assessment_balance(assessment=a), D("-600.00"))  # (15)
        orig = PaymentAllocation.objects.get()
        orig_snapshot = (orig.id, orig.amount, orig.version_id)
        alloc_count = PaymentAllocation.objects.count()

        p2 = self._pay(a, "R2", "500")  # (16) pay into the negative balance
        p2.refresh_from_db()
        self.assertEqual(p2.status, Payment.Status.RECEIVED)
        self.assertEqual(p2.allocated_amount, D("0.00"))          # unallocated
        self.assertEqual(PaymentAllocation.objects.count(), alloc_count)  # no new alloc (16)
        self.assertFalse(PaymentAllocation.objects.filter(amount__lte=0).exists())  # (17)
        orig.refresh_from_db()
        self.assertEqual((orig.id, orig.amount, orig.version_id), orig_snapshot)  # (18)
        self.assertEqual(fs.assessment_balance(assessment=a), D("-600.00"))  # (19) unchanged

    # (20) positive-balance allocation behavior is unchanged
    def test_positive_balance_allocation_unchanged(self):
        a = self._finalized()  # 1500
        p1 = self._pay(a, "R1", "600")
        self.assertEqual(p1.allocated_amount, D("600.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("900.00"))
        p2 = self._pay(a, "R2", "2000")  # overpay: caps at remaining 900
        self.assertEqual(p2.allocated_amount, D("900.00"))
        self.assertEqual(p2.unallocated_amount, D("1100.00"))
        self.assertEqual(fs.assessment_balance(assessment=a), D("0.00"))


class ReconciliationDateRangeTests(FinanceTestBase):
    """run_reconciliation must sum RECEIVED payments by Asia/Manila calendar day via
    half-open aware-datetime bounds (local_day_range) — correct without MySQL tz tables.
    Manila = UTC+8: a payment at UTC 2026-09-01 16:00 is Manila 2026-09-02 00:00.
    """

    def _finalized(self):
        self._tuition_general("500")
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        a.refresh_from_db()
        return a

    def _recv(self, a, receipt, amount, utc_dt):
        return Payment.objects.create(
            assessment=a, received_by=self.cashier, receipt_number=receipt,
            amount=D(amount), method=Payment.Method.CASH,
            status=Payment.Status.RECEIVED, payment_date=utc_dt)

    def test_reconciliation_same_local_day(self):
        a = self._finalized()
        U = dt_tz.utc
        self._recv(a, "RCN-IN1", "500", datetime(2026, 9, 1, 16, 0, 0, tzinfo=U))   # Manila 09-02 00:00
        self._recv(a, "RCN-IN2", "300", datetime(2026, 9, 2, 15, 59, 59, tzinfo=U)) # Manila 09-02 23:59:59
        self._recv(a, "RCN-OUT", "999", datetime(2026, 9, 2, 16, 0, 0, tzinfo=U))   # Manila 09-03 00:00
        batch = fs.run_reconciliation(by=self.admin, period_start=date(2026, 9, 2),
                                      period_end=date(2026, 9, 2))
        self.assertEqual(batch.recorded_total, D("800.00"))  # IN1 + IN2, OUT excluded

    def test_reconciliation_open_ended_and_no_error(self):
        a = self._finalized()
        U = dt_tz.utc
        self._recv(a, "RCN-A", "100", datetime(2026, 9, 1, 16, 0, 0, tzinfo=U))  # Manila 09-02
        self._recv(a, "RCN-B", "200", datetime(2026, 9, 2, 16, 0, 0, tzinfo=U))  # Manila 09-03
        # from 09-03 onward
        b1 = fs.run_reconciliation(by=self.admin, period_start=date(2026, 9, 3))
        self.assertEqual(b1.recorded_total, D("200.00"))
        # no bounds at all -> all received
        b2 = fs.run_reconciliation(by=self.admin)
        self.assertEqual(b2.recorded_total, D("300.00"))


class AdjustmentFormTypeRestrictionTests(FinanceTestBase):
    """The New Adjustment form offers only the balance-affecting types (CREDIT,
    REFUND). CORRECTION (non-financial) and REVERSAL (payment-reverse flow only)
    are not selectable and are rejected server-side if forged into a POST.
    """

    def _finalized(self):
        self._tuition_general("500")
        a = fs.create_draft_assessment(enrollment=self.enrollment, by=self.registrar)
        fs.finalize_assessment(assessment=a, by=self.registrar)
        a.refresh_from_db()
        return a

    def test_form_offers_only_credit_and_refund(self):
        from finance.forms import AdjustmentForm
        values = {c[0] for c in AdjustmentForm().fields["adjustment_type"].choices}
        self.assertEqual(values, {Adjustment.Type.CREDIT, Adjustment.Type.REFUND})
        self.assertNotIn(Adjustment.Type.CORRECTION, values)
        self.assertNotIn(Adjustment.Type.REVERSAL, values)

    def test_credit_and_refund_still_create(self):
        a = self._finalized()
        self.client.login(username="fin_cashier", password="pass12345")
        for t in (Adjustment.Type.CREDIT, Adjustment.Type.REFUND):
            resp = self.client.post(
                reverse("finance:adjustment_create", args=[a.pk]),
                {"adjustment_type": t, "amount": "100", "reason": "ok"})
            self.assertEqual(resp.status_code, 302)  # created -> redirect to detail
        self.assertEqual(Adjustment.objects.filter(assessment=a).count(), 2)

    def test_correction_and_reversal_rejected_server_side(self):
        a = self._finalized()
        self.client.login(username="fin_cashier", password="pass12345")
        for t in (Adjustment.Type.CORRECTION, Adjustment.Type.REVERSAL):
            resp = self.client.post(
                reverse("finance:adjustment_create", args=[a.pk]),
                {"adjustment_type": t, "amount": "6000", "reason": "Increase"})
            self.assertEqual(resp.status_code, 200)  # re-rendered with errors
            self.assertTrue(resp.context["form"].errors)
        self.assertEqual(Adjustment.objects.filter(assessment=a).count(), 0)
