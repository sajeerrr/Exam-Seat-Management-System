"""
Unit tests for elective PDF parser and common template validation.
"""

import os
from pathlib import Path
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.test import TestCase

from exam_allocator.models import (
    AllocationSession,
    Department,
    Class,
    Student,
    Subject,
    Exam,
    ElectiveGroup,
    ElectiveSubject,
    ElectiveStudentRegistration,
)
from exam_allocator.parsers.elective_parser import (
    parse_elective_file,
    split_subject_header,
    normalize_subject_code,
    detect_subject_banner,
    derive_elective_type,
    ElectiveExcelParseError,
)
from exam_allocator.services.elective_import_service import import_elective_data
from exam_allocator.services.registration_service import _resolve_elective_students


class ElectivePdfParserTests(TestCase):
    def setUp(self):
        self.session = AllocationSession.objects.create(name="Elective PDF Test Session")
        self.elective_dir = Path("elective_data")

    def test_subject_header_and_code_normalization(self):
        """Test normalization handles section suffixes, newlines, and ampersands."""
        # 1. Chemical engineering course with & and newline
        raw_che = "22CHE803.1 - ECONOMICS & MANAGEMENT OF CHEMICAL\nINDUSTRIES"
        orig, norm, name = split_subject_header(raw_che)
        self.assertEqual(norm, "22CHE803.1")
        self.assertEqual(name, "ECONOMICS & MANAGEMENT OF CHEMICAL INDUSTRIES")

        # 2. ME course with section suffix and trailing underscores
        raw_me_b = "22MEE802.1_B - QUALITY MANAGEMENT_B\n_ _"
        orig, norm, name = split_subject_header(raw_me_b)
        self.assertEqual(norm, "22MEE802.1_B")
        self.assertEqual(name, "QUALITY MANAGEMENT_B")

        # 3. Space-separated section suffix
        raw_me_space = "22MEE802.1 B - QUALITY MANAGEMENT B"
        orig, norm, name = split_subject_header(raw_me_space)
        self.assertEqual(norm, "22MEE802.1_B")
        self.assertEqual(name, "QUALITY MANAGEMENT B")

        # 4. Standard architecture course
        raw_ar = "22ARE801.1 - ARCHITECTURAL CONSERVATION"
        orig, norm, name = split_subject_header(raw_ar)
        self.assertEqual(norm, "22ARE801.1")
        self.assertEqual(name, "ARCHITECTURAL CONSERVATION")

    def test_elective_type_derivation(self):
        """Test elective type is properly inferred from course codes."""
        self.assertEqual(derive_elective_type("22ARE801.1"), "Architecture Elective")
        self.assertEqual(derive_elective_type("22CSE802.1"), "Programme Elective III")
        self.assertEqual(derive_elective_type("22CEE803.3"), "Programme Elective IV")
        self.assertEqual(derive_elective_type("22EEE804.1"), "Programme Elective V")
        self.assertEqual(derive_elective_type("22MEE802.1_B"), "Programme Elective III")

    def test_parse_sample_elective_pdfs(self):
        """Test parsing sample PDFs from elective_data directory."""
        if not self.elective_dir.exists():
            self.skipTest("elective_data directory not present")

        sample_file = self.elective_dir / "22ARE801.1_ARCHITECTURAL_CONSERVATION.pdf"
        if not sample_file.exists():
            self.skipTest("Sample PDF not found")

        result = parse_elective_file(str(sample_file))
        self.assertEqual(len(result.subjects), 1)
        subj = result.subjects[0]
        self.assertEqual(subj.subject_code, "22ARE801.1")
        self.assertEqual(subj.subject_name, "ARCHITECTURAL CONSERVATION")
        self.assertEqual(subj.elective_type, "Architecture Elective")
        self.assertEqual(len(subj.students), 6)
        self.assertEqual(result.report.total_registrations, 6)
        self.assertEqual(len(result.report.warnings), 0)

        # Check first student
        first_st = subj.students[0]
        self.assertEqual(first_st.roll_number, "B22ARA07")
        self.assertEqual(first_st.student_name, "ANU GEORGE")
        self.assertEqual(first_st.department, "B.ARCH")

    def test_parse_and_validate_all_elective_pdfs(self):
        """Batch validate all 34 PDFs in elective_data."""
        if not self.elective_dir.exists():
            self.skipTest("elective_data directory not present")

        pdf_files = sorted(self.elective_dir.glob("*.pdf"))
        self.assertEqual(len(pdf_files), 34, f"Expected 34 PDF files in elective_data, found {len(pdf_files)}")

        total_students_across_all_files = 0
        for pdf_path in pdf_files:
            result = parse_elective_file(str(pdf_path))
            self.assertGreaterEqual(len(result.subjects), 1, f"No subjects in {pdf_path.name}")
            subj = result.subjects[0]
            self.assertTrue(bool(subj.subject_code), f"Missing subject code in {pdf_path.name}")
            self.assertTrue(bool(subj.subject_name), f"Missing subject name in {pdf_path.name}")
            self.assertNotIn("\n", subj.subject_name, f"Embedded newline in subject name of {pdf_path.name}")
            self.assertNotIn("_ _", subj.subject_code, f"Artifact underline in code of {pdf_path.name}")
            self.assertGreater(len(subj.students), 0, f"No students in {pdf_path.name}")

            # Verify no count warnings
            self.assertEqual(len(result.report.warnings), 0, f"Warnings in {pdf_path.name}: {result.report.warnings}")
            total_students_across_all_files += len(subj.students)

        self.assertEqual(total_students_across_all_files, 1909)

    def test_import_and_resolve_batch_electives(self):
        """Test importing parsed results into DB and resolving students for exams."""
        if not self.elective_dir.exists():
            self.skipTest("elective_data directory not present")

        # Import 22MEE802.1 and 22MEE802.1_B
        f1 = self.elective_dir / "22MEE802.1_QUALITY_MANAGEMENT.pdf"
        f2 = self.elective_dir / "22MEE802.1_B_QUALITY_MANAGEMENT_B.pdf"
        if not (f1.exists() and f2.exists()):
            self.skipTest("ME quality management files not found")

        r1 = parse_elective_file(str(f1))
        r2 = parse_elective_file(str(f2))

        import_elective_data(self.session, r1)
        import_elective_data(self.session, r2)

        # In DB, verify subjects exist
        s1 = ElectiveSubject.objects.get(group__session=self.session, subject_code="22MEE802.1")
        s2 = ElectiveSubject.objects.get(group__session=self.session, subject_code="22MEE802.1_B")
        self.assertEqual(s1.student_registrations.count(), 75)
        self.assertEqual(s2.student_registrations.count(), 75)

        # Setup an exam for 22MEE802.1
        dept = Department.objects.create(session=self.session, department_code="ME", department_name="Mechanical")
        cls = Class.objects.create(department=dept, class_name="ME 2K22 A", semester=8)
        subj = Subject.objects.create(session=self.session, subject_code="22MEE802.1", subject_name="Quality Management", semester=8)
        exam = Exam.objects.create(subject=subj, exam_date="2026-03-01", session="FN", duration=180)

        # Create students in DB matching some of the rolls
        Student.objects.create(student_class=cls, roll_number="B22MEA01", student_name="Student A1")
        # Link one from s1
        first_s1_roll = s1.student_registrations.first().roll_number
        Student.objects.create(student_class=cls, roll_number=first_s1_roll, student_name="S1 Student")
        # Link one from s2
        first_s2_roll = s2.student_registrations.first().roll_number
        Student.objects.create(student_class=cls, roll_number=first_s2_roll, student_name="S2 Student")

        # Test resolution matches both 22MEE802.1 and 22MEE802.1_B
        resolved_students = _resolve_elective_students(exam)
        resolved_rolls = {st.roll_number for st in resolved_students}
        self.assertIn(first_s1_roll, resolved_rolls)
        self.assertIn(first_s2_roll, resolved_rolls)
