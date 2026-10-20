import json
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
    Exam,
    ExamRegistration,
    Allocation,
    Room,
    Subject,
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
        self.assertEqual(lakshmi.roll_number, "")  # Kept blank as in PDF, no fallback duplication
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
        self.assertEqual(aiswariya.roll_number, "")  # Kept blank as in PDF, no fallback duplication
        self.assertEqual(aiswariya.uni_reg_no, "KTE21AR004")



from tests.test_special_subject_allocation import SpecialSubjectAllocationEngineTests


class BlueprintSplitAndAllocationResultTests(TestCase):
    def setUp(self):
        from exam_allocator.models import SlotBlueprint, RoomBlueprint, StreamBlueprintAssignment, Room
        self.session = AllocationSession.objects.create(name="Split Test Session")
        self.room1 = Room.objects.create(session=self.session, room_number="101", capacity=45, benches=15)
        self.room2 = Room.objects.create(session=self.session, room_number="102", capacity=45, benches=15)
        self.bp = SlotBlueprint.objects.create(
            session=self.session,
            exam_date="2026-03-12",
            shift="AN",
            status=SlotBlueprint.Status.NEEDS_REVIEW
        )
        self.rbp1 = RoomBlueprint.objects.create(
            slot_blueprint=self.bp,
            room=self.room1,
            capacity=45,
            room_order=1
        )
        self.rbp2 = RoomBlueprint.objects.create(
            slot_blueprint=self.bp,
            room=self.room2,
            capacity=45,
            room_order=2
        )
        self.assign1 = StreamBlueprintAssignment.objects.create(
            room_blueprint=self.rbp1,
            stream_name="A",
            department_code="CSE",
            class_name="CSE 2026",
            subject_code="CS301",
            subject_name="Data Structures",
            student_count=15,
            student_rolls=[f"CS{i:02d}" for i in range(1, 16)],
            order=1
        )

    def test_split_blueprint_assignment_to_another_room(self):
        from exam_allocator.services.blueprint_service import BlueprintService, StreamBlueprintAssignment
        res = BlueprintService.split_blueprint_assignment(
            slot_blueprint=self.bp,
            assignment_id=self.assign1.assignment_id,
            keep_count=8,
            target_room_id=self.room2.room_id,
            target_stream="B"
        )
        self.assertTrue(res["success"])
        self.assign1.refresh_from_db()
        self.assertEqual(self.assign1.student_count, 8)
        self.assertEqual(len(self.assign1.student_rolls), 8)
        self.assertEqual(self.assign1.student_rolls, [f"CS{i:02d}" for i in range(1, 9)])

        # Verify new assignment in Room 102 Stream B
        new_assign = StreamBlueprintAssignment.objects.filter(
            room_blueprint=self.rbp2,
            stream_name="B"
        ).first()
        self.assertIsNotNone(new_assign)
        self.assertEqual(new_assign.student_count, 7)
        self.assertEqual(len(new_assign.student_rolls), 7)
        self.assertEqual(new_assign.student_rolls, [f"CS{i:02d}" for i in range(9, 16)])

    def test_split_blueprint_assignment_to_unallocated(self):
        from exam_allocator.services.blueprint_service import BlueprintService
        res = BlueprintService.split_blueprint_assignment(
            slot_blueprint=self.bp,
            assignment_id=self.assign1.assignment_id,
            keep_count=10,
            target_room_id=None,
            target_stream=None
        )
        self.assertTrue(res["success"])
        self.assign1.refresh_from_db()
        self.assertEqual(self.assign1.student_count, 10)
        self.assertEqual(len(self.assign1.student_rolls), 10)

    def test_api_blueprint_split_endpoint(self):
        import json
        client = Client()
        url = reverse("exam_allocator:api_blueprint_split", args=[self.session.session_id])
        payload = {
            "blueprint_id": self.bp.blueprint_id,
            "assignment_id": self.assign1.assignment_id,
            "keep_count": 8,
            "target_room_id": self.room2.room_id,
            "target_stream": "A"
        }
        response = client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))

    def test_session_allocation_result_view_renders_without_name_error(self):
        client = Client()
        url = reverse("exam_allocator:session_allocation_result", args=[self.session.session_id])
        response = client.get(url + "?date=2026-03-12&shift=AN")
        self.assertEqual(response.status_code, 200)

    def test_upload_file_no_files_redirects_to_import_data(self):
        client = Client()
        url = reverse("exam_allocator:upload_file", args=[self.session.session_id])
        response = client.post(url, {"file_kind": "ALL"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("exam_allocator:import_data", args=[self.session.session_id]), response.url)

    def test_session_allocation_result_department_allocations_view(self):
        from exam_allocator.models import Department, Class, Student, Subject, Exam, ExamRegistration, Allocation
        dept = Department.objects.create(session=self.session, department_code="MCA", department_name="Master of Computer Applications")
        cls = Class.objects.create(department=dept, class_name="MCA 2 Year", semester=4, academic_year="2025-2026")
        st1 = Student.objects.create(student_class=cls, roll_number="B23MCA01", student_name="Alice")
        st2 = Student.objects.create(student_class=cls, roll_number="B23MCA02", student_name="Bob")

        subj = Subject.objects.create(session=self.session, subject_code="MCA201", subject_name="Data Structures", semester=4)
        exam = Exam.objects.create(subject=subj, exam_date="2026-03-12", session="AN", duration=180)

        reg1 = ExamRegistration.objects.create(student=st1, exam=exam)
        reg2 = ExamRegistration.objects.create(student=st2, exam=exam)

        Allocation.objects.create(exam=exam, registration=reg1, room=self.room1, bench_number=1, seat_number=1)
        Allocation.objects.create(exam=exam, registration=reg2, room=self.room1, bench_number=1, seat_number=2)

        client = Client()
        url = reverse("exam_allocator:session_allocation_result", args=[self.session.session_id])
        response = client.get(url + "?date=2026-03-12&shift=AN")
        self.assertEqual(response.status_code, 200)

        self.assertIn("department_allocations", response.context)
        dept_allocs = response.context["department_allocations"]
        self.assertTrue(any(d["department_code"] == "MCA" for d in dept_allocs))

        mca_alloc = next(d for d in dept_allocs if d["department_code"] == "MCA")
        self.assertEqual(mca_alloc["total_students"], 2)
        self.assertEqual(mca_alloc["class_name"], "MCA 2 Year")
        self.assertEqual(len(mca_alloc["rooms_breakdown"]), 1)
        self.assertEqual(mca_alloc["rooms_breakdown"][0]["room_number"], self.room1.room_number)
        self.assertEqual(mca_alloc["rooms_breakdown"][0]["roll_range_display"], "B23MCA01 – B23MCA02")

        html = response.content.decode("utf-8")
        self.assertIn("btn-view-department", html)
        self.assertIn("view-department", html)
        self.assertIn("MCA 2 Year", html)

    def test_api_allocation_move_and_swap(self):
        import json
        dept = Department.objects.create(session=self.session, department_code="CS", department_name="Computer Science")
        cls = Class.objects.create(department=dept, class_name="CS-A", semester=4, academic_year="2025-2026")
        st1 = Student.objects.create(student_class=cls, roll_number="B23CS01", student_name="Alice")
        st2 = Student.objects.create(student_class=cls, roll_number="B23CS02", student_name="Bob")
        subj = Subject.objects.create(session=self.session, subject_code="CS201", subject_name="Algorithms", semester=4)
        exam = Exam.objects.create(
            subject=subj,
            exam_date="2026-03-15",
            session="FN",
            duration=180,
        )
        reg1 = ExamRegistration.objects.create(student=st1, exam=exam)
        reg2 = ExamRegistration.objects.create(student=st2, exam=exam)

        alloc1 = Allocation.objects.create(exam=exam, registration=reg1, room=self.room1, bench_number=1, seat_number=1)
        alloc2 = Allocation.objects.create(exam=exam, registration=reg2, room=self.room1, bench_number=1, seat_number=2)

        client = Client()
        update_url = reverse("exam_allocator:api_allocation_update", args=[self.session.session_id])

        # 1. Move alloc1 to an empty seat (Bench 5, Seat 3)
        move_resp = client.post(
            update_url,
            data=json.dumps({
                "action": "move",
                "allocation_id": alloc1.allocation_id,
                "target_room_id": self.room1.room_id,
                "target_bench_number": 5,
                "target_seat_number": 3,
            }),
            content_type="application/json"
        )
        self.assertEqual(move_resp.status_code, 200)
        data = move_resp.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["is_swap"])

        alloc1.refresh_from_db()
        self.assertEqual(alloc1.bench_number, 5)
        self.assertEqual(alloc1.seat_number, 3)

        # 2. Swap alloc1 (now at B5, S3) and alloc2 (at B1, S2)
        swap_resp = client.post(
            update_url,
            data=json.dumps({
                "action": "swap",
                "source_allocation_id": alloc1.allocation_id,
                "target_allocation_id": alloc2.allocation_id,
            }),
            content_type="application/json"
        )
        self.assertEqual(swap_resp.status_code, 200)
        swap_data = swap_resp.json()
        self.assertTrue(swap_data["success"])
        self.assertTrue(swap_data["is_swap"])

        alloc1.refresh_from_db()
        alloc2.refresh_from_db()
        self.assertEqual(alloc1.bench_number, 1)
        self.assertEqual(alloc1.seat_number, 2)
        self.assertEqual(alloc2.bench_number, 5)
        self.assertEqual(alloc2.seat_number, 3)

    def test_export_allocations_csv(self):
        dept = Department.objects.create(session=self.session, department_code="EC", department_name="Electronics")
        cls = Class.objects.create(department=dept, class_name="EC-A", semester=4, academic_year="2025-2026")
        st = Student.objects.create(student_class=cls, roll_number="B23EC01", student_name="Carol")
        subj = Subject.objects.create(session=self.session, subject_code="EC201", subject_name="Signals", semester=4)
        exam = Exam.objects.create(
            subject=subj,
            exam_date="2026-03-16",
            session="FN",
            duration=180,
        )
        reg = ExamRegistration.objects.create(student=st, exam=exam)
        Allocation.objects.create(exam=exam, registration=reg, room=self.room1, bench_number=2, seat_number=1)

        client = Client()
        csv_url = reverse("exam_allocator:export_allocations_csv", args=[self.session.session_id])
        resp = client.get(csv_url + "?date=2026-03-16&shift=FN")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=", resp["Content-Disposition"])

        content = resp.content.decode("utf-8")
        self.assertIn("Branch,Count,Classname,Status,Start Roll Number,End Rollnumber,Comma Separater ,Subject", content)
        self.assertIn(st.roll_number, content)
        self.assertIn(self.room1.room_number, content)

        # Also test detailed fallback
        resp_detail = client.get(csv_url + "?date=2026-03-16&shift=FN&format=detailed")
        self.assertEqual(resp_detail.status_code, 200)
        content_detail = resp_detail.content.decode("utf-8")
        self.assertIn("Roll Number,Student Name,Department,Class,Subject Code", content_detail)


