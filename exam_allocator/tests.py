from django.test import TestCase, Client
from django.urls import reverse
from exam_allocator.models import (
    AllocationSession,
    Department,
    Class,
    Student,
    UploadedFile,
    ElectiveGroup,
    ElectiveSubject,
    ElectiveStudentRegistration,
)
from exam_allocator.parsers.elective_parser import (
    ElectiveExtractionResult,
    ElectiveGroupRecord,
    ElectiveSubjectRecord,
    ElectiveStudentRecord,
    ElectiveParseReport,
    normalize_subject_code,
    split_subject_header,
    derive_elective_type,
)
from exam_allocator.services.elective_import_service import import_elective_data


class UploadedFileModelTests(TestCase):
    def test_default_status_is_uploaded(self):
        upload = UploadedFile.objects.create(
            file="uploads/test/sample.pdf",
            original_filename="sample.pdf",
            file_kind=UploadedFile.FileKind.STUDENT_LIST,
            source_format=UploadedFile.SourceFormat.PDF,
        )
        self.assertEqual(upload.status, UploadedFile.Status.UPLOADED)
        self.assertIsNone(upload.processed_at)

    def test_str_representation(self):
        upload = UploadedFile.objects.create(
            file="uploads/test/sample.pdf",
            original_filename="sample.pdf",
            file_kind=UploadedFile.FileKind.CLASSROOM_LIST,
            source_format=UploadedFile.SourceFormat.XLSX,
        )
        self.assertEqual(str(upload), "sample.pdf (Uploaded)")


