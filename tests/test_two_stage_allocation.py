import datetime
from django.test import TestCase, Client
from django.urls import reverse
from exam_allocator.models import (
    AllocationSession,
    Department,
    Class,
    Student,
    Subject,
    Exam,
    Room,
    ExamRegistration,
    Allocation,
    SlotBlueprint,
    RoomBlueprint,
    StreamBlueprintAssignment,
    ElectiveGroup,
    ElectiveSubject,
    ElectiveStudentRegistration,
)
from exam_allocator.services.blueprint_service import (
    BlueprintService,
    BlueprintServiceError,
    BlueprintValidationError,
)
from exam_allocator.services.session_allocation_service import SessionAllocationError


class TwoStageAllocationTests(TestCase):
    """
    Comprehensive regression suite for the separated two-stage workflow:
    Department Blueprint -> Review/Edit -> Automatic Validation -> Finalization -> Physical Seat Generation.
    Covers the 22 required cases specified in Section 13.
    """

    def setUp(self):
        self.session = AllocationSession.objects.create(name="Spring 2026 Examination Session")
        self.client = Client()

        # Create classrooms
        self.room1 = Room.objects.create(
            session=self.session,
            room_number="101",
            capacity=45,
            benches=15,
        )
        self.room2 = Room.objects.create(
            session=self.session,
            room_number="102",
            capacity=45,
            benches=15,
        )

        # Create departments
        self.dept_ce = Department.objects.create(session=self.session, department_code="CE", department_name="Civil")
        self.dept_me = Department.objects.create(session=self.session, department_code="ME", department_name="Mechanical")
        self.dept_cs = Department.objects.create(session=self.session, department_code="CS", department_name="Computer Science")
        self.dept_ec = Department.objects.create(session=self.session, department_code="EC", department_name="Electronics")
        self.dept_ee = Department.objects.create(session=self.session, department_code="EE", department_name="Electrical")

        # Create classes
        self.class_ce = Class.objects.create(department=self.dept_ce, class_name="CE 2K23", semester=6, academic_year="2025-26")
        self.class_me = Class.objects.create(department=self.dept_me, class_name="ME 2K23", semester=6, academic_year="2025-26")
        self.class_cs = Class.objects.create(department=self.dept_cs, class_name="CS 2K23", semester=6, academic_year="2025-26")
        self.class_ec = Class.objects.create(department=self.dept_ec, class_name="EC 2K23", semester=6, academic_year="2025-26")
        self.class_ee = Class.objects.create(department=self.dept_ee, class_name="EE 2K23", semester=6, academic_year="2025-26")

        # Create subjects & exams for Slot 1: 2026-03-12 FN
        self.exam_date = datetime.date(2026, 3, 12)
        self.shift = "FN"

        self.subj_ce = Subject.objects.create(session=self.session, subject_code="CET301", subject_name="Structural Analysis", semester=6)
        self.subj_me = Subject.objects.create(session=self.session, subject_code="MET301", subject_name="Mechanics of Machinery", semester=6)
        self.subj_cs = Subject.objects.create(session=self.session, subject_code="CST301", subject_name="Compiler Design", semester=6)

        self.exam_ce = Exam.objects.create(subject=self.subj_ce, exam_date=self.exam_date, session=self.shift, duration=180)
        self.exam_me = Exam.objects.create(subject=self.subj_me, exam_date=self.exam_date, session=self.shift, duration=180)
        self.exam_cs = Exam.objects.create(subject=self.subj_cs, exam_date=self.exam_date, session=self.shift, duration=180)

        # Create 15 students per department
        self.students_ce = []
        self.students_me = []
        self.students_cs = []

        for i in range(1, 16):
            s_ce = Student.objects.create(
                student_class=self.class_ce,
                roll_number=f"CE{i:02d}",
                student_name=f"CE Student {i}",
            )
            self.students_ce.append(s_ce)
            ExamRegistration.objects.create(student=s_ce, exam=self.exam_ce)

            s_me = Student.objects.create(
                student_class=self.class_me,
                roll_number=f"ME{i:02d}",
                student_name=f"ME Student {i}",
            )
            self.students_me.append(s_me)
            ExamRegistration.objects.create(student=s_me, exam=self.exam_me)

            s_cs = Student.objects.create(
                student_class=self.class_cs,
                roll_number=f"CS{i:02d}",
                student_name=f"CS Student {i}",
            )
            self.students_cs.append(s_cs)
            ExamRegistration.objects.create(student=s_cs, exam=self.exam_cs)

    # ── Test 1: Department allocation runs without generating physical seats ─
    def test_01_stage_a_department_allocation_without_physical_seats(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        self.assertIsNotNone(bp)
        self.assertEqual(bp.status, SlotBlueprint.Status.VALIDATED)
        self.assertEqual(bp.total_allocated_students, 45)
        # CRITICAL: No physical seat allocation records must exist at this stage
        self.assertEqual(Allocation.objects.count(), 0)
        self.assertEqual(bp.room_blueprints.count(), 1)
        rb = bp.room_blueprints.first()
        self.assertEqual(rb.room.room_number, "101")
        self.assertEqual(rb.stream_assignments.count(), 3)

    # ── Test 2: ABC is preferred over ABA when both are feasible ────────────
    def test_02_abc_preferred_over_aba_when_feasible(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb = bp.room_blueprints.first()
        self.assertEqual(rb.pattern, "ABC")
        streams = {sa.stream_name: sa.department_code for sa in rb.stream_assignments.all()}
        self.assertEqual(len(set(streams.values())), 3)

    # ── Test 3: Department consolidation and room balancing continue to work ─
    def test_03_department_consolidation_and_balancing(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb = bp.room_blueprints.first()
        for sa in rb.stream_assignments.all():
            self.assertEqual(sa.student_count, 15)

    # ── Test 4: Blueprint preserves official room ordering ───────────────────
    def test_04_official_room_ordering_preserved(self):
        # Add 30 more students to require 2 rooms
        for i in range(16, 31):
            s_ce = Student.objects.create(student_class=self.class_ce, roll_number=f"CE{i:02d}", student_name=f"CE {i}")
            ExamRegistration.objects.create(student=s_ce, exam=self.exam_ce)
            s_me = Student.objects.create(student_class=self.class_me, roll_number=f"ME{i:02d}", student_name=f"ME {i}")
            ExamRegistration.objects.create(student=s_me, exam=self.exam_me)

        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rbs = list(bp.room_blueprints.order_by("room_order"))
        self.assertEqual(len(rbs), 2)
        self.assertEqual(rbs[0].room.room_number, "101")
        self.assertEqual(rbs[1].room.room_number, "102")
        self.assertLess(rbs[0].room_order, rbs[1].room_order)

    # ── Test 5: Manual room/stream edits are persisted correctly ────────────
    def test_05_manual_stream_edits_persisted(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb1 = bp.room_blueprints.first()
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()
        
        # Move sa_a to Room 102 Stream A
        res = BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=sa_a.assignment_id,
            target_room_id=self.room2.room_id,
            target_stream="A",
            reject_invalid=False,
        )
        self.assertTrue(res["success"])
        sa_a.refresh_from_db()
        self.assertEqual(sa_a.room_blueprint.room.room_number, "102")
        self.assertEqual(sa_a.stream_name, "A")

    # ── Test 6: Every proposed edit triggers backend validity checks ─────────
    def test_06_every_proposed_edit_triggers_backend_validation(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb1 = bp.room_blueprints.first()
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()

        res = BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=sa_a.assignment_id,
            target_room_id=self.room1.room_id,
            target_stream="B",  # Stream B already has 15 students!
            reject_invalid=True,
        )
        # Should be rejected because Stream B would exceed capacity (15 + 15 = 30 > 15)
        self.assertTrue(res.get("rejected", False))
        self.assertIn("exceeds bench capacity", " ".join(res.get("errors", [])))

    # ── Test 7: Invalid edits cannot replace last valid blueprint ────────────
    def test_07_invalid_edits_rejected_and_state_preserved(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb1 = bp.room_blueprints.first()
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()
        old_stream = sa_a.stream_name

        res = BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=sa_a.assignment_id,
            target_room_id=self.room1.room_id,
            target_stream="B",
            reject_invalid=True,
        )
        self.assertFalse(res["success"])
        sa_a.refresh_from_db()
        # Original stream assignment remains unchanged
        self.assertEqual(sa_a.stream_name, old_stream)

    # ── Test 8: Student counts recalculated correctly after edits ────────────
    def test_08_student_counts_recalculated_after_edits(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb1 = bp.room_blueprints.first()
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()

        # Move to empty Room 102
        BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=sa_a.assignment_id,
            target_room_id=self.room2.room_id,
            target_stream="A",
            reject_invalid=False,
        )
        rb1.refresh_from_db()
        rb2 = bp.room_blueprints.get(room=self.room2)
        self.assertEqual(rb1.total_students, 30)
        self.assertEqual(rb2.total_students, 15)
        self.assertEqual(rb1.unused_capacity, 15)
        self.assertEqual(rb2.unused_capacity, 30)

    # ── Test 9: Duplicate or missing students block finalization ─────────────
    def test_09_duplicate_or_missing_students_block_finalization(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb1 = bp.room_blueprints.first()
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()
        
        # Simulate missing students by omitting one roll
        sa_a.student_rolls = sa_a.student_rolls[:-1]
        sa_a.student_count = len(sa_a.student_rolls)
        sa_a.save()

        with self.assertRaises(BlueprintValidationError):
            BlueprintService.finalize_blueprint(bp)

    # ── Test 10: Capacity and department-limit violations block finalization ─
    def test_10_capacity_and_department_limit_block_finalization(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        rb1 = bp.room_blueprints.first()
        
        # Inject 5 departments into Room 1 (limit is 4)
        StreamBlueprintAssignment.objects.create(
            room_blueprint=rb1, stream_name="A", department_code="EC", student_count=1, student_rolls=["EC01"]
        )
        StreamBlueprintAssignment.objects.create(
            room_blueprint=rb1, stream_name="B", department_code="EE", student_count=1, student_rolls=["EE01"]
        )

        with self.assertRaises(BlueprintValidationError):
            BlueprintService.finalize_blueprint(bp)

    # ── Test 11: Normal-subject separation constraints remain enforced ───────
    def test_11_normal_subject_separation_enforced(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        is_valid, errors, warnings, stats = BlueprintService.validate_blueprint(bp)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    # ── Tests 12-14: Special-subject spatial adjacency (horizontal, vertical, diagonal) ─
    def test_12_special_subject_horizontal_adjacency_detected(self):
        """Same elective subject code on adjacent streams (horizontal) detected."""
        group = ElectiveGroup.objects.create(session=self.session, elective_label="PE III")
        es1 = ElectiveSubject.objects.create(group=group, subject_code="23CET611", subject_name="Adv Structures", elective_type="ELECTIVE")

        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.first()
        
        # Put same subject code in Stream A and Stream B
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()
        sa_b = rb1.stream_assignments.filter(stream_name="B").first()
        sa_a.subject_code = "23CET611"
        sa_a.subject_category = "ELECTIVE"
        sa_a.save()
        sa_b.subject_code = "23CET611"
        sa_b.subject_category = "ELECTIVE"
        sa_b.save()

        is_valid, errors, warnings, stats = BlueprintService.validate_blueprint(bp)
        self.assertFalse(is_valid)
        self.assertTrue(any("adjacent Streams A and B" in e for e in errors))

    def test_13_special_subject_vertical_adjacency_detected(self):
        """Physical validator catches vertical adjacency during seat generation."""
        from engine.models.seat_plan import SeatPlan
        from engine.models.seat import Seat
        from engine.models.student import Student as EngineStudent
        from engine.models.classroom import Classroom as EngineClassroom

        classroom = EngineClassroom("101", rows=5, benches_per_row=3, seats_per_bench=3)
        seat_plan = SeatPlan()

        s1 = EngineStudent(
            register_no="EL01", name="E1", department="CE", semester=6, section="A",
            subject_code="23CET611", subject_name="Adv Struct", exam_date="12-03-2026", session="FN",
            roll_no="EL01", subject_category="ELECTIVE"
        )
        s2_vertical = EngineStudent(
            register_no="EL02", name="E2", department="ME", semester=6, section="A",
            subject_code="23CET611", subject_name="Adv Struct", exam_date="12-03-2026", session="FN",
            roll_no="EL02", subject_category="ELECTIVE"
        )

        subj_el = Subject.objects.create(session=self.session, subject_code="23CET611", subject_name="Adv Struct", semester=6)
        exam_el = Exam.objects.create(subject=subj_el, exam_date=self.exam_date, session=self.shift, duration=180)
        st_el1 = Student.objects.create(student_class=self.class_ce, roll_number="EL01", student_name="E1")
        st_el2 = Student.objects.create(student_class=self.class_me, roll_number="EL02", student_name="E2")
        ExamRegistration.objects.create(student=st_el1, exam=exam_el)
        ExamRegistration.objects.create(student=st_el2, exam=exam_el)

        # Bench 1 Seat 1 and Bench 2 Seat 1 (Vertical neighbor)
        seat_plan.add_seat(Seat(classroom=classroom, bench_no=1, stream="A", student=s1))
        seat_plan.add_seat(Seat(classroom=classroom, bench_no=2, stream="A", student=s2_vertical))

        with self.assertRaises(SessionAllocationError) as ctx:
            from exam_allocator.services.session_allocation_service import save_session_seat_plan
            save_session_seat_plan(self.session, seat_plan, [exam_el], expected_students=2)
        self.assertIn("Spatial adjacency conflict", str(ctx.exception))

    def test_14_special_subject_diagonal_adjacency_detected(self):
        """Physical validator catches diagonal adjacency during seat generation."""
        from engine.models.seat_plan import SeatPlan
        from engine.models.seat import Seat
        from engine.models.student import Student as EngineStudent
        from engine.models.classroom import Classroom as EngineClassroom

        classroom = EngineClassroom("101", rows=5, benches_per_row=3, seats_per_bench=3)
        seat_plan = SeatPlan()

        s1 = EngineStudent(
            register_no="EL03", name="E3", department="CE", semester=6, section="A",
            subject_code="23CET612", subject_name="Adv Struct 2", exam_date="12-03-2026", session="FN",
            roll_no="EL03", subject_category="ELECTIVE"
        )
        s2_diagonal = EngineStudent(
            register_no="EL04", name="E4", department="ME", semester=6, section="A",
            subject_code="23CET612", subject_name="Adv Struct 2", exam_date="12-03-2026", session="FN",
            roll_no="EL04", subject_category="ELECTIVE"
        )

        subj_el2 = Subject.objects.create(session=self.session, subject_code="23CET612", subject_name="Adv Struct 2", semester=6)
        exam_el2 = Exam.objects.create(subject=subj_el2, exam_date=self.exam_date, session=self.shift, duration=180)
        st_el3 = Student.objects.create(student_class=self.class_ce, roll_number="EL03", student_name="E3")
        st_el4 = Student.objects.create(student_class=self.class_me, roll_number="EL04", student_name="E4")
        ExamRegistration.objects.create(student=st_el3, exam=exam_el2)
        ExamRegistration.objects.create(student=st_el4, exam=exam_el2)

        # Bench 1 Seat 1 (stream A) and Bench 2 Seat 2 (stream B) (Diagonal neighbor)
        seat_plan.add_seat(Seat(classroom=classroom, bench_no=1, stream="A", student=s1))
        seat_plan.add_seat(Seat(classroom=classroom, bench_no=2, stream="B", student=s2_diagonal))

        with self.assertRaises(SessionAllocationError) as ctx:
            from exam_allocator.services.session_allocation_service import save_session_seat_plan
            save_session_seat_plan(self.session, seat_plan, [exam_el2], expected_students=2)
        self.assertIn("Spatial adjacency conflict", str(ctx.exception))



    # ── Test 15: Different subject codes handled as distinct conflict groups ─
    def test_15_different_subject_codes_distinct_groups(self):
        group = ElectiveGroup.objects.create(session=self.session, elective_label="PE III")
        es1 = ElectiveSubject.objects.create(group=group, subject_code="23CET611", subject_name="Subj 1", elective_type="ELECTIVE")
        es2 = ElectiveSubject.objects.create(group=group, subject_code="23MET611", subject_name="Subj 2", elective_type="ELECTIVE")

        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.first()
        sa_a = rb1.stream_assignments.filter(stream_name="A").first()
        sa_b = rb1.stream_assignments.filter(stream_name="B").first()
        sa_a.subject_code = "23CET611"
        sa_a.save()
        sa_b.subject_code = "23MET611"
        sa_b.save()

        is_valid, errors, warnings, stats = BlueprintService.validate_blueprint(bp)
        self.assertTrue(is_valid)

    # ── Test 16: Seat generation uses finalized blueprint without reallocating ─
    def test_16_seat_generation_uses_finalized_blueprint_without_reallocating(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        BlueprintService.finalize_blueprint(bp)
        self.assertEqual(bp.status, SlotBlueprint.Status.FINALIZED)

        allocs = BlueprintService.generate_seats_from_blueprint(bp)
        self.assertEqual(len(allocs), 45)
        self.assertEqual(bp.status, SlotBlueprint.Status.SEATS_GENERATED)

        # Confirm seat positions match the blueprint stream assignments
        alloc_a = Allocation.objects.filter(seat_number=1, room__room_number="101")
        self.assertEqual(alloc_a.count(), 15)
        for a in alloc_a:
            self.assertEqual(a.registration.student.student_class.department.department_code, "CE")

    # ── Test 17: Every eligible student seated exactly once ──────────────────
    def test_17_every_eligible_student_seated_once(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        BlueprintService.finalize_blueprint(bp)
        allocs = BlueprintService.generate_seats_from_blueprint(bp)
        seated_reg_ids = [a.registration_id for a in allocs]
        self.assertEqual(len(seated_reg_ids), len(set(seated_reg_ids)))
        self.assertEqual(len(seated_reg_ids), 45)

    # ── Test 18: Failed seat generation rolls back incomplete records ────────
    def test_18_failed_seat_generation_rolls_back(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        BlueprintService.finalize_blueprint(bp)

        # Corrupt an assignment's student rolls with an invalid student ID
        sa = bp.room_blueprints.first().stream_assignments.first()
        sa.student_rolls = ["NON_EXISTENT_ROLL_999"]
        sa.save()

        with self.assertRaises(BlueprintServiceError):
            BlueprintService.generate_seats_from_blueprint(bp)

        # No partial allocation records remain
        self.assertEqual(Allocation.objects.count(), 0)

    # ── Test 19: Changing finalized blueprint invalidates affected seating ───
    def test_19_unfinalizing_blueprint_invalidates_seating(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        BlueprintService.finalize_blueprint(bp)
        BlueprintService.generate_seats_from_blueprint(bp)
        self.assertEqual(Allocation.objects.count(), 45)

        # Unfinalize
        BlueprintService.unfinalize_blueprint(bp)
        self.assertEqual(bp.status, SlotBlueprint.Status.NEEDS_REVIEW)
        # Seating records are immediately cleaned up
        self.assertEqual(Allocation.objects.count(), 0)

    # ── Test 20: Different dates, shifts, and sessions remain isolated ───────
    def test_20_slot_and_session_isolation(self):
        # Create Slot 2: 2026-03-12 AN
        exam_an = Exam.objects.create(subject=self.subj_ce, exam_date=self.exam_date, session="AN", duration=180)
        s_an = Student.objects.create(student_class=self.class_ce, roll_number="CE_AN_01", student_name="AN Student")
        ExamRegistration.objects.create(student=s_an, exam=exam_an)


        bp1 = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, "FN")
        BlueprintService.finalize_blueprint(bp1)
        BlueprintService.generate_seats_from_blueprint(bp1)
        self.assertEqual(Allocation.objects.filter(exam__session="FN").count(), 45)

        # Blueprint for AN
        bp2 = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, "AN")
        self.assertEqual(bp2.shift, "AN")
        self.assertEqual(bp2.total_allocated_students, 1)

        # FN allocations remain unaffected
        self.assertEqual(Allocation.objects.filter(exam__session="FN").count(), 45)

    # ── Test 21: Repeated requests do not produce duplicate allocations ──────
    def test_21_repeated_requests_idempotent(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        BlueprintService.finalize_blueprint(bp)
        BlueprintService.generate_seats_from_blueprint(bp)
        self.assertEqual(Allocation.objects.count(), 45)

        # Re-generating for the same finalized blueprint replaces, doesn't duplicate
        BlueprintService.generate_seats_from_blueprint(bp)
        self.assertEqual(Allocation.objects.count(), 45)

    # ── Test 22: Frontend reflects saved edits and actual seating records ────
    def test_22_frontend_reflects_blueprint_and_seating_records(self):
        bp = BlueprintService.allocate_departments_for_slot(
            self.session, self.exam_date, self.shift
        )
        url = reverse("exam_allocator:blueprint_review", kwargs={"session_id": self.session.session_id})
        response = self.client.get(f"{url}?date=2026-03-12&shift=FN")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Room 101")
        self.assertContains(response, "CET301")
        self.assertContains(response, "MET301")
        self.assertContains(response, "CST301")
        self.assertContains(response, "ABC")

    # ── Test 23: Opening page or selecting slot does not allocate automatically ─
    def test_23_opening_page_or_selecting_slot_does_not_allocate_automatically(self):
        # 1. Open allocation page (session_allocation_result)
        res1 = self.client.get(reverse("exam_allocator:session_allocation_result", kwargs={"session_id": self.session.session_id}))
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(Allocation.objects.count(), 0)
        self.assertEqual(SlotBlueprint.objects.count(), 0)

        # 2. Select slot via GET query
        res2 = self.client.get(
            f"{reverse('exam_allocator:session_allocation_result', kwargs={'session_id': self.session.session_id})}?date=2026-03-12&shift=FN"
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(Allocation.objects.count(), 0)
        self.assertEqual(SlotBlueprint.objects.count(), 0)

        # 3. Open blueprint review page
        res3 = self.client.get(
            f"{reverse('exam_allocator:blueprint_review', kwargs={'session_id': self.session.session_id})}?date=2026-03-12&shift=FN"
        )
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(Allocation.objects.count(), 0)
        self.assertEqual(SlotBlueprint.objects.count(), 0)

    # ── Test 24: Clicking allocate departments processes only selected slot ──
    def test_24_clicking_allocate_departments_processes_only_selected_slot(self):
        # Create second slot: 2026-03-13 AN
        date2 = datetime.date(2026, 3, 13)
        exam2 = Exam.objects.create(subject=self.subj_me, exam_date=date2, session="AN", duration=180)
        s2 = Student.objects.create(student_class=self.class_me, roll_number="ME_SLOT2_01", student_name="Slot 2 Stu")
        ExamRegistration.objects.create(student=s2, exam=exam2)

        # Allocate ONLY Slot 1 via API
        response = self.client.post(
            reverse("exam_allocator:api_blueprint_allocate", kwargs={"session_id": self.session.session_id}),
            data='{"date": "2026-03-12", "shift": "FN"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        # Verify Slot 1 is allocated into blueprint
        self.assertEqual(SlotBlueprint.objects.filter(exam_date=self.exam_date, shift="FN").count(), 1)
        # Verify Slot 2 is completely unallocated
        self.assertEqual(SlotBlueprint.objects.filter(exam_date=date2, shift="AN").count(), 0)
        self.assertEqual(Allocation.objects.count(), 0)

    # ── Test 25: Slot with no eligible students produces clear diagnostic ────
    def test_25_slot_with_no_eligible_students_produces_clear_diagnostic(self):
        date3 = datetime.date(2026, 3, 15)
        subj_empty = Subject.objects.create(session=self.session, subject_code="EMPTY301", subject_name="Empty Subj", semester=4)
        Exam.objects.create(subject=subj_empty, exam_date=date3, session="FN", duration=180)

        url = reverse("exam_allocator:blueprint_review", kwargs={"session_id": self.session.session_id})
        response = self.client.get(f"{url}?date=2026-03-15&shift=FN")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Student Eligibility Diagnostic")
        self.assertContains(response, "No eligible students found")
        self.assertEqual(SlotBlueprint.objects.filter(exam_date=date3, shift="FN").count(), 0)

    # ── Test 26: Reset and reallocate blueprint ──────────────────────────────
    def test_26_reset_and_reallocate_blueprint(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        BlueprintService.finalize_blueprint(bp)
        BlueprintService.generate_seats_from_blueprint(bp)
        self.assertEqual(Allocation.objects.count(), 45)

        # Reset via API
        response = self.client.post(
            reverse("exam_allocator:api_blueprint_reset", kwargs={"session_id": self.session.session_id}),
            data=f'{{"blueprint_id": {bp.blueprint_id}}}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        # Both blueprint and allocations are deleted
        self.assertEqual(SlotBlueprint.objects.filter(exam_date=self.exam_date, shift=self.shift).count(), 0)
        self.assertEqual(Allocation.objects.filter(exam__exam_date=self.exam_date, exam__session=self.shift).count(), 0)

    # ── Test 27: Drag-and-drop move API updates and returns serialized rooms ──
    def test_27_drag_and_drop_move_api_updates_and_returns_serialized_rooms(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign = rb1.stream_assignments.filter(stream_name="C").first()
        self.assertIsNotNone(assign)

        url = reverse("exam_allocator:api_blueprint_move", kwargs={"session_id": self.session.session_id})
        response = self.client.post(
            url,
            data={
                "blueprint_id": bp.blueprint_id,
                "assignment_id": assign.assignment_id,
                "target_room_id": self.room2.room_id,
                "target_stream": "A",
                "reject_invalid": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["rejected"])
        self.assertIn("rooms", data)
        self.assertGreaterEqual(len(data["rooms"]), 1)

        # Check serialized payload fields
        room_payload = next((r for r in data["rooms"] if r["room_id"] == self.room2.room_id), None)
        self.assertIsNotNone(room_payload)
        self.assertEqual(room_payload["room_number"], "102")
        self.assertIn("stream_a", room_payload)
        self.assertEqual(len(room_payload["stream_a"]), 1)
        self.assertEqual(room_payload["stream_a"][0]["assignment_id"], assign.assignment_id)
        self.assertEqual(room_payload["stream_a"][0]["student_count"], 15)

        # Verify database state
        assign.refresh_from_db()
        self.assertEqual(assign.room_blueprint.room, self.room2)
        self.assertEqual(assign.stream_name, "A")

    # ── Test 28: Automatic group consolidation merges identical groups ───────
    def test_28_automatic_group_consolidation_merges_identical_groups(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        rb2, _ = RoomBlueprint.objects.get_or_create(
            slot_blueprint=bp,
            room=self.room2,
            defaults={"capacity": self.room2.capacity, "room_order": 2},
        )

        # Split the existing CE assignment (Stream A) into two chunks:
        # chunk 1 (8 students) stays in Room 1 Stream A,
        # chunk 2 (7 students) is temporarily placed in Room 2 Stream A
        assign1 = rb1.stream_assignments.filter(stream_name="A").first()
        self.assertIsNotNone(assign1)

        rolls_part1 = [f"CE{i:02d}" for i in range(1, 9)]
        rolls_part2 = [f"CE{i:02d}" for i in range(9, 16)]

        assign1.student_rolls = rolls_part1
        assign1.student_count = len(rolls_part1)
        assign1.save()

        assign2 = StreamBlueprintAssignment.objects.create(
            room_blueprint=rb2,
            stream_name="A",
            department_code=assign1.department_code,
            class_name=assign1.class_name,
            subject_code=assign1.subject_code,
            subject_name=assign1.subject_name,
            student_count=len(rolls_part2),
            student_rolls=rolls_part2,
            order=1,
        )

        # Move assign2 from Room 2 Stream A into Room 1 Stream A
        res = BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=assign2.assignment_id,
            target_room_id=self.room1.room_id,
            target_stream="A",
            reject_invalid=False,
        )
        self.assertTrue(res["success"])

        # assign2 should be deleted / consolidated into assign1
        self.assertFalse(StreamBlueprintAssignment.objects.filter(assignment_id=assign2.assignment_id).exists())

        assign1.refresh_from_db()
        self.assertEqual(assign1.student_count, 15)
        self.assertEqual(len(assign1.student_rolls), 15)
        self.assertEqual(assign1.student_rolls, [f"CE{i:02d}" for i in range(1, 16)])

        # Room 1 total students updated to full 45 (15 CE + 15 ME + 15 CS)
        rb1.refresh_from_db()
        self.assertEqual(rb1.total_students, 45)
        self.assertEqual(rb1.unused_capacity, 0)

    # ── Test 29: Move exceeding stream capacity is rejected and rolled back ──
    def test_29_move_exceeding_stream_capacity_is_rejected_and_rolled_back(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()

        # Both Stream A and Stream B have 15 students. Moving Stream B into Stream A would result in 30 > 15!
        assign_b = rb1.stream_assignments.filter(stream_name="B").first()
        self.assertIsNotNone(assign_b)

        res = BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=assign_b.assignment_id,
            target_room_id=self.room1.room_id,
            target_stream="A",
            reject_invalid=True,
        )
        self.assertFalse(res["success"])
        self.assertTrue(res["rejected"])
        self.assertTrue(any("exceeds bench capacity" in err for err in res["errors"]))

        # Database state preserved: assign_b remains in Stream B!
        assign_b.refresh_from_db()
        self.assertEqual(assign_b.stream_name, "B")
        self.assertEqual(assign_b.room_blueprint, rb1)

    # ── Test 30: Adjacent stream subject conflict move is rejected and rolled back
    def test_30_adjacent_subject_conflict_move_is_rejected_and_rolled_back(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()

        # Change assign_c to have the same subject CET301 as Stream A, but located in Room 2
        rb2, _ = RoomBlueprint.objects.get_or_create(
            slot_blueprint=bp,
            room=self.room2,
            defaults={"capacity": self.room2.capacity, "room_order": 2},
        )
        assign_dup = StreamBlueprintAssignment.objects.create(
            room_blueprint=rb2,
            stream_name="C",
            department_code="CE_ALT",
            class_name="CE ALT",
            subject_code="CET301",
            subject_name="Structural Analysis",
            student_count=5,
            student_rolls=[f"CE_DUP_{i}" for i in range(5)],
            order=1,
        )

        # Move assign_dup into Room 1 Stream B (which is adjacent to Stream A with CET301)
        res = BlueprintService.modify_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=assign_dup.assignment_id,
            target_room_id=self.room1.room_id,
            target_stream="B",
            reject_invalid=True,
        )
        self.assertFalse(res["success"])
        self.assertTrue(res["rejected"])
        self.assertTrue(any("adjacent Streams A and B" in err for err in res["errors"]))

        # Rollback verified: assign_dup still in Room 2 Stream C
        assign_dup.refresh_from_db()
        self.assertEqual(assign_dup.room_blueprint, rb2)
        self.assertEqual(assign_dup.stream_name, "C")

    # ── Test 31: Swap API cleanly swaps two assignments ──────────────────────
    def test_31_swap_api_cleanly_swaps_two_assignments(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()
        assign_c = rb1.stream_assignments.filter(stream_name="C").first()
        self.assertIsNotNone(assign_a)
        self.assertIsNotNone(assign_c)

        url = reverse("exam_allocator:api_blueprint_swap", kwargs={"session_id": self.session.session_id})
        response = self.client.post(
            url,
            data={
                "blueprint_id": bp.blueprint_id,
                "assignment_id_1": assign_a.assignment_id,
                "assignment_id_2": assign_c.assignment_id,
                "reject_invalid": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["rejected"])

        # Verify DB swap
        assign_a.refresh_from_db()
        assign_c.refresh_from_db()
        self.assertEqual(assign_a.stream_name, "C")
        self.assertEqual(assign_c.stream_name, "A")

    # ── Test 32: Update room capacity dynamically expands stream limits ─────
    def test_32_update_room_capacity_expands_stream_limit(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        self.assertEqual(rb1.capacity, 45)

        res = BlueprintService.update_room_capacity(
            slot_blueprint=bp,
            room_id=self.room1.room_id,
            new_capacity=48,
        )
        self.assertTrue(res["success"])
        rb1.refresh_from_db()
        self.assertEqual(rb1.capacity, 48)
        self.assertEqual(res["rooms"][0]["capacity"], 48)
        self.assertEqual(res["rooms"][0]["stream_limit"], 16)

    # ── Test 33: Reducing room capacity below allocation marks invalid ──────
    def test_33_reducing_room_capacity_below_allocation_marks_invalid(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        self.assertEqual(rb1.total_students, 45)

        # Reduce capacity to 30 (when 45 students are assigned)
        res = BlueprintService.update_room_capacity(
            slot_blueprint=bp,
            room_id=self.room1.room_id,
            new_capacity=30,
        )
        self.assertTrue(res["success"])  # Operation saved
        self.assertFalse(res["is_valid"])  # Blueprint is invalid!
        self.assertEqual(res["blueprint_status"], SlotBlueprint.Status.NEEDS_REVIEW)
        self.assertTrue(any("exceeds room capacity: 45 > 30" in err for err in res["errors"]))

        # Verify students are NOT truncated
        rb1.refresh_from_db()
        self.assertEqual(rb1.capacity, 30)
        self.assertEqual(rb1.total_students, 45)

        # Attempt to finalize -> MUST be blocked
        with self.assertRaises(BlueprintValidationError):
            BlueprintService.finalize_blueprint(bp)

        # Restore capacity back to 45 -> becomes valid and finalization succeeds
        res_restore = BlueprintService.update_room_capacity(
            slot_blueprint=bp,
            room_id=self.room1.room_id,
            new_capacity=45,
        )
        self.assertTrue(res_restore["is_valid"])
        bp.refresh_from_db()
        finalized_bp = BlueprintService.finalize_blueprint(bp)
        self.assertEqual(finalized_bp.status, SlotBlueprint.Status.FINALIZED)

    # ── Test 34: Add eligible individual student to assignment ──────────────
    def test_34_add_individual_student_success(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()

        # Create an extra eligible student CE16 registered for exam_ce
        s_extra = Student.objects.create(
            student_class=self.class_ce,
            roll_number="CE16",
            student_name="CE Student 16",
        )
        ExamRegistration.objects.create(student=s_extra, exam=self.exam_ce)

        # Expand capacity of room 101 to 48 so Stream A can hold 16
        BlueprintService.update_room_capacity(bp, self.room1.room_id, 48)

        # Add CE16 to Stream A assignment
        res = BlueprintService.add_student_to_assignment(
            slot_blueprint=bp,
            assignment_id=assign_a.assignment_id,
            roll_number="CE16",
            allow_capacity_increase=False,
        )
        self.assertTrue(res["success"])
        assign_a.refresh_from_db()
        self.assertIn("CE16", assign_a.student_rolls)
        self.assertEqual(assign_a.student_count, 16)
        rb1.refresh_from_db()
        self.assertEqual(rb1.total_students, 46)

    # ── Test 35: Reject invalid additions (unregistered, wrong subject, duplicate)
    def test_35_reject_invalid_student_additions(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()

        # 1. Non-existent / unregistered student
        with self.assertRaises(BlueprintServiceError) as ctx1:
            BlueprintService.add_student_to_assignment(
                slot_blueprint=bp,
                assignment_id=assign_a.assignment_id,
                roll_number="FAKE999",
            )
        self.assertIn("not registered or eligible", str(ctx1.exception))

        # 2. Student registered for ME subject (MET301) cannot be added to Stream A (CET301)
        # Create unallocated ME student
        s_me_extra = Student.objects.create(
            student_class=self.class_me,
            roll_number="ME99",
            student_name="ME Student 99",
        )
        ExamRegistration.objects.create(student=s_me_extra, exam=self.exam_me)

        with self.assertRaises(BlueprintServiceError) as ctx2:
            BlueprintService.add_student_to_assignment(
                slot_blueprint=bp,
                assignment_id=assign_a.assignment_id,
                roll_number="ME99",
            )
        self.assertIn("does not match assignment subject", str(ctx2.exception))

        # 3. Student already allocated in this slot (CE01 is already in Stream A)
        with self.assertRaises(BlueprintServiceError) as ctx3:
            BlueprintService.add_student_to_assignment(
                slot_blueprint=bp,
                assignment_id=assign_a.assignment_id,
                roll_number="CE01",
            )
        self.assertIn("already allocated", str(ctx3.exception))

    # ── Test 36: Capacity expansion control when adding student ──────────────
    def test_36_capacity_expansion_control(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()

        # Stream A currently has 15/15 capacity (room capacity 45)
        s_extra = Student.objects.create(
            student_class=self.class_ce,
            roll_number="CE17",
            student_name="CE Student 17",
        )
        ExamRegistration.objects.create(student=s_extra, exam=self.exam_ce)

        # Without allow_capacity_increase -> fails
        with self.assertRaises(BlueprintServiceError) as ctx:
            BlueprintService.add_student_to_assignment(
                slot_blueprint=bp,
                assignment_id=assign_a.assignment_id,
                roll_number="CE17",
                allow_capacity_increase=False,
            )
        self.assertIn("would exceed Stream A capacity", str(ctx.exception))

        # With allow_capacity_increase=True -> succeeds, expanding capacity
        res = BlueprintService.add_student_to_assignment(
            slot_blueprint=bp,
            assignment_id=assign_a.assignment_id,
            roll_number="CE17",
            allow_capacity_increase=True,
        )
        self.assertTrue(res["success"])
        rb1.refresh_from_db()
        self.assertGreaterEqual(rb1.capacity, 48)

    # ── Test 37: Remove individual student from assignment ───────────────────
    def test_37_remove_individual_student(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()
        self.assertIn("CE01", assign_a.student_rolls)
        self.assertEqual(assign_a.student_count, 15)

        res = BlueprintService.remove_student_from_assignment(
            slot_blueprint=bp,
            assignment_id=assign_a.assignment_id,
            roll_number="CE01",
        )
        assign_a.refresh_from_db()
        self.assertNotIn("CE01", assign_a.student_rolls)
        self.assertEqual(assign_a.student_count, 14)

        # Check that CE01 is in unallocated students
        unallocated = BlueprintService.get_unallocated_students(bp)
        unallocated_rolls = [u["roll_number"] for u in unallocated]
        self.assertIn("CE01", unallocated_rolls)

    # ── Test 38: Remove entire blueprint assignment ──────────────────────────
    def test_38_remove_blueprint_assignment(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_c = rb1.stream_assignments.filter(stream_name="C").first()
        self.assertIsNotNone(assign_c)

        res = BlueprintService.remove_blueprint_assignment(
            slot_blueprint=bp,
            assignment_id=assign_c.assignment_id,
        )
        rb1.refresh_from_db()
        self.assertEqual(rb1.stream_assignments.filter(stream_name="C").count(), 0)
        self.assertEqual(rb1.total_students, 30)

    # ── Test 39: Add and remove classroom from blueprint ─────────────────────
    def test_39_add_and_remove_room_blueprint(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        self.assertFalse(bp.room_blueprints.filter(room=self.room2).exists())

        # Add room 2
        res_add = BlueprintService.add_room_to_blueprint(bp, self.room2.room_id)
        self.assertTrue(res_add["success"])
        self.assertTrue(bp.room_blueprints.filter(room=self.room2).exists())

        # Remove room 2
        res_rem = BlueprintService.remove_room_from_blueprint(bp, self.room2.room_id)
        self.assertTrue(res_rem["success"])
        self.assertFalse(bp.room_blueprints.filter(room=self.room2).exists())

    # ── Test 40: Room capacity API endpoint ──────────────────────────────────
    def test_40_room_capacity_api_endpoint(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        url = reverse("exam_allocator:api_blueprint_room_capacity", kwargs={"session_id": self.session.session_id})

        response = self.client.post(
            url,
            data={
                "blueprint_id": bp.blueprint_id,
                "room_id": self.room1.room_id,
                "capacity": 48,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["rooms"][0]["capacity"], 48)

    # ── Test 41: Student add/remove API endpoints ────────────────────────────
    def test_41_student_add_remove_api_endpoints(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()

        # Remove student CE01 via API
        url_remove = reverse("exam_allocator:api_blueprint_student_remove", kwargs={"session_id": self.session.session_id})
        resp_rem = self.client.post(
            url_remove,
            data={
                "blueprint_id": bp.blueprint_id,
                "assignment_id": assign_a.assignment_id,
                "roll_number": "CE01",
            },
            content_type="application/json",
        )
        self.assertEqual(resp_rem.status_code, 200)
        self.assertTrue(resp_rem.json()["success"])

        # Add student CE01 back via API
        url_add = reverse("exam_allocator:api_blueprint_student_add", kwargs={"session_id": self.session.session_id})
        resp_add = self.client.post(
            url_add,
            data={
                "blueprint_id": bp.blueprint_id,
                "assignment_id": assign_a.assignment_id,
                "roll_number": "CE01",
                "allow_capacity_increase": False,
            },
            content_type="application/json",
        )
        self.assertEqual(resp_add.status_code, 200)
        self.assertTrue(resp_add.json()["success"])

    # ── Test 42: Unallocated students API endpoint ───────────────────────────
    def test_42_unallocated_students_api_endpoint(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()

        # Remove CE01
        BlueprintService.remove_student_from_assignment(bp, assign_a.assignment_id, "CE01")

        url = reverse("exam_allocator:api_blueprint_unallocated_students", kwargs={"session_id": self.session.session_id})
        resp = self.client.get(f"{url}?blueprint_id={bp.blueprint_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        rolls = [s["roll_number"] for s in data["students"]]
        self.assertIn("CE01", rolls)

    # ── Test 43: Seat generation with dynamic room capacity ──────────────────
    def test_43_seat_generation_with_dynamic_room_capacity(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()
        assign_a = rb1.stream_assignments.filter(stream_name="A").first()

        # Create 1 extra student and add to Stream A with capacity expansion (48)
        s_extra = Student.objects.create(
            student_class=self.class_ce,
            roll_number="CE16",
            student_name="CE Student 16",
        )
        ExamRegistration.objects.create(student=s_extra, exam=self.exam_ce)
        BlueprintService.update_room_capacity(bp, self.room1.room_id, 48)
        BlueprintService.add_student_to_assignment(bp, assign_a.assignment_id, "CE16")

        # Finalize and generate seats
        BlueprintService.finalize_blueprint(bp)
        allocations = BlueprintService.generate_seats_from_blueprint(bp)
        self.assertEqual(len(allocations), 46)

        # Check physical allocations
        ce_allocs = Allocation.objects.filter(exam=self.exam_ce)
        self.assertEqual(ce_allocs.count(), 16)
        max_bench = max(a.bench_number for a in ce_allocs)
        self.assertEqual(max_bench, 16)

    # ── Test 44: Automatic consolidation of duplicate stream assignments ─────
    def test_44_consolidate_duplicate_assignments_in_stream(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()

        # Simulate fragmentation in Stream B by splitting an assignment into two
        assign_b = rb1.stream_assignments.filter(stream_name="B").first()
        rolls = list(assign_b.student_rolls or [])
        if len(rolls) >= 2:
            slice1_rolls = rolls[:1]
            slice2_rolls = rolls[1:]

            assign_b.student_rolls = slice1_rolls
            assign_b.student_count = len(slice1_rolls)
            assign_b.save()

            StreamBlueprintAssignment.objects.create(
                room_blueprint=rb1,
                stream_name="B",
                department_code=assign_b.department_code,
                class_name=assign_b.class_name,
                subject_code=assign_b.subject_code,
                subject_name=assign_b.subject_name,
                subject_category=assign_b.subject_category,
                student_count=len(slice2_rolls),
                student_rolls=slice2_rolls,
                order=assign_b.order + 1,
            )

            # Before consolidation, Stream B has 2 assignments with the same (dept, class, subject)
            matching_before = rb1.stream_assignments.filter(
                stream_name="B",
                department_code=assign_b.department_code,
                class_name=assign_b.class_name,
                subject_code=assign_b.subject_code,
            )
            self.assertEqual(matching_before.count(), 2)

            # Run consolidate_slot_assignments
            consolidated = BlueprintService.consolidate_slot_assignments(bp)
            self.assertTrue(consolidated)

            # After consolidation, only 1 assignment exists in Stream B with all rolls merged
            matching_after = rb1.stream_assignments.filter(
                stream_name="B",
                department_code=assign_b.department_code,
                class_name=assign_b.class_name,
                subject_code=assign_b.subject_code,
            )
            self.assertEqual(matching_after.count(), 1)
            merged_assign = matching_after.first()
            self.assertEqual(merged_assign.student_count, len(rolls))
            self.assertEqual(merged_assign.student_rolls, rolls)

    # ── Test 45: Blueprint review page renders with consolidated cards ───────
    def test_45_blueprint_review_page_renders_with_consolidated_cards(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        url = reverse("exam_allocator:blueprint_review", kwargs={"session_id": self.session.session_id})
        resp = self.client.get(f"{url}?date={self.exam_date}&shift={self.shift}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Department Blueprint")
        self.assertContains(resp, "Edit Cap")
        self.assertContains(resp, "btn-card-move")

    # ── Test 46: Merge section A and B into one department card ──────────────
    def test_46_merge_section_a_and_b_into_one_department_card(self):
        bp = BlueprintService.allocate_departments_for_slot(self.session, self.exam_date, self.shift)
        rb1 = bp.room_blueprints.filter(room=self.room1).first()

        assign_b = rb1.stream_assignments.filter(stream_name="B").first()
        rolls = list(assign_b.student_rolls or [])

        # Simulate two different sections in the same department and subject:
        # e.g., "ECE 2K22 A" (2 students) and "ECE 2K22 B" (13 students)
        assign_b.class_name = "ECE 2K22 A"
        assign_b.student_rolls = ["ECE01", "ECE02"]
        assign_b.student_count = 2
        assign_b.save()

        sec_b = StreamBlueprintAssignment.objects.create(
            room_blueprint=rb1,
            stream_name="B",
            department_code=assign_b.department_code,
            class_name="ECE 2K22 B",
            subject_code=assign_b.subject_code,
            subject_name=assign_b.subject_name,
            subject_category=assign_b.subject_category,
            student_count=3,
            student_rolls=["ECE03", "ECE04", "ECE05"],
            order=assign_b.order + 1,
        )

        # Before consolidation: 2 separate cards in Stream B
        stream_b_assignments = rb1.stream_assignments.filter(
            stream_name="B",
            department_code=assign_b.department_code,
            subject_code=assign_b.subject_code,
        )
        self.assertEqual(stream_b_assignments.count(), 2)

        # Consolidate
        changed = BlueprintService.consolidate_slot_assignments(bp)
        self.assertTrue(changed)

        # After consolidation: Exactly 1 card in Stream B combining sections A and B
        stream_b_after = rb1.stream_assignments.filter(
            stream_name="B",
            department_code=assign_b.department_code,
            subject_code=assign_b.subject_code,
        )
        self.assertEqual(stream_b_after.count(), 1)
        merged = stream_b_after.first()
        self.assertEqual(merged.student_count, 5)
        self.assertEqual(merged.class_name, "ECE 2K22")

    def test_47_strip_section_suffix_and_semester_resolution(self):
        """Test clean class naming without sections and semester resolution."""
        self.assertEqual(BlueprintService.strip_section_suffix("ECE 2K22 A"), "ECE 2K22")
        self.assertEqual(BlueprintService.strip_section_suffix("ECE 2K22 B"), "ECE 2K22")
        self.assertEqual(BlueprintService.strip_section_suffix("ECE 2K22 A, B"), "ECE 2K22")
        self.assertEqual(BlueprintService.strip_section_suffix("ME 2K22 C"), "ME 2K22")
        self.assertEqual(BlueprintService.strip_section_suffix("B.Arch 2K24A"), "B.Arch 2K24")
        self.assertEqual(BlueprintService.strip_section_suffix("CE 2K22"), "CE 2K22")

        # Semester resolution
        sem_by_code = BlueprintService.get_semester_for_assignment(self.session, "22ECT801", "")
        self.assertEqual(sem_by_code, 8)

    def test_48_allocate_unallocated_group_and_auto_allocate(self):
        """Test allocating deleted/unallocated students back into rooms and streams."""
        bp = SlotBlueprint.objects.create(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
            status=SlotBlueprint.Status.VALIDATED,
        )
        rb = RoomBlueprint.objects.create(
            slot_blueprint=bp,
            room=self.room1,
            room_order=1,
            capacity=45,
        )
        # Create unallocated assignment removal
        StreamBlueprintAssignment.objects.create(
            room_blueprint=rb,
            stream_name="A",
            department_code="CE",
            class_name="CE 2K23",
            subject_code=self.subj_ce.subject_code,
            subject_name=self.subj_ce.subject_name,
            student_count=3,
            student_rolls=["CE01", "CE02", "CE03"],
        )
        unallocated_before = BlueprintService.get_unallocated_students(bp)
        self.assertTrue(len(unallocated_before) > 0)

        # Auto-allocate unallocated students
        res = BlueprintService.auto_allocate_unallocated(bp)
        self.assertTrue(res["success"])
        self.assertGreater(res["allocated_count"], 0)
        unallocated_after = BlueprintService.get_unallocated_students(bp)
        self.assertLess(len(unallocated_after), len(unallocated_before))

    def test_api_clear_rooms_with_blueprints(self):
        """Test that clearing all classrooms deletes room blueprints and rooms without ProtectedError."""
        bp = SlotBlueprint.objects.create(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
            status=SlotBlueprint.Status.VALIDATED,
        )
        RoomBlueprint.objects.create(
            slot_blueprint=bp,
            room=self.room1,
            room_order=1,
            capacity=45,
        )
        RoomBlueprint.objects.create(
            slot_blueprint=bp,
            room=self.room2,
            room_order=2,
            capacity=45,
        )

        response = self.client.post(f"/api/session/{self.session.session_id}/clear-rooms/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        self.assertFalse(Room.objects.filter(session=self.session).exists())
        self.assertFalse(SlotBlueprint.objects.filter(session=self.session).exists())
        self.assertFalse(RoomBlueprint.objects.filter(room__in=[self.room1, self.room2]).exists())

    def test_api_delete_single_room_with_blueprint(self):
        """Test that deleting a single room cleans up its room blueprints without ProtectedError."""
        bp = SlotBlueprint.objects.create(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
            status=SlotBlueprint.Status.VALIDATED,
        )
        rb = RoomBlueprint.objects.create(
            slot_blueprint=bp,
            room=self.room1,
            room_order=1,
            capacity=45,
        )

        response = self.client.post(f"/api/room/{self.room1.room_id}/delete/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        self.assertFalse(Room.objects.filter(room_id=self.room1.room_id).exists())
        self.assertFalse(RoomBlueprint.objects.filter(pk=rb.pk).exists())





