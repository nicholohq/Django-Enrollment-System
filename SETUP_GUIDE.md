# Setup Guide — ADS Enrollment System

How to install and run the **Django Enrollment System** (branded *Holy Trinity University · Enrollment
System*) on your own **Windows** computer.

This is a **setup guide only** — it covers installing and starting the app, not testing it.

---

## 1. Introduction

- **What it is:** a college enrollment management system built with **Django 5.2** and **MySQL**. It
  provides role-based logins and dashboards, academic master data, student/instructor profiles, section
  scheduling, enrollment, and a finance workflow.
- **What this guide covers:** getting the project running locally — prerequisites, installation, MySQL,
  environment configuration, database setup, running the server, and logging in. Plus troubleshooting.
- **Audience:** classmates/groupmates who may be new to Django and MySQL. Follow the steps in order.

> All commands below are **Windows PowerShell**. Lines starting with `#` are comments/optional notes.

---

## 2. System Requirements

**Required software** (verified against the project):

| Software | Version | Notes |
| --- | --- | --- |
| Windows | 10 or 11 | Commands use PowerShell. |
| Python | 3.13.7 (3.10+ works; 3.13.7 verified) | Check "Add Python to PATH" when installing. |
| MySQL Server | 8.0+ (9.5.0 verified) | **Required** — the project has no SQLite fallback. |
| Git | any recent version | To clone the repository. |

**Python packages** (installed later via `pip`, from `requirements.txt`): Django 5.2.18,
mysqlclient 2.3.0, asgiref 3.13.0, sqlparse 0.6.0, tzdata 2026.5.

**Optional tools**
- **MySQL Workbench** — a GUI for creating/browsing the database (optional; the command line works too).
- **Visual C++ Build Tools** — only needed if `pip install mysqlclient` has to compile from source and
  fails; most installs use a prebuilt wheel and won't need this.

**Hardware / OS:** any computer that can run Python, MySQL, and a browser. (No specific minimum is
defined in the repository — *flag:* not verifiable from source.)

---

## 3. Installation

1. **Clone the repository** (into a folder of your choice):
   ```powershell
   cd C:\Users\you\Documents
   git clone https://github.com/nicholohq/Django-Enrollment-System.git
   ```
2. **Open the project directory:**
   ```powershell
   cd .\Django-Enrollment-System
   ```
   *What this is:* the folder containing `manage.py`, `requirements.txt`, and `.env.example`.
