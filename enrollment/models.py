from django.db import models
from django.utils import timezone


class Enrollment(models.Model):
    """One student's enrollment for one academic term."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        "academics.Student", on_delete=models.PROTECT, db_column="student_id"
    )
    term = models.ForeignKey(
        "academics.AcademicTerm",
        on_delete=models.PROTECT,
        db_column="term_id",
    )
    enrollment_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    class Meta:
        db_table = "enrollment"
        ordering = ["-enrollment_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "term"],
                name="uq_enrollment_student_term",
            ),
        ]

    def __str__(self):
        return f"{self.student.student_number} - {self.term}"


class EnrollmentDetail(models.Model):
    """One section added to an enrollment.

    The course is derived from ``section.course``; no redundant course column
    is stored.  Uniqueness of (enrollment, section) is enforced by the
    database.  Preventing two sections of the same course in one enrollment is
    a cross-row rule handled by ``enrollment.services``.
    """

    class Status(models.TextChoices):
        ENROLLED = "ENROLLED", "Enrolled"
        DROPPED = "DROPPED", "Dropped"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        COMPLETED = "COMPLETED", "Completed"

    id = models.AutoField(primary_key=True)
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="details",
        db_column="enrollment_id",
    )
    section = models.ForeignKey(
        "scheduling.Section",
        on_delete=models.PROTECT,
        related_name="enrollment_details",
        db_column="section_id",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ENROLLED
    )
    enrolled_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "enrollment_detail"
        ordering = ["enrollment_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "section"],
                name="uq_enrollment_detail_section",
            ),
        ]

    @property
    def course(self):
        """Course for this detail, derived through the section."""
        return self.section.course

    def __str__(self):
        return f"{self.enrollment} -> {self.section}"


class StudentCourseResult(models.Model):
    """Final result for one enrollment detail.

    Prerequisite checks treat ``PASSED`` as satisfying a prerequisite; merely
    having enrolled in (or dropped) the prerequisite course does not.
    """

    class ResultStatus(models.TextChoices):
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"
        INCOMPLETE = "INCOMPLETE", "Incomplete"
        DROPPED = "DROPPED", "Dropped"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    id = models.AutoField(primary_key=True)
    enrollment_detail = models.OneToOneField(
        EnrollmentDetail,
        on_delete=models.PROTECT,
        related_name="result",
        db_column="enrollment_detail_id",
    )
    final_grade = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True
    )
    result_status = models.CharField(max_length=20, choices=ResultStatus.choices)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "student_course_result"
        ordering = ["-recorded_at"]

    @property
    def is_passing(self):
        return self.result_status == self.ResultStatus.PASSED

    def __str__(self):
        return f"{self.enrollment_detail} - {self.result_status}"
