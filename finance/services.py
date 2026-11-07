"""Finance services (Milestone B).

Holds all money-moving logic so views stay thin and rules stay in one place.
Every monetary value is ``Decimal``; results are quantized to 2 places with
``ROUND_HALF_UP``. Balances are computed here (the authoritative source).

Compatibility: ``record_payment`` keeps its original signature/behavior (it
still creates a ``Payment``); it now also auto-allocates a ``RECEIVED`` payment
to the assessment's current version when one exists. ``assessment_balance`` and
``assessment_amount_paid`` fall back to the original "total minus received
payments" formula for legacy assessments that have no version yet, so existing
records and the seed keep their exact meaning.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from enrollment.models import Enrollment, EnrollmentDetail
from .models import (
    Adjustment,
    Assessment,
    AssessmentLine,
    AssessmentVersion,
    FeeRule,
    FinanceAuditLog,
    FinancePolicy,
    Payment,
    PaymentAllocation,
    Reconciliation,
    ScholarshipAward,
)

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def q2(value):
    """Quantize to 2 decimal places with half-up rounding."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _as_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Amount must be a valid decimal number.")


def audit(*, actor, action, detail=""):
    FinanceAuditLog.objects.create(actor=actor, action=action, detail=detail[:500])


def local_day_range(date_from, date_to):
    """Half-open ``[start, end)`` aware-datetime bounds for an INCLUSIVE local-date
    range in the configured timezone (settings.TIME_ZONE, e.g. Asia/Manila).

    Lets date filtering match the intended calendar day via a plain ``payment_date``
    comparison (``>= start`` and ``< end``) instead of ``DATE(CONVERT_TZ(...))`` — so it
    is correct without relying on MySQL timezone tables, and uses the datetime index.
    ``end`` is midnight immediately after ``date_to`` (so the whole end day is included).
    Either bound may be ``None`` (open-ended on that side).
    """
    tz = timezone.get_current_timezone()
    start = (
        timezone.make_aware(datetime.combine(date_from, time.min), tz)
        if date_from else None
    )
    end = (
        timezone.make_aware(datetime.combine(date_to, time.min), tz) + timedelta(days=1)
        if date_to else None
    )
    return start, end


# --------------------------------------------------------------------------
# Fee computation
# --------------------------------------------------------------------------
def _enrolled_courses(enrollment):
    """Return [(course, units)] for actively ENROLLED details of an enrollment."""
    details = (
        EnrollmentDetail.objects.filter(
            enrollment=enrollment, status=EnrollmentDetail.Status.ENROLLED
        )
        .exclude(enrollment__status=Enrollment.Status.CANCELLED)
        .select_related("section__course")
    )
    out = []
    for detail in details:
        course = detail.section.course
        out.append((course, Decimal(course.units)))
    return out


def _rule_applies(rule, *, term_id, year_level):
    if not rule.is_active:
        return False
    if rule.term_id is not None and rule.term_id != term_id:
        return False
    if rule.year_level is not None and rule.year_level != year_level:
        return False
    return True


