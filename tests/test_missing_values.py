import json
from django.test import TestCase, RequestFactory
from exam_allocator.models import AllocationSession, Department, Class, Student
from exam_allocator.parsers.student_parser import StudentRecord, ClassRecord, StudentExtractionResult
from exam_allocator.services.import_service import import_students
from exam_allocator.views import api_add_class_student, api_edit_student, api_class_students


class MissingValuesWorkflowTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.session = AllocationSession.objects.create(name="Missing Values Session")
        self.department = Department.objects.create(
            session=self.session,
            department_code="ARCH",
            department_name="Architecture",
        )
        self.student_class = Class.objects.create(
            department=self.department,
            class_name="B.Arch 2K22 A",
            semester=8,
            academic_year="2022-2027",
        )

    def test_import_students_leaves_missing_roll_blank_and_allows_multiples(self):
        """
        Verify that students without roll numbers are saved with roll_number=''
        without duplicating uni_reg_no or admission_no, and that multiple students
        with empty roll numbers in the same class do not collide on uniqueness.
        """
        class_rec = ClassRecord(
            class_name="B.Arch 2K22 A",
            semester=8,
            academic_year="2022-2027",
            department_name="Architecture",
            students=[
                StudentRecord(
                    sl_no="1",
                    admission_no="220101",
                    roll_number="B22ARA01",
                    uni_reg_no="TKM22AR001",
                    name="Student Regular",
                    gender="Male",
                    class_name="B.Arch 2K22 A",
                    semester=8,
                    academic_year="2022-2027",
                ),
                StudentRecord(
                    sl_no="39",
                    admission_no="220171",
                    roll_number="",  # Missing roll number
                    uni_reg_no="KTE21AR001",
                    name="Transfer Student One",
                    gender="Female",
                    class_name="B.Arch 2K22 A",
                    semester=8,
                    academic_year="2022-2027",
                ),
                StudentRecord(
                    sl_no="40",
                    admission_no="220172",
                    roll_number="",  # Missing roll number
                    uni_reg_no="KTE21AR002",
                    name="Transfer Student Two",
                    gender="Female",
                    class_name="B.Arch 2K22 A",
                    semester=8,
                    academic_year="2022-2027",
                ),
            ],
        )
        extract_result = StudentExtractionResult(
            source_file="test_barch.xlsx",
            classes=[class_rec],
            students=class_rec.students,
            issues=["Row 39: Missing roll number", "Row 40: Missing roll number"],
        )

        stats = import_students(extract_result, self.session)
        self.assertEqual(stats["students_created"], 3)

        s1 = Student.objects.get(student_name="Student Regular")
        self.assertEqual(s1.roll_number, "B22ARA01")

        s39 = Student.objects.get(student_name="Transfer Student One")
        self.assertEqual(s39.roll_number, "")  # strictly blank
        self.assertEqual(s39.uni_reg_no, "KTE21AR001")

        s40 = Student.objects.get(student_name="Transfer Student Two")
        self.assertEqual(s40.roll_number, "")  # strictly blank
        self.assertEqual(s40.uni_reg_no, "KTE21AR002")

    def test_api_add_and_edit_student_with_empty_roll_number(self):
        """
        Verify that API allows adding/editing a student with blank roll number,
        while maintaining uniqueness for non-empty roll numbers.
        """
        # 1. Add student with blank roll number
        req_add = self.factory.post(
            f"/api/class/{self.student_class.class_id}/add-student/",
            data=json.dumps({
                "roll_number": "",
                "student_name": "New Blank Roll Student",
                "admission_no": "220999",
                "uni_reg_no": "TKM22AR999",
                "gender": "Male",
            }),
            content_type="application/json",
        )
        res_add = api_add_class_student(req_add, self.student_class.class_id)
        self.assertEqual(res_add.status_code, 200)
        data_add = json.loads(res_add.content)
        self.assertTrue(data_add["success"])
        new_id = data_add["student_id"]
        self.assertEqual(data_add["roll_number"], "")

        # 2. Add another student with non-empty roll number
        req_add2 = self.factory.post(
            f"/api/class/{self.student_class.class_id}/add-student/",
            data=json.dumps({
                "roll_number": "B22ARA10",
                "student_name": "Named Student",
                "admission_no": "220110",
                "uni_reg_no": "TKM22AR010",
                "gender": "Female",
            }),
            content_type="application/json",
        )
        res_add2 = api_add_class_student(req_add2, self.student_class.class_id)
        self.assertEqual(res_add2.status_code, 200)

        # 3. Disallow duplicate non-empty roll number
        req_add_dup = self.factory.post(
            f"/api/class/{self.student_class.class_id}/add-student/",
            data=json.dumps({
                "roll_number": "B22ARA10",
                "student_name": "Duplicate Student",
            }),
            content_type="application/json",
        )
        res_add_dup = api_add_class_student(req_add_dup, self.student_class.class_id)
        self.assertEqual(res_add_dup.status_code, 400)

        # 4. Edit first student and keep roll number blank
        req_edit = self.factory.post(
            f"/api/student/{new_id}/edit/",
            data=json.dumps({
                "roll_number": "",
                "student_name": "Updated Blank Roll Student",
                "admission_no": "220999",
                "uni_reg_no": "TKM22AR999",
                "gender": "Male",
            }),
            content_type="application/json",
        )
        res_edit = api_edit_student(req_edit, new_id)
        self.assertEqual(res_edit.status_code, 200)
        st_updated = Student.objects.get(student_id=new_id)
        self.assertEqual(st_updated.student_name, "Updated Blank Roll Student")
        self.assertEqual(st_updated.roll_number, "")

    def test_api_class_students_orders_and_returns_blank_rolls(self):
        """
        Verify that api_class_students lists students with roll numbers first,
        and blank roll students at the end.
        """
        Student.objects.create(
            student_class=self.student_class,
            roll_number="B22ARA02",
            student_name="Student Two",
        )
        Student.objects.create(
            student_class=self.student_class,
            roll_number="",
            student_name="Student Blank Roll",
        )
        Student.objects.create(
            student_class=self.student_class,
            roll_number="B22ARA01",
            student_name="Student One",
        )

        req = self.factory.get(f"/api/class/{self.student_class.class_id}/students/")
        res = api_class_students(req, self.student_class.class_id)
        data = json.loads(res.content)
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["roll_number"], "B22ARA01")
        self.assertEqual(data[1]["roll_number"], "B22ARA02")
        self.assertEqual(data[2]["roll_number"], "")
        self.assertEqual(data[2]["student_name"], "Student Blank Roll")

