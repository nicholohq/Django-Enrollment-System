from django.db import models


class Room(models.Model):
    """A physical room that can host section meetings."""

    id = models.AutoField(primary_key=True)
    room_code = models.CharField(max_length=30)
    building = models.CharField(max_length=100, null=True, blank=True)
    capacity = models.IntegerField()

    class Meta:
        db_table = "room"
        ordering = ["room_code"]
        constraints = [
            models.UniqueConstraint(fields=["room_code"], name="uq_room_room_code"),
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1),
                name="ck_room_capacity_positive",
            ),
        ]

    def __str__(self):
        return self.room_code


class Section(models.Model):
    """An offering of a course in a term, taught by one instructor."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.AutoField(primary_key=True)
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, db_column="course_id"
    )
    term = models.ForeignKey(
        "academics.AcademicTerm", on_delete=models.PROTECT, db_column="term_id"
    )
    section_code = models.CharField(max_length=20)
    instructor = models.ForeignKey(
        "academics.Instructor",
        on_delete=models.PROTECT,
        db_column="instructor_id",
    )
    capacity = models.IntegerField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )

    class Meta:
        db_table = "section"
        ordering = ["term_id", "course_id", "section_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "term", "section_code"],
                name="uq_section_course_term_code",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1),
                name="ck_section_capacity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.course.course_code} {self.section_code} ({self.term})"


class SectionMeeting(models.Model):
    """A weekly meeting slot for a section."""

    class DayOfWeek(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    id = models.AutoField(primary_key=True)
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="meetings",
        db_column="section_id",
    )
    room = models.ForeignKey(
        Room, on_delete=models.PROTECT, db_column="room_id"
    )
    day_of_week = models.IntegerField(choices=DayOfWeek.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        db_table = "section_meeting"
        ordering = ["section_id", "day_of_week", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "day_of_week", "start_time"],
                name="uq_section_meeting_slot",
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="ck_section_meeting_time_range",
            ),
        ]

    def __str__(self):
        return (
            f"{self.section} - {self.get_day_of_week_display()} "
            f"{self.start_time}-{self.end_time} @ {self.room.room_code}"
        )
