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


class EditAndDeleteApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.session = AllocationSession.objects.create(name="CRUD Test Session")

    def test_elective_subject_and_registration_crud(self):
        # Create group and subject
        grp = ElectiveGroup.objects.create(session=self.session, elective_label="Programme Elective III")
        subj = ElectiveSubject.objects.create(group=grp, subject_code="22ECE803.1", subject_name="Sub A", elective_type="Programme Elective III")
        reg = ElectiveStudentRegistration.objects.create(
            elective_subject=subj, roll_number="B22ECA01", student_name="Student One", department="EC", class_name="EC A"
        )

        # 1. Edit elective subject
        resp = self.client.post(
            reverse("exam_allocator:api_edit_elective_subject", args=[subj.elective_subject_id]),
            data={"subject_code": "22ECE803.1R", "subject_name": "Updated Sub A", "elective_type": "Programme Elective III"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        subj.refresh_from_db()
        self.assertEqual(subj.subject_code, "22ECE803.1R")
        self.assertEqual(subj.subject_name, "Updated Sub A")

        # 2. Add student to elective subject
        resp = self.client.post(
            reverse("exam_allocator:api_add_elective_student", args=[subj.elective_subject_id]),
            data={"roll_number": "B22ECA02", "student_name": "Student Two", "department": "EC", "class_name": "EC A"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(subj.student_registrations.count(), 2)

        # 3. Edit elective student registration
        resp = self.client.post(
            reverse("exam_allocator:api_edit_elective_registration", args=[reg.registration_id]),
            data={"roll_number": "B22ECA01-MOD", "student_name": "Student One Mod", "department": "EC", "class_name": "EC B"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        reg.refresh_from_db()
        self.assertEqual(reg.roll_number, "B22ECA01-MOD")
        self.assertEqual(reg.class_name, "EC B")

        # 4. Delete elective registration
        resp = self.client.post(
            reverse("exam_allocator:api_delete_elective_registration", args=[reg.registration_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ElectiveStudentRegistration.objects.filter(pk=reg.pk).exists())

        # 5. Delete elective subject (cascades)
        resp = self.client.post(
            reverse("exam_allocator:api_delete_elective_subject", args=[subj.elective_subject_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ElectiveSubject.objects.filter(pk=subj.pk).exists())

        # 6. Delete elective group
        grp2 = ElectiveGroup.objects.create(session=self.session, elective_label="Programme Elective IV")
        resp = self.client.post(
            reverse("exam_allocator:api_delete_elective_group", args=[grp2.group_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ElectiveGroup.objects.filter(pk=grp2.pk).exists())

    def test_clear_all_electives(self):
        grp = ElectiveGroup.objects.create(session=self.session, elective_label="Group A")
        subj = ElectiveSubject.objects.create(group=grp, subject_code="22CS801", subject_name="Sub CS", elective_type="Group A")
        ElectiveStudentRegistration.objects.create(elective_subject=subj, roll_number="B22CS01", student_name="CS One")

        resp = self.client.post(
            reverse("exam_allocator:api_clear_electives", args=[self.session.session_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ElectiveGroup.objects.filter(session=self.session).count(), 0)
        self.assertEqual(ElectiveSubject.objects.filter(group__session=self.session).count(), 0)

    def test_timetable_crud_and_clear(self):
        # 1. Add Exam
        resp = self.client.post(
            reverse("exam_allocator:api_add_exam", args=[self.session.session_id]),
            data={"subject_code": "22CST801", "subject_name": "Compilers", "exam_date": "2026-05-10", "session": "FN", "slot": "A", "branch": "CSE"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        exam_id = resp.json()["exam_id"]

        # 2. Edit Exam
        resp = self.client.post(
            reverse("exam_allocator:api_edit_exam", args=[exam_id]),
            data={"exam_date": "2026-05-12", "session": "AN", "slot": "B"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Clear Timetable
        resp = self.client.post(
            reverse("exam_allocator:api_clear_timetable", args=[self.session.session_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)

    def test_student_and_class_crud(self):
        dept = Department.objects.create(session=self.session, department_code="EC", department_name="ECE")
        cls = Class.objects.create(department=dept, class_name="ECE A", semester=8)

        # 1. Add student to class
        resp = self.client.post(
            reverse("exam_allocator:api_add_class_student", args=[cls.class_id]),
            data={"roll_number": "B22ECA99", "student_name": "New Student", "admission_no": "A99", "uni_reg_no": "U99", "gender": "Female"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        stud_id = resp.json()["student_id"]

        # 2. Delete individual student
        resp = self.client.post(
            reverse("exam_allocator:api_delete_student", args=[stud_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Student.objects.filter(pk=stud_id).exists())

        # 3. Delete class
        resp = self.client.post(
            reverse("exam_allocator:api_delete_class", args=[cls.class_id]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Class.objects.filter(pk=cls.class_id).exists())


class StudentPDFParserTests(TestCase):
    def test_parse_student_pdf_with_missing_roll_number(self):
        from exam_allocator.parsers.student_pdf_parser import parse_student_pdf
        from exam_allocator.services.import_service import import_students
        from pathlib import Path

        pdf_path = Path("media/uploads/2026/10/04/B.Arch_2K21B.pdf")
        if not pdf_path.exists():
            self.skipTest("Sample PDF not found in uploads")

        res = parse_student_pdf(str(pdf_path))
        # Total students must be 36 (not 35)
        self.assertEqual(len(res.students), 36)
        last_student = res.students[-1]
        self.assertEqual(last_student.sl_no, "36")
        self.assertEqual(last_student.name, "LAKSHMI RAJESHKUMAR")
        self.assertEqual(last_student.uni_reg_no, "TKM20AR032")
        self.assertEqual(last_student.admission_no, "200097")
        self.assertEqual(last_student.roll_number, "")  # Kept blank as in PDF
        self.assertEqual(last_student.gender, "Female")

        # Test importing into session
        session = AllocationSession.objects.create(name="Test Student Import Session")
        result = import_students(res, session)
        self.assertEqual(result["students_created"], 36)
        lakshmi = Student.objects.get(student_name="LAKSHMI RAJESHKUMAR")
        self.assertEqual(lakshmi.roll_number, "")  # Blank in database as well
        self.assertEqual(lakshmi.uni_reg_no, "TKM20AR032")

    def test_parse_student_pdf_barch_2k22_a(self):
        from exam_allocator.parsers.student_pdf_parser import parse_student_pdf
        from exam_allocator.services.import_service import import_students
        from pathlib import Path

        pdf_path = Path("media/uploads/2026/10/04/B.Arch_2K22_A.pdf")
        if not pdf_path.exists():
            self.skipTest("Sample PDF not found in uploads")

        res = parse_student_pdf(str(pdf_path))
        # Total students must be 40 (not 39)
        self.assertEqual(len(res.students), 40)
        self.assertEqual(res.classes[0].semester, 8)  # VIIIth semester parsed as 8
        last_student = res.students[-1]
        self.assertEqual(last_student.sl_no, "40")
        self.assertEqual(last_student.name, "AISWARIYA S S")
        self.assertEqual(last_student.uni_reg_no, "KTE21AR004")
        self.assertEqual(last_student.admission_no, "220172")
        self.assertEqual(last_student.roll_number, "")  # Kept blank as in PDF
        self.assertEqual(last_student.gender, "Female")

        session = AllocationSession.objects.create(name="Test Student Import Session 2")
        result = import_students(res, session)
        self.assertEqual(result["students_created"], 40)
        aiswariya = Student.objects.get(student_name="AISWARIYA S S")
        self.assertEqual(aiswariya.roll_number, "")  # Blank in database as well
        self.assertEqual(aiswariya.uni_reg_no, "KTE21AR004")

    def test_derive_dept_from_subject_code(self):
        from exam_allocator.parsers.elective_parser import derive_dept_from_subject_code
        self.assertEqual(derive_dept_from_subject_code("22CEE803.3"), "CE")
        self.assertEqual(derive_dept_from_subject_code("22CHE803.1"), "CHE")
        self.assertEqual(derive_dept_from_subject_code("22CSE803.4"), "CSE")
        self.assertEqual(derive_dept_from_subject_code("22ECE803.1"), "ECE")
        self.assertEqual(derive_dept_from_subject_code("22EEE803.2"), "EEE")
        self.assertEqual(derive_dept_from_subject_code("22MEE803.1"), "ME")
        self.assertEqual(derive_dept_from_subject_code("22ARE801.1"), "B.ARCH")
        self.assertEqual(derive_dept_from_subject_code("ECT-4023"), "ECE")