class ElectiveSubjectGroupingTests(TestCase):
    def setUp(self):
        self.session = AllocationSession.objects.create(name="Test Allocation Session")

    def test_elective_models_str_and_constraints(self):
        group = ElectiveGroup.objects.create(
            session=self.session,
            department_code="ELECTIVE",
            elective_label="Programme Elective III",
        )
        self.assertEqual(str(group), "Programme Elective III")

        subject = ElectiveSubject.objects.create(
            group=group,
            subject_code="22ECE803.2",
            subject_name="Real Time Operating Systems",
            elective_type="Programme Elective III",
        )
        self.assertEqual(str(subject), "22ECE803.2 - Real Time Operating Systems")

        reg = ElectiveStudentRegistration.objects.create(
            elective_subject=subject,
            roll_number="B22ECA01",
            student_name="Alice Smith",
            department="EC",
            class_name="ECE 2K22 A",
            source_file="EC_2.xlsx",
        )
        self.assertEqual(str(reg), "B22ECA01 -> 22ECE803.2")

    def test_subject_code_normalization(self):
        """Test normalization preserves distinct subject identities while cleaning spacing."""
        self.assertEqual(normalize_subject_code("22ECE 803.2"), "22ECE803.2")
        self.assertEqual(normalize_subject_code("22-ECE-803.2"), "22ECE803.2")
        self.assertEqual(normalize_subject_code("Sub: 22ECE803.2"), "22ECE803.2")
        self.assertEqual(normalize_subject_code("22ECE803.2"), "22ECE803.2")
        # Ensure different codes remain separate
        self.assertNotEqual(normalize_subject_code("22ECE803.2"), normalize_subject_code("22ECE803.3"))

        orig, norm, name = split_subject_header("22ECE 803.2 - Real Time Operating Systems")
        self.assertEqual(norm, "22ECE803.2")
        self.assertEqual(name, "Real Time Operating Systems")

    def test_multi_department_students_in_single_subject(self):
        """Test students from multiple departments remain in the SAME subject group."""
        st1 = ElectiveStudentRecord(
            roll_number="B22ECA01",
            student_name="Student EC",
            department="EC",
            class_name="ECE 2K22 A",
        )
        st2 = ElectiveStudentRecord(
            roll_number="B22EEA03",
            student_name="Student EEE",
            department="EEE",
            class_name="EEE 2K22 A",
        )
        st3 = ElectiveStudentRecord(
            roll_number="B22MEA14",
            student_name="Student ME",
            department="ME",
            class_name="ME 2K22 A",
        )

        subj_rec = ElectiveSubjectRecord(
            subject_code="22CSE802.1",
            subject_name="Deep Learning",
            elective_type="Programme Elective III",
            students=[st1, st2, st3],
        )
        group_rec = ElectiveGroupRecord(
            elective_label="Programme Elective III",
            subjects=[subj_rec],
        )
        extraction = ElectiveExtractionResult(
            source_file="cross_dept.xlsx",
            groups=[group_rec],
            report=ElectiveParseReport(total_subjects=1, total_registrations=3),
        )

        stats = import_elective_data(self.session, extraction)
        self.assertEqual(stats["subjects_count"], 1)
        self.assertEqual(stats["students_count"], 3)
        self.assertEqual(stats["departments_count"], 3)

        # Verify in DB: single ElectiveSubject has 3 registrations spanning 3 departments
        subject = ElectiveSubject.objects.get(group__session=self.session, subject_code="22CSE802.1")
        regs = list(subject.student_registrations.all())
        self.assertEqual(len(regs), 3)
        depts = set(r.department for r in regs)
        self.assertEqual(depts, {"EC", "EEE", "ME"})

    def test_duplicate_student_handling(self):
        """Test duplicate student entries per subject are updated/skipped rather than duplicated."""
        st1 = ElectiveStudentRecord(
            roll_number="B22ERA61",
            student_name="KRIPA S RAJEEV",
            department="EL",
        )
        subj_rec = ElectiveSubjectRecord(
            subject_code="22CSE803.5",
            subject_name="Data Mining",
            students=[st1],
        )
        group_rec = ElectiveGroupRecord(
            elective_label="Programme Elective IV",
            subjects=[subj_rec],
        )
        extraction = ElectiveExtractionResult(
            source_file="EL_2.xlsx",
            groups=[group_rec],
        )

        import_elective_data(self.session, extraction)
        self.assertEqual(ElectiveStudentRegistration.objects.filter(elective_subject__subject_code="22CSE803.5").count(), 1)

        # Import again with same student
        import_elective_data(self.session, extraction)
        self.assertEqual(ElectiveStudentRegistration.objects.filter(elective_subject__subject_code="22CSE803.5").count(), 1)

    def test_reuploading_file_preserves_session_isolation_and_idempotency(self):
        """Test re-uploading safely replaces records belonging to that source file without inflating counts."""
        st1 = ElectiveStudentRecord(roll_number="B22CEA01", student_name="Student 1", department="CE")
        st2 = ElectiveStudentRecord(roll_number="B22CEA02", student_name="Student 2", department="CE")
        subj = ElectiveSubjectRecord(
            subject_code="22CEE802.6",
            subject_name="Air Quality Management",
            students=[st1, st2],
        )
        grp = ElectiveGroupRecord(elective_label="Programme Elective III", subjects=[subj])
        extraction = ElectiveExtractionResult(source_file="CE_Elective.xlsx", groups=[grp])

        # First import
        stats1 = import_elective_data(self.session, extraction)
        self.assertEqual(stats1["students_count"], 2)
        self.assertEqual(ElectiveStudentRegistration.objects.filter(elective_subject__subject_code="22CEE802.6").count(), 2)

        # Second import of same file
        stats2 = import_elective_data(self.session, extraction)
        self.assertEqual(stats2["students_count"], 2)
        self.assertEqual(ElectiveStudentRegistration.objects.filter(elective_subject__subject_code="22CEE802.6").count(), 2)

    def test_review_page_renders_electives_subject_wise(self):
        """Test review page shows electives with subject-wise hierarchy."""
        st = ElectiveStudentRecord(
            roll_number="B22ECA01",
            student_name="Alice Smith",
            department="EC",
            class_name="ECE 2K22 A",
            source_file="EC.xlsx",
        )
        subj = ElectiveSubjectRecord(
            subject_code="22ECE802.7",
            subject_name="Entrepreneurship",
            elective_type="Programme Elective III",
            students=[st],
        )
        grp = ElectiveGroupRecord(elective_label="Programme Elective III", subjects=[subj])
        extraction = ElectiveExtractionResult(source_file="EC.xlsx", groups=[grp])
        import_elective_data(self.session, extraction)

        client = Client()
        url = reverse("exam_allocator:review_session", args=[self.session.session_id])
        response = client.get(url, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "22ECE802.7")
        self.assertContains(response, "Entrepreneurship")
        self.assertContains(response, "B22ECA01")
        self.assertContains(response, "Alice Smith")
        self.assertContains(response, "ECE 2K22 A")
