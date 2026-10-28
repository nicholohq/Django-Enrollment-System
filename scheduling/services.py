"""Scheduling rules that require cross-row inspection."""

from django.core.exceptions import ValidationError

from .models import SectionMeeting


def find_overlapping_meetings(*, section, room, day_of_week, start_time, end_time, exclude_pk=None):
    """Return meetings that overlap the proposed slot in the same room or
    with the same instructor."""
    overlapping = SectionMeeting.objects.filter(
        day_of_week=day_of_week,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_pk is not None:
        overlapping = overlapping.exclude(pk=exclude_pk)
    return overlapping.filter(room=room) | overlapping.filter(
        section__instructor=section.instructor
    )


def validate_section_meeting(*, section, room, day_of_week, start_time, end_time, exclude_pk=None):
    """Validate a section meeting before saving it.

    Checks:
      * start time is before end time;
      * the room can hold the section;
      * neither the room nor the instructor has an overlapping meeting.
    """
    if start_time >= end_time:
        raise ValidationError("A meeting must end after it starts.")

    if room.capacity < section.capacity:
        raise ValidationError(
            "The room capacity is smaller than the section capacity."
        )

    conflicts = find_overlapping_meetings(
        section=section,
        room=room,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        exclude_pk=exclude_pk,
    )
    if conflicts.exists():
        raise ValidationError(
            "The meeting overlaps an existing room or instructor booking."
        )
