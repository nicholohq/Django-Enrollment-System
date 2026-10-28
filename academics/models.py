from django.conf import settings
from django.db import models
from django.utils import timezone


class College(models.Model):
    """Top-level academic unit (e.g. College of Engineering)."""

    id = models.AutoField(primary_key=True)
    college_code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "college"
        ordering = ["college_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["college_code"], name="uq_college_college_code"
            ),
        ]

    def __str__(self):
        return f"{self.college_code} - {self.name}"


class Program(models.Model):
    """Degree program offered by a college."""

    id = models.AutoField(primary_key=True)
    college = models.ForeignKey(
        College, on_delete=models.PROTECT, db_column="college_id"
    )
    program_code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "program"
        ordering = ["program_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program_code"], name="uq_program_program_code"
            ),
        ]

    def __str__(self):
        return f"{self.program_code} - {self.name}"


class Curriculum(models.Model):
    """A specific version of a program's study plan."""

    id = models.AutoField(primary_key=True)
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, db_column="program_id"
    )
    curriculum_code = models.CharField(max_length=30)
    effective_year = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "curriculum"
        ordering = ["program_id", "curriculum_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "curriculum_code"],
                name="uq_curriculum_program_code",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_year__gte=1),
                name="ck_curriculum_effective_year_positive",
            ),
        ]

    def __str__(self):
        return f"{self.program.program_code} {self.curriculum_code}"


class Course(models.Model):
    """A catalogue course, independent of when it is offered."""

    id = models.AutoField(primary_key=True)
    course_code = models.CharField(max_length=20)
    title = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    units = models.DecimalField(max_digits=4, decimal_places=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "course"
        ordering = ["course_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["course_code"], name="uq_course_course_code"
            ),
            models.CheckConstraint(
                condition=models.Q(units__gt=0),
                name="ck_course_units_positive",
            ),
        ]

    def __str__(self):
        return f"{self.course_code} - {self.title}"


class CurriculumCourse(models.Model):
    """Placement of a course within a curriculum version."""

    class Category(models.TextChoices):
        CORE = "CORE", "Core"
        MAJOR = "MAJOR", "Major"
        ELECTIVE = "ELECTIVE", "Elective"
        GENERAL_EDUCATION = "GENERAL_EDUCATION", "General Education"
        PHYSICAL_EDUCATION = "PHYSICAL_EDUCATION", "Physical Education"
        NSTP = "NSTP", "NSTP"

    id = models.AutoField(primary_key=True)
    curriculum = models.ForeignKey(
        Curriculum, on_delete=models.PROTECT, db_column="curriculum_id"
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, db_column="course_id"
    )
    year_level = models.IntegerField()
    recommended_semester = models.IntegerField()
    course_category = models.CharField(max_length=30, choices=Category.choices)

    class Meta:
        db_table = "curriculum_course"
        ordering = ["curriculum_id", "year_level", "recommended_semester"]
        constraints = [
            models.UniqueConstraint(
                fields=["curriculum", "course"],
                name="uq_curriculum_course_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(year_level__gte=1),
                name="ck_curriculum_course_year_level_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(recommended_semester__gte=1),
                name="ck_curriculum_course_semester_positive",
            ),
        ]

    def __str__(self):
        return f"{self.curriculum} / {self.course.course_code}"


class CoursePrerequisite(models.Model):
    """A course that must be passed before another course may be taken.

    Uses a surrogate INT primary key (instead of the SQL script's composite
    key) while preserving uniqueness of the (course, prerequisite) pair.
    """

    id = models.AutoField(primary_key=True)
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="prerequisites",
        db_column="course_id",
    )
    prerequisite_course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="required_for",
        db_column="prerequisite_course_id",
    )

    class Meta:
        db_table = "course_prerequisite"
        ordering = ["course_id", "prerequisite_course_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "prerequisite_course"],
                name="uq_course_prerequisite_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(course=models.F("prerequisite_course")),
                name="ck_course_prerequisite_not_self",
            ),
        ]

    def __str__(self):
        return f"{self.course.course_code} requires {self.prerequisite_course.course_code}"


class AcademicTerm(models.Model):
    """A term (academic year + semester) in which sections are offered."""

    id = models.AutoField(primary_key=True)
    academic_year = models.CharField(max_length=9)
    semester_number = models.IntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    enrollment_open = models.BooleanField(default=False)

    class Meta:
        db_table = "academic_term"
        ordering = ["-academic_year", "semester_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "semester_number"],
                name="uq_academic_term_year_semester",
            ),
            models.CheckConstraint(
                condition=models.Q(semester_number__gte=1),
                name="ck_academic_term_semester_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="ck_academic_term_date_range",
            ),
        ]

    def __str__(self):
        return f"{self.academic_year} - Semester {self.semester_number}"


class Student(models.Model):
    """Student profile linked one-to-one to an application user.

    ``email`` is intentionally independent of ``User.email``; the two are not
    synchronised automatically.
    """

    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="user_id",
    )
    student_number = models.CharField(max_length=30)
    curriculum = models.ForeignKey(
        Curriculum, on_delete=models.PROTECT, db_column="curriculum_id"
    )
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100)
    birth_date = models.DateField(null=True, blank=True)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=30, null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    year_level = models.IntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "student"
        ordering = ["student_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["student_number"], name="uq_student_student_number"
            ),
            models.CheckConstraint(
                condition=models.Q(year_level__gte=1),
                name="ck_student_year_level_positive",
            ),
        ]

    def __str__(self):
        return f"{self.student_number} - {self.last_name}, {self.first_name}"


class Instructor(models.Model):
    """Instructor profile linked one-to-one to an application user."""

    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="user_id",
    )
    employee_number = models.CharField(max_length=30)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    class Meta:
        db_table = "instructor"
        ordering = ["employee_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee_number"], name="uq_instructor_employee_number"
            ),
        ]

    def __str__(self):
        return f"{self.employee_number} - {self.last_name}, {self.first_name}"