class RoomEditAndCapacityStepperTests(TestCase):
    def setUp(self):
        from exam_allocator.models import AllocationSession, SlotBlueprint, RoomBlueprint, Room, StreamBlueprintAssignment
        self.session = AllocationSession.objects.create(name="Test Session Spring 2026", status="DRAFT")
        self.room1 = Room.objects.create(session=self.session, room_number="101", capacity=45, benches=15, building="Main")
        self.room2 = Room.objects.create(session=self.session, room_number="102", capacity=45, benches=15, building="Main")
        self.room_small = Room.objects.create(session=self.session, room_number="Small 1", capacity=10, benches=4, building="Main")

        self.bp = SlotBlueprint.objects.create(
            session=self.session,
            exam_date="2026-03-20",
            shift="FN",
            status=SlotBlueprint.Status.DRAFT,
            total_eligible_students=20,
            total_allocated_students=15,
            unallocated_count=5
        )
        self.rbp1 = RoomBlueprint.objects.create(
            slot_blueprint=self.bp,
            room=self.room1,
            capacity=45,
            total_students=15,
            unused_capacity=30,
            room_order=1
        )
        self.assign1 = StreamBlueprintAssignment.objects.create(
            room_blueprint=self.rbp1,
            stream_name="A",
            department_code="CSE",
            class_name="CSE-A",
            subject_code="CS101",
            subject_name="Intro CS",
            student_count=15,
            student_rolls=[f"CS{i:02d}" for i in range(1, 16)],
            order=1
        )

    def test_step_capacity_up_and_down(self):
        from exam_allocator.services.blueprint_service import BlueprintService
        # Step capacity up by 3
        res = BlueprintService.update_room_capacity(self.bp, self.room1.room_id, 48)
        self.assertTrue(res["success"])
        self.rbp1.refresh_from_db()
        self.assertEqual(self.rbp1.capacity, 48)
        self.assertEqual(self.rbp1.unused_capacity, 33)

        # Step capacity down
        res2 = BlueprintService.update_room_capacity(self.bp, self.room1.room_id, 42)
        self.assertTrue(res2["success"])
        self.rbp1.refresh_from_db()
        self.assertEqual(self.rbp1.capacity, 42)
        self.assertEqual(self.rbp1.unused_capacity, 27)

    def test_rename_room_in_blueprint(self):
        from exam_allocator.services.blueprint_service import BlueprintService
        res = BlueprintService.assign_real_room_name(
            slot_blueprint=self.bp,
            room_blueprint_id=self.rbp1.room_blueprint_id,
            new_room_number="Hall 101"
        )
        self.assertTrue(res["success"])
        self.rbp1.refresh_from_db()
        self.assertEqual(self.rbp1.room.room_number, "Hall 101")

    def test_switch_room_to_existing_session_room(self):
        from exam_allocator.services.blueprint_service import BlueprintService
        res = BlueprintService.assign_real_room_name(
            slot_blueprint=self.bp,
            room_blueprint_id=self.rbp1.room_blueprint_id,
            target_room_id=self.room2.room_id
        )
        self.assertTrue(res["success"])
        self.rbp1.refresh_from_db()
        self.assertEqual(self.rbp1.room, self.room2)
        self.assertEqual(self.rbp1.total_students, 15)

    def test_switch_room_rejects_smaller_capacity_than_students(self):
        from exam_allocator.services.blueprint_service import BlueprintService, BlueprintServiceError
        with self.assertRaises(BlueprintServiceError) as ctx:
            BlueprintService.assign_real_room_name(
                slot_blueprint=self.bp,
                room_blueprint_id=self.rbp1.room_blueprint_id,
                target_room_id=self.room_small.room_id
            )
        self.assertIn("smaller than the 15 currently assigned students", str(ctx.exception))

    def test_api_blueprint_room_capacity_stepper_endpoint(self):
        client = Client()
        url = reverse("exam_allocator:api_blueprint_room_capacity", args=[self.session.session_id])
        resp = client.post(
            url,
            data=json.dumps({
                "blueprint_id": self.bp.blueprint_id,
                "room_id": self.room1.room_id,
                "capacity": 48
            }),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.rbp1.refresh_from_db()
        self.assertEqual(self.rbp1.capacity, 48)

    def test_api_blueprint_assign_room_name_endpoint(self):
        client = Client()
        url = reverse("exam_allocator:api_blueprint_assign_room_name", args=[self.session.session_id])
        resp = client.post(
            url,
            data=json.dumps({
                "blueprint_id": self.bp.blueprint_id,
                "room_blueprint_id": self.rbp1.room_blueprint_id,
                "target_room_id": self.room2.room_id
            }),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.rbp1.refresh_from_db()
        self.assertEqual(self.rbp1.room, self.room2)

class ExamSlotOrderingTests(TestCase):
    def setUp(self):
        self.session = AllocationSession.objects.create(name="Slot Order Session")
        self.subj1 = Subject.objects.create(session=self.session, subject_code="SUB101", subject_name="Subject 1", semester=1)
        self.subj2 = Subject.objects.create(session=self.session, subject_code="SUB102", subject_name="Subject 2", semester=1)
        self.subj3 = Subject.objects.create(session=self.session, subject_code="SUB103", subject_name="Subject 3", semester=1)
        self.subj4 = Subject.objects.create(session=self.session, subject_code="SUB104", subject_name="Subject 4", semester=1)

        # Create exams across 2 dates, deliberately inserting AN before FN
        # Date 1: 2026-04-10
        Exam.objects.create(subject=self.subj1, exam_date="2026-04-10", session="AN", duration=180)
        Exam.objects.create(subject=self.subj2, exam_date="2026-04-10", session="FN", duration=180)
        # Date 2: 2026-04-11
        Exam.objects.create(subject=self.subj3, exam_date="2026-04-11", session="AN", duration=180)
        Exam.objects.create(subject=self.subj4, exam_date="2026-04-11", session="FN", duration=180)

    def test_blueprint_review_slot_order_fn_first(self):
        client = Client()
        url = reverse("exam_allocator:blueprint_review", args=[self.session.session_id])
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200)

        slots = resp.context["slots"]
        slot_pairs = [(str(s["date"]), s["shift"]) for s in slots]
        expected_pairs = [
            ("2026-04-10", "FN"),
            ("2026-04-10", "AN"),
            ("2026-04-11", "FN"),
            ("2026-04-11", "AN"),
        ]
        self.assertEqual(slot_pairs, expected_pairs)

        # Also check default selected slot is the first slot (FN)
        selected_slot = resp.context["selected_slot"]
        self.assertEqual(str(selected_slot["date"]), "2026-04-10")
        self.assertEqual(selected_slot["shift"], "FN")

    def test_session_allocation_result_slot_order_fn_first(self):
        client = Client()
        url = reverse("exam_allocator:session_allocation_result", args=[self.session.session_id])
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200)

        slots = resp.context["slots"]
        slot_pairs = [(str(s["date"]), s["shift"]) for s in slots]
        expected_pairs = [
            ("2026-04-10", "FN"),
            ("2026-04-10", "AN"),
            ("2026-04-11", "FN"),
            ("2026-04-11", "AN"),
        ]
        self.assertEqual(slot_pairs, expected_pairs)

        selected_slot = resp.context["selected_slot"]
        self.assertEqual(str(selected_slot["date"]), "2026-04-10")
        self.assertEqual(selected_slot["shift"], "FN")

    def test_exam_list_order_fn_first(self):
        client = Client()
        url = reverse("exam_allocator:session_exam_list", args=[self.session.session_id])
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200)

        exams = list(resp.context["exams"])
        exam_pairs = [(str(e.exam_date), e.session) for e in exams]
        expected_pairs = [
            ("2026-04-10", "FN"),
            ("2026-04-10", "AN"),
            ("2026-04-11", "FN"),
            ("2026-04-11", "AN"),
        ]
        self.assertEqual(exam_pairs, expected_pairs)