3. **Create a Python virtual environment** (an isolated space for this project's packages):
   ```powershell
   python -m venv .venv
   ```
4. **Activate the environment** (do this in every new PowerShell window):
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   Your prompt should now begin with `(.venv)`.
   - **Windows-specific:** if PowerShell blocks the activation script, run this once for the session,
     then activate again:
     ```powershell
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     ```
5. **Install dependencies:**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
   *What this does:* installs Django and the other pinned packages into your virtual environment.
   - **If `mysqlclient` fails to build:** install **Visual C++ Build Tools**, or use a Python version that
     has a prebuilt `mysqlclient` wheel, then re-run the install.

**Expected result:** `pip list` shows Django 5.2.18 and mysqlclient 2.3.0, and no install errors.

---

## 4. MySQL Setup

1. **Install MySQL Server** (8.0+; 9.5.0 verified) and make sure the service is **running**.
   - Check/start the service (Run PowerShell as Administrator if needed):
     ```powershell
     Get-Service -Name '*MySQL*'
     # If it is stopped, start it (service name varies, e.g. MySQL80):
     # Start-Service MySQL80
     ```
2. **Create your local development database.** Use a name you control (the project's default example is
   `ads_enrollment_simplified`; you may keep that or choose your own — just match it in `.env`):
   ```powershell
   mysql -u root -p -e "CREATE DATABASE ads_enrollment_simplified CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
   ```
   *Or in **MySQL Workbench**:* open a SQL tab and run
   `CREATE DATABASE ads_enrollment_simplified CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
3. **Choose database credentials.** Use a MySQL user that can access this database (e.g. `root`, or a
   dedicated user you create). You'll put these in `.env` next (Section 5). **Do not commit credentials.**
4. **Verify the connection:**
   ```powershell
   mysql -u root -p -e "SHOW DATABASES;"
   ```
   **Expected result:** your database (e.g. `ads_enrollment_simplified`) appears in the list.

---

## 5. Environment Configuration

The app reads settings from a local, git-ignored `.env` file (real environment variables take precedence
over `.env`).

1. **Create `.env` from the template:**
   ```powershell
   Copy-Item .env.example .env
   ```
2. **Edit `.env`** and set your own values. The template contains exactly these variables:

   | Variable | What it is | Who sets it | Example |
   | --- | --- | --- | --- |
   | `DJANGO_SECRET_KEY` | Django's cryptographic key | **You** (any long random string for local dev) | `replace-with-a-long-random-value` |
   | `DJANGO_DEBUG` | Debug mode (local only) | Leave `True` for local setup | `True` |
   | `DJANGO_ALLOWED_HOSTS` | Hosts allowed to serve the app | Leave as-is | `localhost,127.0.0.1` |
   | `DB_NAME` | Your database name | **You** (match Section 4) | `ads_enrollment_simplified` |
   | `DB_USER` | MySQL username | **You** | `root` |
   | `DB_PASSWORD` | MySQL password | **You** (your own — never share/commit) | *(your password)* |
   | `DB_HOST` | Database host | Usually `localhost` | `localhost` |
   | `DB_PORT` | Database port | Usually `3306` | `3306` |

   **Each groupmate must set their own `DB_NAME`, `DB_USER`, `DB_PASSWORD`** (and a `DJANGO_SECRET_KEY`)
   to match their local MySQL. **Never put real passwords or secrets in this guide, in chat, or in Git.**

**Expected result:** `.env` exists in the project root with your local values; it stays **uncommitted**
(it is listed in `.gitignore`).

---

## 6. Django Setup

Run these from the project root with the virtual environment **activated**.

1. **Apply database migrations** (creates all the tables in your database):
   ```powershell
   python manage.py migrate
   ```
   **Expected result:** a list of migrations ending in `... OK`, no errors.

2. **Prepare accounts to log in with.** Choose **one** of the following:

   **Option A — Load the demo dataset (recommended for groupmates).** Creates demo users plus sample
   academic and finance data:
   ```powershell
   python manage.py seed_demo --commit
   ```
   - Preview first without changing anything (optional): `python manage.py seed_demo --dry-run`
   - **Safe to re-run:** it does not duplicate rows and never resets an existing account's password/role.
   - Demo usernames and the shared demo password are covered in Section 8.

   **Option B — Create your own administrator account.** New users default to the **Student** role, and the
   custom `/admin/` site needs the **Administrator** role, so promote the account after creating it:
   ```powershell
   python manage.py createsuperuser
   # then promote it to Administrator (replace YOUR_USERNAME):
   python manage.py shell -c "from accounts.models import User; u = User.objects.get(username='YOUR_USERNAME'); u.role = User.Role.ADMINISTRATOR; u.save(update_fields=['role'])"
   ```
   *Do not keep a real/development password in source control.*

> **Optional sanity checks** (do not change anything):
> ```powershell
> python manage.py check
> python manage.py showmigrations
> ```

---

## 7. Running the Application

1. **Start the development server:**
   ```powershell
   python manage.py runserver
   ```
2. **Open the app** at <http://127.0.0.1:8000/> (login page: <http://127.0.0.1:8000/login/>; the
   Administrator-only Django admin is at <http://127.0.0.1:8000/admin/>).
3. **Stop the server:** press **Ctrl + C** in the PowerShell window.
4. **If port 8000 is already in use** (`Error: That port is already in use.`), run on another port:
   ```powershell
   python manage.py runserver 127.0.0.1:8010
   ```
   Then browse to <http://127.0.0.1:8010/>.

**Expected result:** the terminal shows "Starting development server at http://127.0.0.1:8000/" and the
login page loads in your browser.

---

## 8. Logging In

**User roles** (the `role` field on the account controls access):

| Role | Access summary |
| --- | --- |
| Administrator | Oversight: approvals (scholarships/adjustments), payment reversals, all reports, read-only academic/people/section/enrollment screens; `/admin/` if a staff superuser. |
| Registrar | Manages academic data, people, sections, enrollments; finalizes/revises assessments; submits scholarships/adjustments. |
| Cashier | Records payments, prints receipts, submits scholarships/adjustments, views the collection report. |
| Student | Views only their own enrollment records (read-only). |
| Instructor | Dashboard only (no section/grading screens yet). |

**Getting test accounts**
- If you ran **`seed_demo --commit`** (Section 6, Option A), these demo accounts exist:

  | Username | Role |
  | --- | --- |
  | `demo.admin1` | Administrator |
  | `demo.registrar1`, `demo.registrar2` | Registrar |
  | `demo.cashier1`, `demo.cashier2` | Cashier |
  | `demo.instr1` … `demo.instr5` | Instructor |
  | `demo.stud01` … `demo.stud15` | Student (`demo.stud15` is inactive and cannot log in) |

- **Demo password:** all demo accounts share one password, defined as the `DEMO_PASSWORD` constant in
  `accounts/management/commands/seed_demo.py`. Read it from that file locally or ask your group lead.
  **Never paste the password into this guide, screenshots, chat, or Git.**
- If you used **Option B**, log in with the administrator account you created.

After login, `/dashboard/` automatically redirects you to the dashboard for your role.

---

## 9. Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `python` not found / wrong version | Python not installed or not on PATH | Reinstall Python with "Add to PATH"; reopen PowerShell. |
| `Activate.ps1 cannot be loaded ...` | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. |
| `(.venv)` not showing / `ModuleNotFoundError: django` | Virtual environment not activated / deps not installed | Activate `.venv`, then `pip install -r requirements.txt`. |
| `pip install` fails on `mysqlclient` | Missing C build tools | Install **Visual C++ Build Tools**, or use a Python version with a prebuilt wheel. |
| `Can't connect to MySQL server (2003)` | MySQL service not running | Start the MySQL service (`Start-Service MySQL80` as admin). |
| `Access denied for user ...` | Wrong `DB_USER`/`DB_PASSWORD` | Correct the credentials in `.env`. |
| `Unknown database '...'` | DB not created / `DB_NAME` mismatch | Create the DB (Section 4) and match `DB_NAME` in `.env`. |
| Settings/`ImproperlyConfigured` errors | Missing `.env` | `Copy-Item .env.example .env` and fill it in. |
| `migrate` errors / tables missing | Migrations not applied, or DB not reachable | Fix the DB connection first, then `python manage.py migrate`. |
| `Error: That port is already in use.` | Port 8000 busy | `python manage.py runserver 127.0.0.1:8010`. |
| Can't log in | No accounts yet, or using `demo.stud15` (inactive) | Run `seed_demo --commit` (or create a superuser); use an active account with the correct demo password. |

---

## 10. Important Notes

- **Use your own local database.** Each groupmate runs their own MySQL and their own `.env`.
- **Do not use another developer's database credentials** or connect to anyone else's database.
- **Never commit `.env`** or any secret/credential (it is git-ignored for this reason).
- **Do not reset or delete databases without authorization**, especially shared ones.
- `DEBUG=True` and the insecure default secret-key fallback are for **local development only** — never use
  them for a public or production deployment.

---

### Notes / items to confirm
- **Default server port** is `8000`; use another port if it's busy (Section 7).
- **Demo password value** is intentionally not included here — read it from
  `accounts/management/commands/seed_demo.py` or ask your group lead.
- **Minimum hardware/OS specs** are not defined in the repository, so none are stated beyond "runs
  Python + MySQL + a browser."
- The project's `README.md` describes an earlier phase for some areas (e.g., finance); this guide sticks
  to **installation/run steps**, which are current. If a command behaves differently on your machine,
  ask rather than guessing.
