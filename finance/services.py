"""Transactional finance rules: fee-rule selection, assessments, payments."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    Assessment,
    AssessmentLine,
    FeeRule,
    Payment,
    PaymentAllocation,
)


def _as_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Amount must be a valid decimal number.")


# ---------------------------------------------------------------------------
# Fee rules
# ---------------------------------------------------------------------------


def find_applicable_fee_rule(*, fee_type, program, course, on_date=None):
    """Return the single fee rule that applies, or ``None``.

    Precedence: course-specific, then program-specific, then general.  If more
    than one active rule matches at the winning precedence, the configuration
    is ambiguous and a ``ValidationError`` is raised instead of guessing.
    """
    on_date = on_date or timezone.localdate()
    candidates = FeeRule.objects.filter(
        fee_type=fee_type,
        is_active=True,
        effective_from__lte=on_date,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))

    tiers = []
    if course is not None:
        tiers.append(
            ("course", candidates.filter(course=course, program__isnull=True))
        )
    if program is not None:
        tiers.append(
            ("program", candidates.filter(program=program, course__isnull=True))
        )
    tiers.append(
        ("general", candidates.filter(program__isnull=True, course__isnull=True))
    )

    for scope, queryset in tiers:
        rules = list(queryset)
        if len(rules) > 1:
            ids = ", ".join(str(rule.pk) for rule in rules)
            raise ValidationError(
                f"Ambiguous {scope}-specific fee rules for {fee_type.code} "
                f"on {on_date}: rules {ids} all apply. Resolve the overlap "
                "before computing the assessment."
            )
        if rules:
            return rules[0]
    return None


def validate_fee_rule_no_overlap(*, rule, exclude_pk=None):
    """Reject a rule that overlaps an existing rule in the same scope.

    Overlap means same fee type, same program/course scope, and intersecting
    effective dates.  This is a cross-row rule, so it is validated here rather
    than by a database constraint.
    """
    if rule.program_id is not None and rule.course_id is not None:
        raise ValidationError(
            "A fee rule must be general, program-specific, or course-specific - "
            "not both program- and course-specific."
        )
    if rule.effective_to is not None and rule.effective_to < rule.effective_from:
        raise ValidationError("effective_to cannot be before effective_from.")

    overlapping = FeeRule.objects.filter(
        fee_type_id=rule.fee_type_id,
        program_id=rule.program_id,
        course_id=rule.course_id,
        is_active=True,
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=rule.effective_from)
    )
    if rule.effective_to is not None:
        overlapping = overlapping.filter(effective_from__lte=rule.effective_to)
    if exclude_pk is not None:
        overlapping = overlapping.exclude(pk=exclude_pk)

    if overlapping.exists():
        raise ValidationError(
            "Another active fee rule in the same scope has overlapping "
            "effective dates."
        )


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------


@transaction.atomic
def recalculate_assessment_total(*, assessment):
    """Recalculate a draft assessment's total from its lines."""
    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.status != Assessment.Status.DRAFT:
        raise ValidationError("Only draft assessments can be recalculated.")

    total = assessment.lines.aggregate(total=Sum("line_total"))["total"]
    total = total if total is not None else Decimal("0.00")
    assessment.total_amount = total
    assessment.save(update_fields=["total_amount"])
    return total


@transaction.atomic
def finalize_assessment(*, assessment):
    """Freeze the assessment by saving the total derived from its lines."""
    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.status == Assessment.Status.FINALIZED:
        return assessment

    lines = list(assessment.lines.all())
    if not lines:
        raise ValidationError("Cannot finalize an assessment with no lines.")

    total = sum((line.line_total for line in lines), Decimal("0.00"))
    assessment.total_amount = total
    assessment.status = Assessment.Status.FINALIZED
    assessment.save(update_fields=["total_amount", "status"])
    return assessment


def outstanding_balance(*, assessment):
    """Finalized total minus allocations from RECEIVED payments.

    Returns ``None`` while the assessment is not finalized, because only
    finalized assessments are billable.
    """
    if assessment.status != Assessment.Status.FINALIZED:
        return None

    allocated = (
        PaymentAllocation.objects.filter(
            assessment=assessment, payment__status=Payment.Status.RECEIVED
        ).aggregate(total=Sum("allocated_amount"))["total"]
        or Decimal("0.00")
    )
    return assessment.total_amount - allocated


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@transaction.atomic
def allocate_payment(*, payment, assessment, amount):
    """Apply part of a received payment to a finalized assessment.

    Locks the payment and assessment rows so concurrent allocations cannot
    exceed the payment amount or the assessment's remaining balance.
    """
    amount = _as_decimal(amount)
    if amount <= 0:
        raise ValidationError("Allocation amount must be greater than zero.")

    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)

    if payment.status != Payment.Status.RECEIVED:
        raise ValidationError("Only RECEIVED payments can be allocated.")
    if assessment.status != Assessment.Status.FINALIZED:
        raise ValidationError("Only finalized assessments can receive allocations.")
    if payment.student_id != assessment.enrollment.student_id:
        raise ValidationError(
            "The payment student does not match the assessment's student."
        )

    already_allocated = (
        payment.allocations.aggregate(total=Sum("allocated_amount"))["total"]
        or Decimal("0.00")
    )
    if already_allocated + amount > payment.amount:
        raise ValidationError(
            "Allocations cannot exceed the payment amount."
        )

    remaining = outstanding_balance(assessment=assessment)
    if amount > remaining:
        raise ValidationError(
            "The allocation exceeds the assessment's outstanding balance."
        )

    allocation = (
        PaymentAllocation.objects.select_for_update()
        .filter(payment=payment, assessment=assessment)
        .first()
    )
    if allocation is not None:
        allocation.allocated_amount += amount
        allocation.save(update_fields=["allocated_amount"])
        return allocation

    return PaymentAllocation.objects.create(
        payment=payment, assessment=assessment, allocated_amount=amount
    )


@transaction.atomic
def cancel_payment(*, payment):
    """Cancel a payment that has no allocations.

    Initial-version policy: a payment with allocations cannot be cancelled,
    and allocations must not be deleted to bypass the rule.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.CANCELLED:
        return payment
    if payment.allocations.exists():
        raise ValidationError(
            "A payment with allocations cannot be cancelled. "
            "Preserve the payment and allocation history."
        )

    payment.status = Payment.Status.CANCELLED
    payment.save(update_fields=["status"])
    return payment
