# tests/test_stream_balancing.py

import datetime
from django.test import TestCase
from exam_allocator.models import (
    AllocationSession,
    Department,
    Class,
    Student,
    Subject,
    Exam,
    Room,
    ExamRegistration,
    SlotBlueprint,
    RoomBlueprint,
    StreamBlueprintAssignment,
)
from exam_allocator.services.blueprint_service import BlueprintService
from engine.adaptive.stream_balancer import RoomStreamBalancer
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.models.student import Student as EngineStudent
from engine.validators.allocation_validator import AllocationValidator


def make_student(reg_no: str, dept: str, subj_code: str) -> EngineStudent:
    return EngineStudent(
        register_no=reg_no,
        name=f"Student {reg_no}",
        department=dept,
        semester=5,
        section="A",
        subject_code=subj_code,
        subject_name=f"{subj_code} Name",
        exam_date="2026-03-12",
        session="FN",
    )


def make_group(group_id: str, dept: str, subj_code: str, students: list) -> Group:
    return Group(
        group_id=group_id,
        department=dept,
        semester=5,
        section="A",
        subject_code=subj_code,
        subject_name=f"{subj_code} Name",
        exam_date="2026-03-12",
        session="FN",
        students=students,
        allocated_count=len(students),
    )


class StreamBalancingTests(TestCase):

    def test_underfilled_room_stream_balancing_cohorts_intact(self):
        """
        Tests Option A: Cohorts-Intact Stream Balancing on an underfilled room.
        Room has 31 students total:
        - Stream A: 15 students (ME)
        - Stream B: 14 students (ECE: 6, EL: 8)
        - Stream C: 2 students (CSE: 2)

        Balancing should move the 6 ECE students from Stream B to Stream C:
        - Stream A: 15 students (ME)
        - Stream B: 8 students (EL)
        - Stream C: 8 students (CSE: 2, ECE: 6)
        Streams B and C are balanced at 8 and 8 (diff = 0).
        All 4 cohorts remain 100% intact with zero validation errors.
        """
        classroom = Classroom(room_no="Dummy Room 2")
        room = RoomAllocation(classroom)

        # Stream A: ME 15
        st_a = [make_student(f"ME{i:02d}", "ME", "MET301") for i in range(1, 16)]
        # Stream B: ECE 6 + EL 8
        st_b_ece = [make_student(f"ECE{i:02d}", "ECE", "ECT301") for i in range(1, 7)]
        st_b_el = [make_student(f"EL{i:02d}", "EL", "ELT301") for i in range(1, 9)]
        # Stream C: CSE 2
        st_c_cse = [make_student(f"CSE{i:02d}", "CSE", "CST301") for i in range(1, 3)]

        room.get_stream("A").students = list(st_a)
        room.get_stream("B").students = list(st_b_ece + st_b_el)
        room.get_stream("C").students = list(st_c_cse)

        # Build groups
        g_me = make_group("ME_GRP", "ME", "MET301", st_a)
        g_ece = make_group("ECE_GRP", "ECE", "ECT301", st_b_ece)
        g_el = make_group("EL_GRP", "EL", "ELT301", st_b_el)
        g_cse = make_group("CSE_GRP", "CSE", "CST301", st_c_cse)

        context = AllocationContext(
            groups=[g_me, g_ece, g_el, g_cse],
            room_allocations=[room],
            remaining_pool=RemainingPool(),
        )

        # Before balancing: counts are 15, 14, 2
        self.assertEqual(len(room.get_stream("A").students), 15)
        self.assertEqual(len(room.get_stream("B").students), 14)
        self.assertEqual(len(room.get_stream("C").students), 2)

        balancer = RoomStreamBalancer()
        changed = balancer.balance(context)

        self.assertTrue(changed)
        # After balancing: Stream B has 8 (EL), Stream C has 8 (CSE 2 + ECE 6)
        self.assertEqual(len(room.get_stream("A").students), 15)
        self.assertEqual(len(room.get_stream("B").students), 8)
        self.assertEqual(len(room.get_stream("C").students), 8)

        # Check department distribution
        self.assertEqual(room.get_stream("A").departments, {"ME"})
        self.assertEqual(room.get_stream("B").departments, {"EL"})
        self.assertEqual(room.get_stream("C").departments, {"CSE", "ECE"})

        # Check total room departments <= 4
        self.assertLessEqual(len(room.departments), 4)

        # Check validator success
        val = AllocationValidator().validate(context)
        self.assertTrue(val.success)
        self.assertEqual(len(val.errors), 0)

    def test_full_room_stream_balancing_noop(self):
        """
        A full room (15, 15, 15) should not be modified by RoomStreamBalancer.
        """
        classroom = Classroom(room_no="101")
        room = RoomAllocation(classroom)

        st_a = [make_student(f"CE{i}", "CE", "CET301") for i in range(15)]
        st_b = [make_student(f"ME{i}", "ME", "MET301") for i in range(15)]
        st_c = [make_student(f"EE{i}", "EE", "EET301") for i in range(15)]

        room.get_stream("A").students = st_a
        room.get_stream("B").students = st_b
        room.get_stream("C").students = st_c

        context = AllocationContext(
            groups=[],
            room_allocations=[room],
            remaining_pool=RemainingPool(),
        )

        balancer = RoomStreamBalancer()
        changed = balancer.balance(context)
        self.assertFalse(changed)
        self.assertEqual(len(room.get_stream("A").students), 15)
        self.assertEqual(len(room.get_stream("B").students), 15)
        self.assertEqual(len(room.get_stream("C").students), 15)

    def test_adjacent_clash_prevention(self):
        """
        Balancing must reject moves that would cause adjacent streams (A & B, or B & C)
        to share the same department or subject code.
        """
        classroom = Classroom(room_no="Dummy Room 1")
        room = RoomAllocation(classroom)

        # Stream A: ME (15)
        # Stream B: ECE (10)
        # Stream C: ME (5)
        # Moving ME from Stream C to Stream B would put ME into Stream B, which borders Stream A (ME).
        # This must NOT be allowed!
        st_a = [make_student(f"ME_A{i}", "ME", "MET301") for i in range(15)]
        st_b = [make_student(f"ECE{i}", "ECE", "ECT301") for i in range(10)]
        st_c = [make_student(f"ME_C{i}", "ME", "MET301") for i in range(5)]

        room.get_stream("A").students = st_a
        room.get_stream("B").students = st_b
        room.get_stream("C").students = st_c

        context = AllocationContext(
            groups=[],
            room_allocations=[room],
            remaining_pool=RemainingPool(),
        )

        balancer = RoomStreamBalancer()
        balancer.balance(context)

        # Adjacent streams A and B must NOT share department ME
        self.assertTrue(room.get_stream("A").departments.isdisjoint(room.get_stream("B").departments))
        self.assertTrue(room.get_stream("B").departments.isdisjoint(room.get_stream("C").departments))

    def test_blueprint_service_stream_balancing_integration(self):
        """
        End-to-end integration test creating a session with 1 physical room (45 capacity)
        and 31 students (ME 15, EL 8, ECE 6, CSE 2), verifying that BlueprintService produces
        balanced streams (8 and 8 for Streams B and C).
        """
        session = AllocationSession.objects.create(name="Stream Balancing Test Session")
        Room.objects.create(session=session, room_number="101", capacity=45, benches=15)

        dept_me = Department.objects.create(session=session, department_code="ME", department_name="Mechanical")
        dept_el = Department.objects.create(session=session, department_code="EL", department_name="Electrical")
        dept_ece = Department.objects.create(session=session, department_code="ECE", department_name="Electronics")
        dept_cse = Department.objects.create(session=session, department_code="CSE", department_name="Computer Science")

        cls_me = Class.objects.create(department=dept_me, class_name="ME 2K23", semester=5, academic_year="2026")
        cls_el = Class.objects.create(department=dept_el, class_name="EL 2K23", semester=5, academic_year="2026")
        cls_ece = Class.objects.create(department=dept_ece, class_name="ECE 2K23", semester=5, academic_year="2026")
        cls_cse = Class.objects.create(department=dept_cse, class_name="CSE 2K23", semester=5, academic_year="2026")

        exam_date = datetime.date(2026, 3, 12)
        shift = "FN"

        subj_me = Subject.objects.create(session=session, subject_code="MET301", subject_name="ME Subj", semester=5)
        subj_el = Subject.objects.create(session=session, subject_code="ELT301", subject_name="EL Subj", semester=5)
        subj_ece = Subject.objects.create(session=session, subject_code="ECT301", subject_name="ECE Subj", semester=5)
        subj_cse = Subject.objects.create(session=session, subject_code="CST301", subject_name="CSE Subj", semester=5)

        ex_me = Exam.objects.create(subject=subj_me, exam_date=exam_date, session=shift, duration=180)
        ex_el = Exam.objects.create(subject=subj_el, exam_date=exam_date, session=shift, duration=180)
        ex_ece = Exam.objects.create(subject=subj_ece, exam_date=exam_date, session=shift, duration=180)
        ex_cse = Exam.objects.create(subject=subj_cse, exam_date=exam_date, session=shift, duration=180)

        for i in range(1, 16):
            s = Student.objects.create(student_class=cls_me, roll_number=f"ME_{i:02d}", student_name=f"ME {i}")
            ExamRegistration.objects.create(exam=ex_me, student=s)
        for i in range(1, 9):
            s = Student.objects.create(student_class=cls_el, roll_number=f"EL_{i:02d}", student_name=f"EL {i}")
            ExamRegistration.objects.create(exam=ex_el, student=s)
        for i in range(1, 7):
            s = Student.objects.create(student_class=cls_ece, roll_number=f"ECE_{i:02d}", student_name=f"ECE {i}")
            ExamRegistration.objects.create(exam=ex_ece, student=s)
        for i in range(1, 3):
            s = Student.objects.create(student_class=cls_cse, roll_number=f"CSE_{i:02d}", student_name=f"CSE {i}")
            ExamRegistration.objects.create(exam=ex_cse, student=s)

        bp = BlueprintService.allocate_departments_for_slot(
            session=session,
            exam_date=exam_date,
            shift=shift,
            force_reallocate=True,
        )

        rbp = bp.room_blueprints.first()
        self.assertIsNotNone(rbp)
        self.assertEqual(rbp.total_students, 31)

        counts = {
            s: sum(a.student_count for a in rbp.stream_assignments.filter(stream_name=s))
            for s in ["A", "B", "C"]
        }
        # In underfilled room with 31 students, Stream B and C are balanced at 8 and 8
        self.assertEqual(counts["A"], 15)
        self.assertEqual(counts["B"], 8)
        self.assertEqual(counts["C"], 8)