def compute_fee_breakdown(enrollment):
    """Compute itemized fee lines for an enrollment.

    Returns ``{"lines": [...], "conflicts": [...]}``. Each line is a dict with
    ``fee_category``, ``description``, ``quantity``, ``unit_amount``,
    ``line_total``, ``fee_rule``.

    Category-aware stacking with COURSE > PROGRAM > GENERAL precedence:
      * Different fee categories accumulate.
      * Within a category, if any COURSE-scoped rule applies it becomes a
        *per-course* category: each enrolled course is charged with the most
        specific rule available for it (its COURSE rule, else PROGRAM, else
        GENERAL). Otherwise the category is charged once at the student level
        using the most specific of PROGRAM/GENERAL.
      * Two equally-applicable competing rules in the winning scope produce a
        CONFLICT (finalization is then blocked); a rule is never silently chosen.

    Calculation basis: PER_UNIT course rules use that course's units; PER_UNIT
    program/general rules use the student's total enrolled units; FIXED rules
    are charged once and never multiplied by units.
    """
    student = enrollment.student
    program_id = student.curriculum.program_id
    term_id = enrollment.term_id
    year_level = student.year_level

    courses = _enrolled_courses(enrollment)
    total_units = sum((units for _c, units in courses), Decimal("0"))
    enrolled_course_ids = {c.id for c, _u in courses}

    applicable = [
        r for r in FeeRule.objects.select_related("course", "program").all()
        if _rule_applies(r, term_id=term_id, year_level=year_level)
    ]

    categories = sorted({r.category for r in applicable})
    lines = []
    conflicts = []

    def _line(rule, *, course=None, units=None):
        if rule.computation == FeeRule.Computation.PER_UNIT:
            basis = units if units is not None else total_units
            qty = q2(basis)
            total = q2(Decimal(rule.amount) * basis)
            desc = rule.name + (f" ({course.course_code})" if course else "")
            return {
                "fee_category": rule.category, "description": desc,
                "quantity": qty, "unit_amount": q2(rule.amount),
                "line_total": total, "fee_rule": rule,
            }
        total = q2(rule.amount)
        desc = rule.name + (f" ({course.course_code})" if course else "")
        return {
            "fee_category": rule.category, "description": desc,
            "quantity": None, "unit_amount": q2(rule.amount),
            "line_total": total, "fee_rule": rule,
        }

    for category in categories:
        cat_rules = [r for r in applicable if r.category == category]
        course_rules = [
            r for r in cat_rules
            if r.scope == FeeRule.Scope.COURSE and r.course_id in enrolled_course_ids
        ]
        program_rules = [
            r for r in cat_rules
            if r.scope == FeeRule.Scope.PROGRAM and r.program_id == program_id
        ]
        general_rules = [r for r in cat_rules if r.scope == FeeRule.Scope.GENERAL]

        if course_rules:
            # per-course category: charge each course with its most specific rule
            for course, units in courses:
                specific = [r for r in course_rules if r.course_id == course.id]
                chosen = specific or program_rules or general_rules
                if len(chosen) > 1:
                    conflicts.append(
                        f"{category}/{course.course_code}: "
                        f"{len(chosen)} competing fee rules apply."
                    )
                    continue
                if chosen:
                    lines.append(_line(chosen[0], course=course, units=units))
        else:
            chosen = program_rules or general_rules
            if len(chosen) > 1:
                conflicts.append(
                    f"{category}: {len(chosen)} competing fee rules apply."
                )
            elif chosen:
                lines.append(_line(chosen[0]))

    return {"lines": lines, "conflicts": conflicts}


# --------------------------------------------------------------------------
# Assessment lifecycle
# --------------------------------------------------------------------------
def _write_lines(version, lines):
    AssessmentLine.objects.filter(version=version).delete()
    total = ZERO
    for data in lines:
        rule = data["fee_rule"]
        AssessmentLine.objects.create(
            version=version,
            fee_category=data["fee_category"],
            description=data["description"],
            quantity=data["quantity"],
            unit_amount=data["unit_amount"],
            line_total=data["line_total"],
            fee_rule=rule,
            fee_rule_name=rule.name if rule else "",
            fee_rule_scope=rule.scope if rule else "",
        )
        total += data["line_total"]
    return q2(total)


def _sync_assessment(assessment, version):
    assessment.current_version = version
    assessment.total_amount = version.total_amount
    assessment.status = (
        Assessment.Status.FINALIZED
        if version.status == AssessmentVersion.Status.FINALIZED
        else Assessment.Status.DRAFT
    )
    assessment.save(update_fields=["current_version", "total_amount", "status"])


