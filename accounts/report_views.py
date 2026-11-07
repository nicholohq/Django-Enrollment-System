"""Read-only institutional reports with CSV export and print-friendly HTML.

Three reports: enrolled students per course/year level, total enrollment per
semester, and finance collections. Every view is server-side role-gated. These
views never write to the database; figures come from the existing models and
finance services (no competing calculation system).

Export formats: ``?format=csv`` streams a UTF-8 (BOM) CSV with formula-injection
-safe cells; the HTML page itself is print-friendly (Print button + the shared
print CSS) for browser "Save as PDF".
"""

import csv
from decimal import Decimal

from django import forms
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.models import User
from accounts.permissions import role_required
from academics.models import AcademicTerm, College, Course, Program
from enrollment.models import Enrollment, EnrollmentDetail
from finance.models import Payment, ScholarshipAward
from finance.services import local_day_range
from scheduling.models import Section

ZERO = Decimal("0.00")


# --- helpers --------------------------------------------------------------
def _csv_safe(value):
    """Neutralize values a spreadsheet could read as a formula."""
    s = "" if value is None else str(value)
    if s[:1] in ("=", "+", "-", "@"):
        s = "'" + s
    return s


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # UTF-8 BOM so Excel detects encoding
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_safe(cell) for cell in row])
    return response


def _stamp():
    return timezone.localtime().strftime("%Y%m%d-%H%M%S")


def _money(value):
    return f"{(value or ZERO):.2f}"


def _int(request, name):
    raw = request.GET.get(name)
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


# --- Report A: enrolled students per course and year level ----------------
def _enrolled_rows(request):
    qs = (
        EnrollmentDetail.objects.filter(status=EnrollmentDetail.Status.ENROLLED)
        .exclude(enrollment__status=Enrollment.Status.CANCELLED)
        .select_related(
            "enrollment__term",
            "enrollment__student__user",
            "enrollment__student__curriculum__program__college",
            "section__course",
        )
    )
    term = _int(request, "term")
    college = _int(request, "college")
    program = _int(request, "program")
    course = _int(request, "course")
    year_level = _int(request, "year_level")
    section = _int(request, "section")
    if term:
        qs = qs.filter(enrollment__term_id=term)
    if college:
        qs = qs.filter(enrollment__student__curriculum__program__college_id=college)
    if program:
        qs = qs.filter(enrollment__student__curriculum__program_id=program)
    if course:
        qs = qs.filter(section__course_id=course)
    if year_level:
        qs = qs.filter(enrollment__student__year_level=year_level)
    if section:
        qs = qs.filter(section_id=section)
    qs = qs.order_by(
        "enrollment__term__academic_year", "enrollment__term__semester_number",
        "section__course__course_code", "section__section_code",
        "enrollment__student__student_number",
    )
    rows = []
    for d in qs:
        student = d.enrollment.student
        program_obj = student.curriculum.program
        rows.append({
            "term": str(d.enrollment.term),
            "college": program_obj.college.name,
            "program": program_obj.program_code,
            "course_code": d.section.course.course_code,
            "course_title": d.section.course.title,
            "year_level": student.year_level,
            "section": d.section.section_code,
            "student_number": student.student_number,
            "student_name": student.user.get_full_name() or student.user.username,
            "status": d.enrollment.get_status_display(),
        })
    return rows


@role_required(User.Role.REGISTRAR, User.Role.ADMINISTRATOR)
def enrolled_report(request):
    rows = _enrolled_rows(request)
    if request.GET.get("format") == "csv":
        header = ["Academic Term", "College", "Program", "Course Code",
                  "Course Title", "Year Level", "Section", "Student No.",
                  "Student Name", "Enrollment Status"]
        data = [[r["term"], r["college"], r["program"], r["course_code"],
                 r["course_title"], r["year_level"], r["section"],
                 r["student_number"], r["student_name"], r["status"]] for r in rows]
        return _csv_response(f"enrolled-students-{_stamp()}.csv", header, data)
    context = {
        "rows": rows,
        "terms": AcademicTerm.objects.all(),
        "colleges": College.objects.all(),
        "programs": Program.objects.select_related("college").all(),
        "courses": Course.objects.all(),
        "sections": Section.objects.select_related("course", "term").all(),
        "filters": request.GET,
        "generated_at": timezone.localtime(),
        "title": "Enrolled Students per Course and Year Level",
        "csv_url": "?" + request.GET.urlencode() + ("&" if request.GET else "") + "format=csv",
    }
    return render(request, "reports/enrolled.html", context)


# --- Report B: total enrollment per semester ------------------------------
def _semester_rows(request):
    terms = AcademicTerm.objects.all().order_by("-academic_year", "semester_number")
    year = request.GET.get("academic_year") or None
    semester = _int(request, "semester")
    if year:
        terms = terms.filter(academic_year=year)
    if semester:
        terms = terms.filter(semester_number=semester)
    rows = []
    for term in terms:
        active = Enrollment.objects.filter(term=term).exclude(
            status=Enrollment.Status.CANCELLED)
        distinct_students = active.values("student").distinct().count()
        records = active.count()
        breakdown = list(
            active.values(
                "student__curriculum__program__program_code",
                "student__curriculum__program__college__name",
            ).annotate(
                students=Count("student", distinct=True),
                enrollments=Count("id"),
            ).order_by("student__curriculum__program__program_code")
        )
        rows.append({
            "term": term, "academic_year": term.academic_year,
            "semester": term.semester_number,
            "distinct_students": distinct_students, "records": records,
            "breakdown": breakdown,
        })
    return rows


