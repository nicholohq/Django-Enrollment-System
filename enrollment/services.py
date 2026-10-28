"""Transactional enrollment rules that cannot be expressed as row constraints."""

from django.core.exceptions import ValidationError
from django.db import transaction

from academics.models import Course, CoursePrerequisite
from scheduling.models import Section

from .models import Enrollment, EnrollmentDetail, StudentCourseResult

# Statuses that still occupy a slot in a course for duplicate-course checks.
BLOCKING_DETAIL_STATUSES = (
    EnrollmentDetail.Status.ENROLLED,
    EnrollmentDetail.Status.COMPLETED,
)


def _passed_course_ids(student):
    return set(
        StudentCourseResult.objects.filter(
            enrollment_detail__enrollment__student=student,
            result_status=StudentCourseResult.ResultStatus.PASSED,
        ).values_list("enrollment_detail__section__course_id", flat=True)
    )


def missing_prerequisites(student, course):
    """Return prerequisite courses the student has not passed.

    Enrollment in a prerequisite is not sufficient - a ``PASSED`` result is
    required.
    """
    required_ids = set(
        CoursePrerequisite.objects.filter(course=course).values_list(
            "prerequisite_course_id", flat=True
        )
    )
    if not required_ids:
        return []
    passed_ids = _passed_course_ids(student)
    missing_ids = required_ids - passed_ids
    return list(Course.objects.filter(pk__in=missing_ids).order_by("course_code"))


@transaction.atomic
def enroll_in_section(*, enrollment, section):
    """Add a section to an enrollment after validating the enrollment rules.

    Locks the enrollment and section rows so concurrent requests cannot both
    pass the duplicate-course or capacity checks.

    Rules enforced here:
      * the section belongs to the enrollment's term;
      * the section is open;
      * the student is not already enrolled in the same course (any section);
      * the section is not full;
      * all prerequisites are passed.
    """
    enrollment = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
    section = Section.objects.select_for_update().get(pk=section.pk)

    if enrollment.status == Enrollment.Status.CANCELLED:
        raise ValidationError("Cannot add sections to a cancelled enrollment.")
    if section.term_id != enrollment.term_id:
        raise ValidationError("The section belongs to a different academic term.")
    if section.status != Section.Status.OPEN:
        raise ValidationError("The section is not open for enrollment.")

    if EnrollmentDetail.objects.filter(
        enrollment=enrollment, section=section
    ).exists():
        raise ValidationError("This section is already part of the enrollment.")

    duplicate_course = EnrollmentDetail.objects.filter(
        enrollment=enrollment,
        section__course_id=section.course_id,
        status__in=BLOCKING_DETAIL_STATUSES,
    ).exists()
    if duplicate_course:
        raise ValidationError(
            "The student is already enrolled in another section of this course. "
            "Multiple sections of the same course are not allowed in one enrollment."
        )

    enrolled_count = EnrollmentDetail.objects.filter(
        section=section, status=EnrollmentDetail.Status.ENROLLED
    ).count()
    if enrolled_count >= section.capacity:
        raise ValidationError("The section has reached its capacity.")

    missing = missing_prerequisites(enrollment.student, section.course)
    if missing:
        codes = ", ".join(course.course_code for course in missing)
        raise ValidationError(
            f"Prerequisite course(s) not passed: {codes}."
        )

    return EnrollmentDetail.objects.create(
        enrollment=enrollment, section=section, status=EnrollmentDetail.Status.ENROLLED
    )


@transaction.atomic
def drop_enrollment_detail(*, detail, withdrawn=False):
    """Mark a detail as dropped or withdrawn, preserving the record."""
    detail = EnrollmentDetail.objects.select_for_update().get(pk=detail.pk)
    detail.status = (
        EnrollmentDetail.Status.WITHDRAWN
        if withdrawn
        else EnrollmentDetail.Status.DROPPED
    )
    detail.save(update_fields=["status"])
    return detail
