from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user.

    Extends ``AbstractUser`` so Django's authentication, password hashing and
    permission machinery work unchanged.  ``role`` is a coarse-grained label
    used for authorisation decisions; fine-grained permissions still come from
    Django's groups/permissions tables.
    """

    class Role(models.TextChoices):
        ADMINISTRATOR = "ADMINISTRATOR", "Administrator"
        REGISTRAR = "REGISTRAR", "Registrar"
        CASHIER = "CASHIER", "Cashier"
        INSTRUCTOR = "INSTRUCTOR", "Instructor"
        STUDENT = "STUDENT", "Student"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
    )

    class Meta:
        db_table = "app_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.get_username()