@transaction.atomic
def create_draft_assessment(*, enrollment, by=None):
    """Create (idempotently) a DRAFT assessment + v1 for a CONFIRMED enrollment.

    Called automatically on enrollment confirmation. Conflicting fee rules do
    not block draft creation (only finalization); conflicted categories are
    simply omitted from the draft lines until resolved.
    """
    enrollment = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
    if enrollment.status != Enrollment.Status.CONFIRMED:
        raise ValidationError(
            "An assessment can only be created for a confirmed enrollment."
        )
    assessment = Assessment.objects.filter(enrollment=enrollment).first()
    if assessment is not None and assessment.current_version_id is not None:
        return assessment
    if assessment is None:
        assessment = Assessment.objects.create(
            enrollment=enrollment, total_amount=ZERO,
            status=Assessment.Status.DRAFT,
        )
    version = AssessmentVersion.objects.create(
        assessment=assessment, version_number=1,
        status=AssessmentVersion.Status.DRAFT, created_by=by,
    )
    breakdown = compute_fee_breakdown(enrollment)
    version.total_amount = _write_lines(version, breakdown["lines"])
    version.save(update_fields=["total_amount"])
    _sync_assessment(assessment, version)
    audit(actor=by, action="assessment.draft_created",
          detail=f"assessment #{assessment.pk} v1 total {version.total_amount}")
    return assessment


@transaction.atomic
def finalize_assessment(*, assessment, by):
    """Finalize the current DRAFT version; blocks on conflicting fee rules."""
    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    version = assessment.current_version
    if version is None:
        raise ValidationError("This assessment has no version to finalize.")
    version = AssessmentVersion.objects.select_for_update().get(pk=version.pk)
    if version.status != AssessmentVersion.Status.DRAFT:
        raise ValidationError("Only a draft assessment version can be finalized.")

    breakdown = compute_fee_breakdown(assessment.enrollment)
    if breakdown["conflicts"]:
        raise ValidationError(
            "Conflicting fee rules must be resolved before finalization: "
            + "; ".join(breakdown["conflicts"])
        )
    version.total_amount = _write_lines(version, breakdown["lines"])
    version.status = AssessmentVersion.Status.FINALIZED
    version.finalized_at = timezone.now()
    version.finalized_by = by
    version.save(update_fields=["total_amount", "status", "finalized_at", "finalized_by"])
    assessment.needs_review = False
    assessment.save(update_fields=["needs_review"])
    _sync_assessment(assessment, version)
    audit(actor=by, action="assessment.finalized",
          detail=f"assessment #{assessment.pk} v{version.version_number} total {version.total_amount}")
    return version


@transaction.atomic
def revise_assessment(*, assessment, by, reason):
    """Supersede the finalized current version with a new DRAFT version.

    Previous versions and their payment allocations are preserved untouched;
    allocations are never moved. Prior RECEIVED payments still settle the same
    assessment, so they carry forward automatically into the balance via
    ``assessment_amount_paid`` (which sums received allocations across all of the
    assessment's versions) — no manual reallocation is required.
    """
    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    current = assessment.current_version
    if current is None or current.status != AssessmentVersion.Status.FINALIZED:
        raise ValidationError("Only a finalized assessment can be revised.")
    if not reason:
        raise ValidationError("A revision reason is required.")

    current.status = AssessmentVersion.Status.SUPERSEDED
    current.save(update_fields=["status"])
    new_version = AssessmentVersion.objects.create(
        assessment=assessment,
        version_number=current.version_number + 1,
        status=AssessmentVersion.Status.DRAFT,
        created_by=by, revision_reason=reason,
    )
    breakdown = compute_fee_breakdown(assessment.enrollment)
    new_version.total_amount = _write_lines(new_version, breakdown["lines"])
    new_version.save(update_fields=["total_amount"])
    _sync_assessment(assessment, new_version)
    audit(actor=by, action="assessment.revised",
          detail=f"assessment #{assessment.pk} -> v{new_version.version_number}: {reason}")
    return new_version


def flag_assessments_for_rule_change(*, fee_rule, by=None):
    """Flag finalized assessments whose lines used a changed fee rule.

    Does not alter any finalized values; it only sets ``needs_review`` so an
    authorized revision can be made deliberately.
    """
    version_ids = (
        AssessmentLine.objects.filter(fee_rule=fee_rule)
        .values_list("version_id", flat=True)
    )
    assessments = Assessment.objects.filter(
        current_version_id__in=list(version_ids),
        status=Assessment.Status.FINALIZED,
    )
    count = assessments.update(needs_review=True)
    audit(actor=by, action="assessment.flagged_for_review",
          detail=f"fee rule #{fee_rule.pk} affected {count} finalized assessment(s)")
    return count


