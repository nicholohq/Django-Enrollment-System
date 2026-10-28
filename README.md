# Django College Enrollment System

A reusable, generic college-level enrollment management system built with Django and
MySQL. It models a semester-based academic structure and provides the data layer,
constraints, and transactional service rules needed for academic records, curriculum
management, class scheduling, enrollment, assessment, and payment tracking.

The project is intended as a foundation: the domain models and service-layer rules are
implemented, while the user-facing interface is not yet built (see
[Current limitations](#current-limitations)).

## Technology stack

| Component | Version |
| --- | --- |
| Python | 3.13.7 |
| Django | 5.2.18 |
| MySQL Server | 9.5.0 |
| mysqlclient | 2.3.0 |
| asgiref | 3.13.0 |
| sqlparse | 0.6.0 |
| tzdata | 2026.5 |

Versions above were verified in the local development environment. Django 5.2 requires
Python 3.10 or newer; this project is developed and tested against Python 3.13.

## Features

The domain is split into five Django applications:

- **accounts** – custom user model (`accounts.User`, table `app_user`) with a coarse
  `role` field (administrator, registrar, cashier, instructor, student) on top of
  Django's authentication, groups, and permissions.
- **academics** – colleges, programs, curricula, courses, curriculum course placement,
  course prerequisites, academic terms, students, and instructors.
- **scheduling** – rooms, course sections offered per term, and weekly section meetings.
- **enrollment** – a student's enrollment per term, its section-level details, and
  final course results.
- **finance** – fee types, scoped fee rules, assessments and assessment lines, payments,
  and payment allocations.

Business rules that span multiple rows are implemented in service modules
(`enrollment/services.py`, `scheduling/services.py`, `finance/services.py`) rather than
inside triggers. Examples include prerequisite checking against passed results,
duplicate-course prevention, room/instructor overlap detection, fee-rule precedence,
assessment finalization immutability, and payment allocation limits.

## Prerequisites

- Python 3.13 (3.10+ should work, but 3.13.7 is the verified version)
- MySQL Server 8.0+ (9.5.0 verified) with a database and user you can use
- A C compiler and Python headers if `mysqlclient` must be built from source
  (on Windows, the Visual C++ Build Tools are typically required)
- Git

## Local setup (Windows PowerShell)

```powershell
# From the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# If PowerShell blocks the activation script for the current session:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Database and environment configuration

1. Create an empty database and a dedicated MySQL user. Example (run in a MySQL client
   as an administrative user, replacing the placeholders):

   ```sql
   CREATE DATABASE ads_enrollment
     CHARACTER SET utf8mb4
     COLLATE utf8mb4_unicode_ci;
   ```

2. Copy the environment template and fill in your own values:

   ```powershell
   Copy-Item .env.example .env
   ```

   `.env` is git-ignored and must never be committed. It supports the following
   variables:

   | Variable | Purpose | Example placeholder |
   | --- | --- | --- |
   | `DJANGO_SECRET_KEY` | Django secret key | `replace-with-a-long-random-value` |
   | `DJANGO_DEBUG` | Debug mode | `True` |
   | `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts | `localhost,127.0.0.1` |
   | `DB_NAME` | Database name | `ads_enrollment` |
   | `DB_USER` | Database user | `your-db-user` |
   | `DB_PASSWORD` | Database password | `your-db-password` |
   | `DB_HOST` | Database host | `localhost` |
   | `DB_PORT` | Database port | `3306` |

   Real environment variables take precedence over values in `.env`.

3. Apply the schema with Django migrations:

   ```powershell
   python manage.py migrate
   ```

4. Create an administrative account and start the development server:

   ```powershell
   python manage.py createsuperuser
   python manage.py runserver
   ```

The application is then available at <http://127.0.0.1:8000/>; the Django admin site is
at <http://127.0.0.1:8000/admin/>.

### Useful commands

```powershell
python manage.py check                        # configuration/model checks
python manage.py makemigrations --check --dry-run  # detect missing migrations
python manage.py showmigrations               # list migration status
python manage.py migrate                      # apply pending migrations
```

Only run `makemigrations` when you have intentionally changed a model; the repository
already contains the initial migrations for all five applications.

## Project structure

```text
.
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── config/                  # Django project package
│   ├── settings.py          # environment-driven configuration
│   ├── urls.py              # currently exposes only the admin site
│   ├── asgi.py
│   └── wsgi.py
├── accounts/                # custom user and roles
│   ├── models.py
│   └── migrations/
├── academics/               # colleges, programs, curricula, courses, terms, people
│   ├── models.py
│   └── migrations/
├── scheduling/              # rooms, sections, meetings
│   ├── models.py
│   ├── services.py
│   └── migrations/
├── enrollment/              # enrollments, details, results
│   ├── models.py
│   ├── services.py
│   └── migrations/
├── finance/                 # fees, assessments, payments, allocations
│   ├── models.py
│   ├── services.py
│   └── migrations/
└── erd_artifacts/           # design reference artifacts (see below)
    ├── ADS_Enrollment_System_Final_Schema_REVISED.sql
    ├── ADS_Enrollment_System_Final_Django_Compatible.mwb
    └── Enrollment System ERD.png
```

Each application also contains the standard Django `admin.py`, `apps.py`, `tests.py`,
and `views.py` modules.

## Migrations are the source of truth

Database schema changes are managed exclusively by Django migrations.

- The initial migrations in each app describe the current schema and have been applied
  to a local development database.
- `python manage.py makemigrations --check --dry-run` reports no pending model changes.
- Always create and apply schema changes through `makemigrations` / `migrate`.

### Reference artifacts

The files under `erd_artifacts/` are **design and documentation artifacts only**:

- `ADS_Enrollment_System_Final_Schema_REVISED.sql` is a schema-only SQL script generated
  from the Django models for use in MySQL Workbench/ERD tooling.
- `ADS_Enrollment_System_Final_Django_Compatible.mwb` is the MySQL Workbench EER model
  that was imported from that script.
- `Enrollment System ERD.png` is an exported diagram image.

Do **not** execute the SQL script against an application database as a substitute for
migrations. It does not record migration state, and running it alongside `migrate`
would conflict with the tables Django creates. If a fresh database is needed, use
`python manage.py migrate`.

## Data model notes

- All application primary keys use integer `AutoField` columns
  (`DEFAULT_AUTO_FIELD = "django.db.models.AutoField"`).
- The custom user model is `accounts.User`, mapped to the `app_user` table. It must be
  configured via `AUTH_USER_MODEL` before the first migration, which is already the case
  here.
- Foreign keys use `on_delete=PROTECT` for historical and referential records.
- Database-level `UniqueConstraint` and `CheckConstraint` entries cover row-level rules;
  cross-row rules live in the service layer.
- `CoursePrerequisite` uses a surrogate integer primary key with a unique
  `(course, prerequisite_course)` pair instead of a composite primary key.
- `EnrollmentDetail` derives its course from the related section; no redundant course
  column is stored.

## Current limitations

Verified against the current source tree:

- **No custom web interface.** `config/urls.py` exposes only `admin/`, and the
  application `views.py` modules are empty stubs.
- **Application models are not registered in the Django admin.** The `admin.py` modules
  are the default generated stubs, so the admin site shows only Django's built-in
  authentication/admin models.
- **Tests are placeholders.** The per-app `tests.py` files contain only the generated
  `TestCase` stub; there is no automated test suite yet.
- **MySQL is required at settings level.** The database engine is fixed to
  `django.db.backends.mysql`; there is no SQLite fallback for local experiments.
- **Development defaults.** `DEBUG` defaults to `True` and a development-only secret key
  fallback exists when `DJANGO_SECRET_KEY` is unset. Both must be overridden for any
  non-development environment, along with `DJANGO_ALLOWED_HOSTS`.
- **Service-layer rules are not database triggers.** Prerequisite checks, duplicate
  course prevention, capacity/overlap checks, fee-rule ambiguity detection, and payment
  allocation limits must be invoked through the provided service functions; direct ORM
  writes bypass them.

## License

No license has been declared for this project. Add one before distributing or accepting
external contributions.
