from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

TWO_PLACES = Decimal("0.01")


class FeeType(models.Model):
    """Catalogue of fees that can be charged (tuition, lab, misc, ...)."""

    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "fee_type"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uq_fee_type_code"),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class FeeRule(models.Model):
    """Amount rule for a fee type within exactly one scope.

    Scope is one of:
      * general         - neither ``program`` nor ``course`` set
      * program-specific - ``program`` set, ``course`` unset
      * course-specific  - ``course`` set, ``program`` unset

    A rule with both set is rejected by a database check constraint.  Which
    rule applies for a given student/course on a date, and whether that
    selection is ambiguous, is resolved by ``finance.services``.
    """

    class CalculationBasis(models.TextChoices):
        FLAT = "FLAT", "Flat amount"
        PER_UNIT = "PER_UNIT", "Per course unit"

    id = models.AutoField(primary_key=True)
    fee_type = models.ForeignKey(
        FeeType, on_delete=models.PROTECT, db_column="fee_type_id"
    )
    program = models.ForeignKey(
        "academics.Program",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="program_id",
    )
    course = models.ForeignKey(
        "academics.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="course_id",
    )
    calculation_basis = models.CharField(
        max_length=20,
        choices=CalculationBasis.choices,
        default=CalculationBasis.FLAT,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "fee_rule"
        ordering = ["fee_type_id", "effective_from"]
        constraints = [
            # A rule is general, program-specific, or course-specific - never
            # both program- and course-specific.
            models.CheckConstraint(
                condition=models.Q(program__isnull=True)
                | models.Q(course__isnull=True),
                name="ck_fee_rule_single_scope",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="ck_fee_rule_effective_range",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name="ck_fee_rule_amount_non_negative",
            ),
        ]

    @property
    def scope(self):
        if self.course_id is not None:
            return "course"
        if self.program_id is not None:
            return "program"
        return "general"

    def __str__(self):
        return f"{self.fee_type.code} ({self.scope}) {self.amount}"


class Assessment(models.Model):
    """The single assessment for an enrollment (initial scope).

    Totals are derived from the assessment lines.  Once ``status`` is
    ``FINALIZED`` the total and the lines may no longer be modified by normal
    operations; see ``save`` and ``AssessmentLine.save``.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FINALIZED = "FINALIZED", "Finalized"

    id = models.AutoField(primary_key=True)
    enrollment = models.OneToOneField(
        "enrollment.Enrollment",
        on_delete=models.PROTECT,
        related_name="assessment",
        db_column="enrollment_id",
    )
    assessed_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        db_table = "assessment"
        ordering = ["-assessed_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="ck_assessment_total_non_negative",
            ),
        ]

    @property
    def is_finalized(self):
        return self.status == self.Status.FINALIZED

    def save(self, *args, **kwargs):
        """Prevent silent edits to a finalized assessment."""
        if self.pk is not None:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("status", "total_amount", "enrollment_id")
                .first()
            )
            if previous and previous["status"] == self.Status.FINALIZED:
                changed = (
                    previous["total_amount"] != self.total_amount
                    or previous["status"] != self.status
                    or previous["enrollment_id"] != self.enrollment_id
                )
                if changed:
                    raise ValidationError(
                        "A finalized assessment cannot be modified. "
                        "Corrections require an approved exception procedure."
                    )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Assessment #{self.pk} for enrollment #{self.enrollment_id}"


class AssessmentLine(models.Model):
    """One charge line on an assessment.

    Description, quantity, unit amount and line total are snapshots: they are
    not recomputed from fee rules after creation.  ``line_total`` is kept
    consistent with quantity x unit amount.  Lines of a finalized assessment
    cannot be saved or deleted.
    """

    id = models.AutoField(primary_key=True)
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.PROTECT,
        related_name="lines",
        db_column="assessment_id",
    )
    fee_type = models.ForeignKey(
        FeeType, on_delete=models.PROTECT, db_column="fee_type_id"
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=8, decimal_places=2)
    unit_amount = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "assessment_line"
        ordering = ["assessment_id", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="ck_assessment_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_amount__gte=0),
                name="ck_assessment_line_unit_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=0),
                name="ck_assessment_line_total_non_negative",
            ),
        ]

    def compute_line_total(self):
        return (self.quantity * self.unit_amount).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

    def _ensure_not_finalized(self, action):
        if self.assessment_id is None:
            return
        status = (
            Assessment.objects.filter(pk=self.assessment_id)
            .values_list("status", flat=True)
            .first()
        )
        if status == Assessment.Status.FINALIZED:
            raise ValidationError(
                f"Cannot {action} a line of a finalized assessment."
            )

    def save(self, *args, **kwargs):
        self._ensure_not_finalized("modify")
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._ensure_not_finalized("delete")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.description} x{self.quantity} @ {self.unit_amount}"


class Payment(models.Model):
    """A payment received (or expected) from a student.

    Status drives balance calculations: only ``RECEIVED`` payments contribute.
    Payments with allocations must not be cancelled in the initial version
    (enforced by ``finance.services.cancel_payment``).
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        CHECK = "CHECK", "Check"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        ONLINE = "ONLINE", "Online payment"

    id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        "academics.Student",
        on_delete=models.PROTECT,
        related_name="payments",
        db_column="student_id",
    )
    received_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="payments_received",
        db_column="received_by_id",
    )
    receipt_number = models.CharField(max_length=40)
    payment_date = models.DateTimeField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    class Meta:
        db_table = "payment"
        ordering = ["-payment_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt_number"], name="uq_payment_receipt_number"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="ck_payment_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.receipt_number} - {self.amount} ({self.status})"


class PaymentAllocation(models.Model):
    """Amount of a payment applied to one assessment.

    Aggregate rules (allocation not exceeding the payment or the assessment's
    remaining balance, and student matching) are enforced transactionally in
    ``finance.services``.
    """

    id = models.AutoField(primary_key=True)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="allocations",
        db_column="payment_id",
    )
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.PROTECT,
        related_name="allocations",
        db_column="assessment_id",
    )
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "payment_allocation"
        ordering = ["payment_id", "assessment_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "assessment"],
                name="uq_payment_allocation_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(allocated_amount__gt=0),
                name="ck_payment_allocation_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.payment.receipt_number} -> assessment #{self.assessment_id}: {self.allocated_amount}"