# --------------------------------------------------------------------------
# Payments & allocations
# --------------------------------------------------------------------------
def _received_allocations_to_assessment(assessment):
    """Sum RECEIVED payment allocations across ALL versions of this assessment.

    A revision supersedes the current version but leaves prior allocations on it
    (they are never moved). Those payments are still valid settlements of the
    *same* assessment, so they carry forward into the current balance. Allocations
    are read in place and never modified. The ``version__assessment`` filter keeps
    the sum scoped to this assessment's own versions (no cross-assessment leakage),
    and ``payment__status=RECEIVED`` excludes PENDING/CANCELLED/REVERSED payments.
    """
    total = (
        PaymentAllocation.objects.filter(
            version__assessment=assessment, payment__status=Payment.Status.RECEIVED
        ).aggregate(total=Sum("amount"))["total"]
    )
    return total if total is not None else ZERO


@transaction.atomic
def record_payment(
    *, assessment, received_by, receipt_number, amount, method,
    status=Payment.Status.RECEIVED, reference_note="",
):
    """Record one payment against an assessment (compatible with the original).

    When the assessment has a current version and the payment is RECEIVED, the
    payment is auto-allocated to that version up to the remaining balance (never
    beyond, so a balance never goes negative). Any excess stays unallocated and
    can become an authorized credit per policy.
    """
    amount = _as_decimal(amount)
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")
    amount = q2(amount)

    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    payment = Payment.objects.create(
        assessment=assessment, received_by=received_by,
        receipt_number=receipt_number, amount=amount, method=method,
        status=status, reference_note=reference_note,
    )
    if status == Payment.Status.RECEIVED and assessment.current_version_id:
        remaining = assessment_balance(assessment=assessment)
        allocatable = min(amount, remaining) if remaining > 0 else ZERO
        if allocatable > 0:
            PaymentAllocation.objects.create(
                payment=payment, version=assessment.current_version,
                amount=q2(allocatable), created_by=received_by,
            )
    audit(actor=received_by, action="payment.recorded",
          detail=f"{receipt_number} {amount} {method} {status}")
    return payment


@transaction.atomic
def allocate_payment(*, payment, version, amount, by=None):
    """Explicitly allocate part of a payment to an assessment version.

    Prevents allocating more than the payment's unallocated remainder.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    amount = q2(_as_decimal(amount))
    if amount <= 0:
        raise ValidationError("Allocation amount must be greater than zero.")
    if payment.status != Payment.Status.RECEIVED:
        raise ValidationError("Only a received payment can be allocated.")
    if amount > payment.unallocated_amount:
        raise ValidationError(
            "Allocation exceeds the payment's unallocated amount."
        )
    allocation = PaymentAllocation.objects.create(
        payment=payment, version=version, amount=amount, created_by=by,
    )
    audit(actor=by, action="payment.allocated",
          detail=f"payment #{payment.pk} -> version #{version.pk}: {amount}")
    return allocation


@transaction.atomic
def reverse_payment(*, payment, by, reason):
    """Reverse a received payment. It stays visible but no longer counts.

    Records an approved REVERSAL adjustment for the audit trail. Authorization
    (approver role) is enforced by the calling view.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.REVERSED:
        raise ValidationError("This payment is already reversed.")
    if payment.status != Payment.Status.RECEIVED:
        raise ValidationError("Only a received payment can be reversed.")
    payment.status = Payment.Status.REVERSED
    payment.reversed_at = timezone.now()
    payment.save(update_fields=["status", "reversed_at"])
    # A reversal is a single authorized action (not a two-step approval), so it
    # is recorded as system-initiated (created_by=None) and authorized by ``by``.
    Adjustment.objects.create(
        adjustment_type=Adjustment.Type.REVERSAL, amount=payment.amount,
        reason=reason or "Payment reversed", payment=payment,
        assessment=payment.assessment, created_by=None, approved_by=by,
        status=Adjustment.Status.APPROVED, approved_at=timezone.now(),
    )
    audit(actor=by, action="payment.reversed",
          detail=f"payment #{payment.pk} {payment.receipt_number}: {reason}")
    return payment