@role_required(User.Role.REGISTRAR, User.Role.ADMINISTRATOR)
def semester_report(request):
    rows = _semester_rows(request)
    if request.GET.get("format") == "csv":
        header = ["Academic Year", "Semester", "Distinct Students",
                  "Active Enrollment Records"]
        data = [[r["academic_year"], r["semester"], r["distinct_students"],
                 r["records"]] for r in rows]
        return _csv_response(f"enrollment-per-semester-{_stamp()}.csv", header, data)
    context = {
        "rows": rows,
        "years": AcademicTerm.objects.values_list("academic_year", flat=True).distinct(),
        "filters": request.GET,
        "generated_at": timezone.localtime(),
        "title": "Total Enrollment per Semester",
        "csv_url": "?" + request.GET.urlencode() + ("&" if request.GET else "") + "format=csv",
    }
    return render(request, "reports/semester.html", context)


# --- Report C: collection report ------------------------------------------
class CollectionReportFilterForm(forms.Form):
    """Validate the optional collection-report date range.

    Using Django's own ``DateField`` validation means a malformed (``notadate``)
    or impossible (``2026-13-45``) value is reported as a clear field error
    instead of raising an unhandled error inside the ORM date lookup (HTTP 500).
    Both fields are optional, so missing/empty dates simply apply no date filter.
    """

    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError(
                "The start date must be on or before the end date."
            )
        return cleaned


def _collection_data(request, *, date_from=None, date_to=None):
    payments = Payment.objects.filter(status=Payment.Status.RECEIVED)
    scholarships = ScholarshipAward.objects.filter(
        status__in=[ScholarshipAward.Status.APPROVED, ScholarshipAward.Status.APPLIED]
    )
    term = _int(request, "term")
    method = request.GET.get("method") or None
    if term:
        payments = payments.filter(assessment__enrollment__term_id=term)
        scholarships = scholarships.filter(assessment__enrollment__term_id=term)
    if method:
        payments = payments.filter(method=method)
    start, end = local_day_range(date_from, date_to)
    if start:
        payments = payments.filter(payment_date__gte=start)
    if end:
        payments = payments.filter(payment_date__lt=end)

    by_method = list(
        payments.values("method").annotate(
            count=Count("id"), total=Sum("amount")
        ).order_by("method")
    )
    payments_total = payments.aggregate(total=Sum("amount"))["total"] or ZERO
    payments_count = payments.count()
    scholarship_total = scholarships.aggregate(total=Sum("amount"))["total"] or ZERO
    scholarship_count = scholarships.count()
    return {
        "by_method": by_method, "payments_total": payments_total,
        "payments_count": payments_count, "scholarship_total": scholarship_total,
        "scholarship_count": scholarship_count,
    }


@role_required(User.Role.CASHIER, User.Role.ADMINISTRATOR)
def collection_report(request):
    filter_form = CollectionReportFilterForm(request.GET)
    valid = filter_form.is_valid()
    if valid:
        data = _collection_data(
            request,
            date_from=filter_form.cleaned_data.get("date_from"),
            date_to=filter_form.cleaned_data.get("date_to"),
        )
        # CSV export only for valid filters; invalid input never streams a file
        # or runs an unrestricted report (it falls through to the HTML page).
        if request.GET.get("format") == "csv":
            header = ["Payment Method", "Confirmed Count", "Confirmed Amount"]
            rows = [[m["method"], m["count"], _money(m["total"])] for m in data["by_method"]]
            rows.append(["TOTAL RECORDED COLLECTIONS", data["payments_count"], _money(data["payments_total"])])
            rows.append(["SCHOLARSHIP FUNDING (separate, not cash)", data["scholarship_count"], _money(data["scholarship_total"])])
            return _csv_response(f"collection-report-{_stamp()}.csv", header, rows)
    else:
        # Invalid dates: show the page with validation errors and no results.
        data = {
            "by_method": [], "payments_total": ZERO, "payments_count": 0,
            "scholarship_total": ZERO, "scholarship_count": 0,
        }
    context = {
        **data,
        "method_choices": Payment.Method.choices,
        "terms": AcademicTerm.objects.all(),
        "filters": request.GET,
        "filter_form": filter_form,
        "generated_at": timezone.localtime(),
        "title": "Collection Report",
        "csv_url": "?" + request.GET.urlencode() + ("&" if request.GET else "") + "format=csv",
    }
    return render(request, "reports/collection.html", context)


@role_required(
    User.Role.REGISTRAR, User.Role.ADMINISTRATOR, User.Role.CASHIER
)
def reports_index(request):
    role = getattr(request.user, "role", None)
    return render(request, "reports/index.html", {"role": role})
