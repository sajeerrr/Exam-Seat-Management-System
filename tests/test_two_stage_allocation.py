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