# --------------------------------------------------------------------------
# Adjustments, credits, refunds, scholarships
# --------------------------------------------------------------------------
@transaction.atomic
def create_adjustment(
    *, adjustment_type, amount, reason, by,
    assessment=None, version=None, payment=None,
):
    amount = q2(_as_decimal(amount))
    if amount <= 0:
        raise ValidationError("Adjustment amount must be greater than zero.")
    if not reason:
        raise ValidationError("A reason is required for an adjustment.")
    adjustment = Adjustment.objects.create(
        adjustment_type=adjustment_type, amount=amount, reason=reason,
        assessment=assessment, version=version, payment=payment,
        created_by=by, status=Adjustment.Status.PENDING,
    )
    audit(actor=by, action="adjustment.created",
          detail=f"{adjustment_type} {amount}: {reason}")
    return adjustment


@transaction.atomic
def approve_adjustment(*, adjustment, by):
    adjustment = Adjustment.objects.select_for_update().get(pk=adjustment.pk)
    if adjustment.status != Adjustment.Status.PENDING:
        raise ValidationError("Only a pending adjustment can be approved.")
    if adjustment.created_by_id == getattr(by, "pk", None):
        raise ValidationError(
            "An adjustment cannot be approved by the user who created it "
            "(separation of duties)."
        )
    adjustment.status = Adjustment.Status.APPROVED
    adjustment.approved_by = by
    adjustment.approved_at = timezone.now()
    adjustment.save(update_fields=["status", "approved_by", "approved_at"])
    audit(actor=by, action="adjustment.approved",
          detail=f"adjustment #{adjustment.pk} {adjustment.adjustment_type} {adjustment.amount}")
    return adjustment


@transaction.atomic
def reject_adjustment(*, adjustment, by):
    adjustment = Adjustment.objects.select_for_update().get(pk=adjustment.pk)
    if adjustment.status != Adjustment.Status.PENDING:
        raise ValidationError("Only a pending adjustment can be rejected.")
    adjustment.status = Adjustment.Status.REJECTED
    adjustment.approved_by = by
    adjustment.approved_at = timezone.now()
    adjustment.save(update_fields=["status", "approved_by", "approved_at"])
    audit(actor=by, action="adjustment.rejected", detail=f"adjustment #{adjustment.pk}")
    return adjustment


@transaction.atomic
def create_scholarship(
    *, student, sponsor, amount, by, assessment=None, version=None, is_demo=False,
):
    amount = q2(_as_decimal(amount))
    if amount <= 0:
        raise ValidationError("Scholarship amount must be greater than zero.")
    award = ScholarshipAward.objects.create(
        student=student, sponsor=sponsor, amount=amount,
        assessment=assessment, version=version,
        created_by=by, status=ScholarshipAward.Status.PENDING, is_demo=is_demo,
    )
    audit(actor=by, action="scholarship.created",
          detail=f"{sponsor} {amount} for student #{student.pk}")
    return award


@transaction.atomic
def approve_scholarship(*, scholarship, by):
    scholarship = ScholarshipAward.objects.select_for_update().get(pk=scholarship.pk)
    if scholarship.status != ScholarshipAward.Status.PENDING:
        raise ValidationError("Only a pending scholarship can be approved.")
    if scholarship.created_by_id == getattr(by, "pk", None):
        raise ValidationError(
            "A scholarship cannot be approved by the user who created it "
            "(separation of duties)."
        )
    scholarship.status = ScholarshipAward.Status.APPROVED
    scholarship.approved_by = by
    scholarship.approved_at = timezone.now()
    scholarship.save(update_fields=["status", "approved_by", "approved_at"])
    audit(actor=by, action="scholarship.approved", detail=f"scholarship #{scholarship.pk}")
    return scholarship


@transaction.atomic
def apply_scholarship(*, scholarship, by):
    scholarship = ScholarshipAward.objects.select_for_update().get(pk=scholarship.pk)
    if scholarship.status != ScholarshipAward.Status.APPROVED:
        raise ValidationError("Only an approved scholarship can be applied.")
    scholarship.status = ScholarshipAward.Status.APPLIED
    scholarship.save(update_fields=["status"])
    audit(actor=by, action="scholarship.applied", detail=f"scholarship #{scholarship.pk}")
    return scholarship


