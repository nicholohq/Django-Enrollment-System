-- ADS Enrollment System - Final Schema REVISED (Schema-only, MySQL 9.5-compatible)
-- Generated from Django models/migrations - NOT executed against MySQL
-- Purpose: Import into MySQL Workbench to create a NEW ERD
-- Source: Current Django models and migration state

-- BUSINESS RULES (not enforced by DDL):
-- 1. Duplicate course across sections in one enrollment blocked by service layer
-- 2. Prerequisites require PASSED result (not just enrollment)
-- 3. FeeRule precedence: course-specific > program-specific > general; ties rejected by service
-- 4. Only RECEIVED payments count toward balance
-- 5. Cannot cancel payments with allocations; no deletion of history
-- 6. Assessment finalization immutability enforced by model logic
-- 7. Capacity/overlap/term-open checks enforced by service layer
-- 8. enrollment_detail.course derived via section.course (no column)
-- NOTE: Django ORM uses on_delete=PROTECT; native MySQL FKs use RESTRICT/NO ACTION below as valid equivalents.

-- Table: django_content_type
CREATE TABLE django_content_type (
  id INT AUTO_INCREMENT,
  app_label VARCHAR(100) NOT NULL,
  model VARCHAR(100) NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: auth_permission
CREATE TABLE auth_permission (
  id INT AUTO_INCREMENT,
  name VARCHAR(255) NOT NULL,
  content_type_id INT NOT NULL,
  codename VARCHAR(100) NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: auth_group
CREATE TABLE auth_group (
  id INT AUTO_INCREMENT,
  name VARCHAR(150) NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: app_user
CREATE TABLE app_user (
  id INT AUTO_INCREMENT,
  password VARCHAR(128) NOT NULL,
  last_login DATE NULL,
  is_superuser TINYINT(1) NOT NULL DEFAULT 0,
  username VARCHAR(150) NOT NULL,
  first_name VARCHAR(150) NOT NULL,
  last_name VARCHAR(150) NOT NULL,
  email VARCHAR(254) NOT NULL,
  is_staff TINYINT(1) NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  date_joined DATE NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'STUDENT',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: django_session
CREATE TABLE django_session (
  session_key VARCHAR(40) NOT NULL,
  session_data TEXT NOT NULL,
  expire_date DATE NOT NULL,
  PRIMARY KEY (session_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: django_admin_log
CREATE TABLE django_admin_log (
  id INT AUTO_INCREMENT,
  action_time DATE NOT NULL,
  user_id INT NOT NULL,
  content_type_id INT NULL,
  object_id TEXT NULL,
  object_repr VARCHAR(200) NOT NULL,
  action_flag INT NOT NULL,
  change_message TEXT NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: college
CREATE TABLE college (
  id INT AUTO_INCREMENT,
  college_code VARCHAR(20) NOT NULL,
  name VARCHAR(150) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  CONSTRAINT uq_college_college_code UNIQUE (college_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: program
CREATE TABLE program (
  id INT AUTO_INCREMENT,
  college_id INT NOT NULL,
  program_code VARCHAR(20) NOT NULL,
  name VARCHAR(150) NOT NULL,
  description TEXT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  CONSTRAINT uq_program_program_code UNIQUE (program_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: curriculum
CREATE TABLE curriculum (
  id INT AUTO_INCREMENT,
  program_id INT NOT NULL,
  curriculum_code VARCHAR(30) NOT NULL,
  effective_year INT NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  CONSTRAINT uq_curriculum_program_code UNIQUE (program,curriculum_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: course
CREATE TABLE course (
  id INT AUTO_INCREMENT,
  course_code VARCHAR(20) NOT NULL,
  title VARCHAR(150) NOT NULL,
  description TEXT NULL,
  units DECIMAL(4,1) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  CONSTRAINT uq_course_course_code UNIQUE (course_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: curriculum_course
CREATE TABLE curriculum_course (
  id INT AUTO_INCREMENT,
  curriculum_id INT NOT NULL,
  course_id INT NOT NULL,
  year_level INT NOT NULL,
  recommended_semester INT NOT NULL,
  course_category VARCHAR(30) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_curriculum_course_pair UNIQUE (curriculum,course)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: course_prerequisite
CREATE TABLE course_prerequisite (
  id INT AUTO_INCREMENT,
  course_id INT NOT NULL,
  prerequisite_course_id INT NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_course_prerequisite_pair UNIQUE (course,prerequisite_course)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: academic_term
CREATE TABLE academic_term (
  id INT AUTO_INCREMENT,
  academic_year VARCHAR(9) NOT NULL,
  semester_number INT NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  enrollment_open TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  CONSTRAINT uq_academic_term_year_semester UNIQUE (academic_year,semester_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: student
CREATE TABLE student (
  id INT AUTO_INCREMENT,
  user_id INT NOT NULL,
  student_number VARCHAR(30) NOT NULL,
  curriculum_id INT NOT NULL,
  first_name VARCHAR(100) NOT NULL,
  middle_name VARCHAR(100) NULL,
  last_name VARCHAR(100) NOT NULL,
  birth_date DATE NULL,
  email VARCHAR(254) NOT NULL,
  phone VARCHAR(30) NULL,
  address VARCHAR(255) NULL,
  year_level INT NOT NULL,
  created_at DATE NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_student_student_number UNIQUE (student_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: instructor
CREATE TABLE instructor (
  id INT AUTO_INCREMENT,
  user_id INT NOT NULL,
  employee_number VARCHAR(30) NOT NULL,
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_instructor_employee_number UNIQUE (employee_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: room
CREATE TABLE room (
  id INT AUTO_INCREMENT,
  room_code VARCHAR(30) NOT NULL,
  building VARCHAR(100) NULL,
  capacity INT NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_room_room_code UNIQUE (room_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: section
CREATE TABLE section (
  id INT AUTO_INCREMENT,
  course_id INT NOT NULL,
  term_id INT NOT NULL,
  section_code VARCHAR(20) NOT NULL,
  instructor_id INT NOT NULL,
  capacity INT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
  PRIMARY KEY (id),
  CONSTRAINT uq_section_course_term_code UNIQUE (course,term,section_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: section_meeting
CREATE TABLE section_meeting (
  id INT AUTO_INCREMENT,
  section_id INT NOT NULL,
  room_id INT NOT NULL,
  day_of_week INT NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_section_meeting_slot UNIQUE (section,day_of_week,start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: enrollment
CREATE TABLE enrollment (
  id INT AUTO_INCREMENT,
  student_id INT NOT NULL,
  term_id INT NOT NULL,
  enrollment_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
  PRIMARY KEY (id),
  CONSTRAINT uq_enrollment_student_term UNIQUE (student,term)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: enrollment_detail
CREATE TABLE enrollment_detail (
  id INT AUTO_INCREMENT,
  enrollment_id INT NOT NULL,
  section_id INT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'ENROLLED',
  enrolled_at DATE NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_enrollment_detail_section UNIQUE (enrollment,section)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: student_course_result
CREATE TABLE student_course_result (
  id INT AUTO_INCREMENT,
  enrollment_detail_id INT NOT NULL,
  final_grade DECIMAL(4,2) NULL,
  result_status VARCHAR(20) NOT NULL,
  recorded_at DATE NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: fee_type
CREATE TABLE fee_type (
  id INT AUTO_INCREMENT,
  code VARCHAR(30) NOT NULL,
  name VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  CONSTRAINT uq_fee_type_code UNIQUE (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: fee_rule
CREATE TABLE fee_rule (
  id INT AUTO_INCREMENT,
  fee_type_id INT NOT NULL,
  program_id INT NULL,
  course_id INT NULL,
  calculation_basis VARCHAR(20) NOT NULL DEFAULT 'FLAT',
  amount DECIMAL(12,2) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  CONSTRAINT ck_fee_rule_single_scope CHECK (program_id IS NULL OR course_id IS NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: assessment
CREATE TABLE assessment (
  id INT AUTO_INCREMENT,
  enrollment_id INT NOT NULL,
  assessed_at DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
  total_amount DECIMAL(12,2) NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: assessment_line
CREATE TABLE assessment_line (
  id INT AUTO_INCREMENT,
  assessment_id INT NOT NULL,
  fee_type_id INT NOT NULL,
  description VARCHAR(255) NOT NULL,
  quantity DECIMAL(8,2) NOT NULL,
  unit_amount DECIMAL(12,2) NOT NULL,
  line_total DECIMAL(14,2) NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: payment
CREATE TABLE payment (
  id INT AUTO_INCREMENT,
  student_id INT NOT NULL,
  received_by_id INT NOT NULL,
  receipt_number VARCHAR(40) NOT NULL,
  payment_date DATE NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  method VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  PRIMARY KEY (id),
  CONSTRAINT uq_payment_receipt_number UNIQUE (receipt_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: payment_allocation
CREATE TABLE payment_allocation (
  id INT AUTO_INCREMENT,
  payment_id INT NOT NULL,
  assessment_id INT NOT NULL,
  allocated_amount DECIMAL(12,2) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_payment_allocation_pair UNIQUE (payment,assessment)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: auth_group_permissions (M2M through)
CREATE TABLE auth_group_permissions (
  group_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (group_id,permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: app_user_groups (M2M through)
CREATE TABLE app_user_groups (
  user_id INT NOT NULL,
  group_id INT NOT NULL,
  PRIMARY KEY (user_id,group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Table: app_user_user_permissions (M2M through)
CREATE TABLE app_user_user_permissions (
  user_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (user_id,permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Foreign Keys
ALTER TABLE auth_permission ADD CONSTRAINT k_auth_permission_content_type_id FOREIGN KEY (content_type_id) REFERENCES django_content_type(id) ON DELETE RESTRICT;
ALTER TABLE django_admin_log ADD CONSTRAINT k_django_admin_log_user_id FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;
ALTER TABLE django_admin_log ADD CONSTRAINT k_django_admin_log_content_type_id FOREIGN KEY (content_type_id) REFERENCES django_content_type(id) ON DELETE SET NULL;
ALTER TABLE program ADD CONSTRAINT k_program_college_id FOREIGN KEY (college_id) REFERENCES college(id) ON DELETE RESTRICT;
ALTER TABLE curriculum ADD CONSTRAINT k_curriculum_program_id FOREIGN KEY (program_id) REFERENCES program(id) ON DELETE RESTRICT;
ALTER TABLE curriculum_course ADD CONSTRAINT k_curriculum_course_curriculum_id FOREIGN KEY (curriculum_id) REFERENCES curriculum(id) ON DELETE RESTRICT;
ALTER TABLE curriculum_course ADD CONSTRAINT k_curriculum_course_course_id FOREIGN KEY (course_id) REFERENCES course(id) ON DELETE RESTRICT;
ALTER TABLE course_prerequisite ADD CONSTRAINT k_course_prerequisite_course_id FOREIGN KEY (course_id) REFERENCES course(id) ON DELETE RESTRICT;
ALTER TABLE course_prerequisite ADD CONSTRAINT k_course_prerequisite_prerequisite_course_id FOREIGN KEY (prerequisite_course_id) REFERENCES course(id) ON DELETE RESTRICT;
ALTER TABLE student ADD CONSTRAINT k_student_user_id FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;
ALTER TABLE student ADD CONSTRAINT k_student_curriculum_id FOREIGN KEY (curriculum_id) REFERENCES curriculum(id) ON DELETE RESTRICT;
ALTER TABLE instructor ADD CONSTRAINT k_instructor_user_id FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE RESTRICT;
ALTER TABLE section ADD CONSTRAINT k_section_course_id FOREIGN KEY (course_id) REFERENCES course(id) ON DELETE RESTRICT;
ALTER TABLE section ADD CONSTRAINT k_section_term_id FOREIGN KEY (term_id) REFERENCES academic_term(id) ON DELETE RESTRICT;
ALTER TABLE section ADD CONSTRAINT k_section_instructor_id FOREIGN KEY (instructor_id) REFERENCES instructor(id) ON DELETE RESTRICT;
ALTER TABLE section_meeting ADD CONSTRAINT k_section_meeting_section_id FOREIGN KEY (section_id) REFERENCES section(id) ON DELETE RESTRICT;
ALTER TABLE section_meeting ADD CONSTRAINT k_section_meeting_room_id FOREIGN KEY (room_id) REFERENCES room(id) ON DELETE RESTRICT;
ALTER TABLE enrollment ADD CONSTRAINT k_enrollment_student_id FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE RESTRICT;
ALTER TABLE enrollment ADD CONSTRAINT k_enrollment_term_id FOREIGN KEY (term_id) REFERENCES academic_term(id) ON DELETE RESTRICT;
ALTER TABLE enrollment_detail ADD CONSTRAINT k_enrollment_detail_enrollment_id FOREIGN KEY (enrollment_id) REFERENCES enrollment(id) ON DELETE RESTRICT;
ALTER TABLE enrollment_detail ADD CONSTRAINT k_enrollment_detail_section_id FOREIGN KEY (section_id) REFERENCES section(id) ON DELETE RESTRICT;
ALTER TABLE student_course_result ADD CONSTRAINT k_student_course_result_enrollment_detail_id FOREIGN KEY (enrollment_detail_id) REFERENCES enrollment_detail(id) ON DELETE RESTRICT;
ALTER TABLE fee_rule ADD CONSTRAINT k_fee_rule_fee_type_id FOREIGN KEY (fee_type_id) REFERENCES fee_type(id) ON DELETE RESTRICT;
ALTER TABLE fee_rule ADD CONSTRAINT k_fee_rule_program_id FOREIGN KEY (program_id) REFERENCES program(id) ON DELETE RESTRICT;
ALTER TABLE fee_rule ADD CONSTRAINT k_fee_rule_course_id FOREIGN KEY (course_id) REFERENCES course(id) ON DELETE RESTRICT;
ALTER TABLE assessment ADD CONSTRAINT k_assessment_enrollment_id FOREIGN KEY (enrollment_id) REFERENCES enrollment(id) ON DELETE RESTRICT;
ALTER TABLE assessment_line ADD CONSTRAINT k_assessment_line_assessment_id FOREIGN KEY (assessment_id) REFERENCES assessment(id) ON DELETE RESTRICT;
ALTER TABLE assessment_line ADD CONSTRAINT k_assessment_line_fee_type_id FOREIGN KEY (fee_type_id) REFERENCES fee_type(id) ON DELETE RESTRICT;
ALTER TABLE payment ADD CONSTRAINT k_payment_student_id FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE RESTRICT;
ALTER TABLE payment ADD CONSTRAINT k_payment_received_by_id FOREIGN KEY (received_by_id) REFERENCES app_user(id) ON DELETE RESTRICT;
ALTER TABLE payment_allocation ADD CONSTRAINT k_payment_allocation_payment_id FOREIGN KEY (payment_id) REFERENCES payment(id) ON DELETE RESTRICT;
ALTER TABLE payment_allocation ADD CONSTRAINT k_payment_allocation_assessment_id FOREIGN KEY (assessment_id) REFERENCES assessment(id) ON DELETE RESTRICT;
ALTER TABLE auth_group_permissions ADD CONSTRAINT k_auth_group_permissions_group_id FOREIGN KEY (group_id) REFERENCES auth_group(id) ON DELETE CASCADE;
ALTER TABLE auth_group_permissions ADD CONSTRAINT k_auth_group_permissions_permission_id FOREIGN KEY (permission_id) REFERENCES auth_permission(id) ON DELETE CASCADE;
ALTER TABLE app_user_groups ADD CONSTRAINT k_app_user_groups_user_id FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE;
ALTER TABLE app_user_groups ADD CONSTRAINT k_app_user_groups_group_id FOREIGN KEY (group_id) REFERENCES auth_group(id) ON DELETE CASCADE;
ALTER TABLE app_user_user_permissions ADD CONSTRAINT k_app_user_user_permissions_user_id FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE;
ALTER TABLE app_user_user_permissions ADD CONSTRAINT k_app_user_user_permissions_permission_id FOREIGN KEY (permission_id) REFERENCES auth_permission(id) ON DELETE CASCADE;

-- DETAILED BUSINESS RULES (enforced by Django service/model logic, not DDL):
-- - Fee precedence: course-specific > program-specific > general; ambiguous/tied rules rejected by service
-- - Prerequisites: student must have PASSED result for prerequisite course (not just enrollment)
-- - Enrollment: no duplicate course across sections in same enrollment; capacity/term-open/overlap checks in services
-- - EnrollmentDetail: course derived via section.course (no stored course_id column)
-- - Assessment: one Assessment per Enrollment (OneToOne), immutability enforced by model logic
-- - Payments: only RECEIVED payments count toward balance; PENDING/CANCELLED do not; cannot cancel with allocations; no deletion of history
-- - PaymentAllocation: links payments to assessments
-- - Scheduling: room/section meeting conflicts checked by services