# --------------------------------------------------------------------------
# Authoritative balance
# --------------------------------------------------------------------------
def _approved_adjustment_total(assessment, adjustment_type):
    total = (
        Adjustment.objects.filter(
            assessment=assessment, adjustment_type=adjustment_type,
            status=Adjustment.Status.APPROVED,
        ).aggregate(total=Sum("amount"))["total"]
    )
    return total if total is not None else ZERO


def _scholarship_total(assessment):
    total = (
        ScholarshipAward.objects.filter(
            assessment=assessment,
            status__in=[ScholarshipAward.Status.APPROVED, ScholarshipAward.Status.APPLIED],
        ).aggregate(total=Sum("amount"))["total"]
    )
    return total if total is not None else ZERO


def assessment_amount_paid(*, assessment):
    """Total settled against this assessment (or legacy received payments).

    = received allocations across all of the assessment's versions + approved
      credits + approved/applied scholarship − approved refunds.
    Received allocations carry forward across revisions (a payment made against a
    now-superseded version still settles the same assessment); allocations are
    never moved. Legacy (no version): sum of RECEIVED payments, preserving the
    original behavior.
    """
    cv = assessment.current_version
    if cv is None:
        total = (
            Payment.objects.filter(
                assessment=assessment, status=Payment.Status.RECEIVED
            ).aggregate(total=Sum("amount"))["total"]
        )
        return q2(total if total is not None else ZERO)
    received = _received_allocations_to_assessment(assessment)
    credits = _approved_adjustment_total(assessment, Adjustment.Type.CREDIT)
    scholarship = _scholarship_total(assessment)
    refunds = _approved_adjustment_total(assessment, Adjustment.Type.REFUND)
    return q2(received + credits + scholarship - refunds)


def assessment_balance(*, assessment):
    """Authoritative current balance: current-version total minus amount paid.

    Only the current version's total is used (historical versions are never
    summed). Pending/cancelled/reversed payments never count.
    """
    cv = assessment.current_version
    if cv is None:
        return q2(assessment.total_amount - assessment_amount_paid(assessment=assessment))
    return q2(cv.total_amount - assessment_amount_paid(assessment=assessment))


# --------------------------------------------------------------------------
# Reconciliation (basic; see report for limitations)
# --------------------------------------------------------------------------
@transaction.atomic
def run_reconciliation(*, by, term=None, method="", period_start=None,
                       period_end=None, verified_total=None, notes=""):
    """Compute recorded received collections for a scope and record a batch.

    ``recorded_total`` is derived from RECEIVED payments in scope;
    ``verified_total`` is supplied by the reconciler (bank/OR tally). The
    discrepancy is flagged for investigation. Payment records are never altered.
    """
    qs = Payment.objects.filter(status=Payment.Status.RECEIVED)
    if method:
        qs = qs.filter(method=method)
    if term is not None:
        qs = qs.filter(assessment__enrollment__term=term)
    start, end = local_day_range(period_start, period_end)
    if start is not None:
        qs = qs.filter(payment_date__gte=start)
    if end is not None:
        qs = qs.filter(payment_date__lt=end)
    recorded = qs.aggregate(total=Sum("amount"))["total"] or ZERO
    verified = q2(_as_decimal(verified_total)) if verified_total is not None else q2(recorded)
    batch = Reconciliation.objects.create(
        term=term, method=method, period_start=period_start,
        period_end=period_end, recorded_total=q2(recorded),
        verified_total=verified, discrepancy=q2(recorded - verified),
        performed_by=by, notes=notes,
        status=(Reconciliation.Status.OPEN if q2(recorded - verified) != ZERO
                else Reconciliation.Status.RESOLVED),
        resolved_at=(None if q2(recorded - verified) != ZERO else timezone.now()),
    )
    audit(actor=by, action="reconciliation.run",
          detail=f"recorded {batch.recorded_total} vs verified {batch.verified_total}")
    return batch
