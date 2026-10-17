# tests/test_dummy_room_workflow.py

import datetime
from django.test import TestCase, Client
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
)
from exam_allocator.services.blueprint_service import (
    BlueprintService,
    BlueprintServiceError,
    BlueprintValidationError,
)


class DummyRoomWorkflowTests(TestCase):

    def setUp(self):
        self.session = AllocationSession.objects.create(name="Fall 2026 Exam Session")
        self.client = Client()

        # Create only ONE physical room with capacity 45
        self.room1 = Room.objects.create(
            session=self.session,
            room_number="101",
            capacity=45,
            benches=15,
            building="Main",
        )

        self.dept_ce = Department.objects.create(session=self.session, department_code="CE", department_name="Civil")
        self.dept_me = Department.objects.create(session=self.session, department_code="ME", department_name="Mechanical")

        self.class_ce = Class.objects.create(department=self.dept_ce, class_name="CE 2K23", semester=5, academic_year="2026")
        self.class_me = Class.objects.create(department=self.dept_me, class_name="ME 2K23", semester=5, academic_year="2026")

        self.exam_date = datetime.date(2026, 11, 10)
        self.shift = "FN"

        self.subj_ce = Subject.objects.create(session=self.session, subject_code="CET301", subject_name="Structural Analysis", semester=5)
        self.subj_me = Subject.objects.create(session=self.session, subject_code="MET301", subject_name="Mechanics of Machinery", semester=5)

        self.exam_ce = Exam.objects.create(subject=self.subj_ce, exam_date=self.exam_date, session=self.shift, duration=180)
        self.exam_me = Exam.objects.create(subject=self.subj_me, exam_date=self.exam_date, session=self.shift, duration=180)

        # Create 45 CE students + 45 ME students = 90 students total (definitely exceeds 45-capacity room 101)
        for i in range(1, 46):
            s_ce = Student.objects.create(
                student_class=self.class_ce,
                roll_number=f"CE{i:02d}",
                student_name=f"CE Student {i}",
            )
            ExamRegistration.objects.create(student=s_ce, exam=self.exam_ce)

            s_me = Student.objects.create(
                student_class=self.class_me,
                roll_number=f"ME{i:02d}",
                student_name=f"ME Student {i}",
            )
            ExamRegistration.objects.create(student=s_me, exam=self.exam_me)

    def test_auto_provision_dummy_rooms_when_capacity_insufficient(self):
        """When total students (90) exceeds available room capacity (45), allocator auto-provisions Dummy Room."""
        bp = BlueprintService.allocate_departments_for_slot(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
        )

        # All 90 students must be allocated (0 unallocated)
        self.assertEqual(bp.total_allocated_students, 90)
        self.assertEqual(bp.unallocated_count, 0)

        # Must have allocated into 2 room blueprints: Room 101 and a Dummy Room
        room_bps = list(bp.room_blueprints.all().select_related("room").order_by("room_order"))
        self.assertEqual(len(room_bps), 2)

        dummy_bps = [rb for rb in room_bps if rb.room.is_dummy_room]
        self.assertEqual(len(dummy_bps), 1)
        self.assertTrue(dummy_bps[0].room.room_number.startswith("Dummy Room"))

        # Validation should report that the dummy room needs a real name
        is_valid, errors, warnings, stats = BlueprintService.validate_blueprint(bp)
        self.assertFalse(is_valid)
        self.assertTrue(any("dummy" in err.lower() or "unassigned placeholder" in err.lower() for err in errors))

    def test_pre_seating_guard_blocks_physical_seats_for_dummy_rooms(self):
        """Physical seating generation must be blocked while dummy rooms remain."""
        bp = BlueprintService.allocate_departments_for_slot(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
        )

        # Attempt to finalize should fail
        with self.assertRaises(BlueprintValidationError):
            BlueprintService.finalize_blueprint(bp)

        # Force status to FINALIZED to test generate_seats guard directly
        bp.status = SlotBlueprint.Status.FINALIZED
        bp.save()

        with self.assertRaises(BlueprintServiceError) as ctx:
            BlueprintService.generate_seats_from_blueprint(bp)
        self.assertIn("dummy", str(ctx.exception).lower())

    def test_assign_real_room_name_and_generate_seats(self):
        """Once dummy room is given a real room name, finalization and physical seat generation succeed."""
        bp = BlueprintService.allocate_departments_for_slot(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
        )

        dummy_rb = bp.room_blueprints.filter(room__room_number__startswith="Dummy Room").first()
        self.assertIsNotNone(dummy_rb)

        # Rename Dummy Room to 'Drawing Hall 1'
        res = BlueprintService.assign_real_room_name(
            slot_blueprint=bp,
            room_blueprint_id=dummy_rb.room_blueprint_id,
            new_room_number="Drawing Hall 1",
        )
        self.assertTrue(res["success"])

        # Room should now have the real name and is_dummy=False
        dummy_rb.refresh_from_db()
        self.assertEqual(dummy_rb.room.room_number, "Drawing Hall 1")
        self.assertFalse(dummy_rb.room.is_dummy)
        self.assertFalse(dummy_rb.room.is_dummy_room)

        # Blueprint should now be valid
        bp.refresh_from_db()
        is_valid, errors, _, _ = BlueprintService.validate_blueprint(bp)
        self.assertTrue(is_valid, f"Validation failed with errors: {errors}")

        # Finalize and generate physical seats
        finalized_bp = BlueprintService.finalize_blueprint(bp)
        self.assertEqual(finalized_bp.status, SlotBlueprint.Status.FINALIZED)

        allocations = BlueprintService.generate_seats_from_blueprint(finalized_bp)
        self.assertEqual(len(allocations), 90)
        self.assertEqual(Allocation.objects.count(), 90)

    def test_assign_existing_unassigned_room_to_dummy(self):
        """A dummy room can be swapped with an existing unassigned classroom."""
        # Create a second real room that wasn't used initially
        room2 = Room.objects.create(
            session=self.session,
            room_number="102",
            capacity=45,
            benches=15,
            building="Main",
        )

        bp = BlueprintService.allocate_departments_for_slot(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
        )

        # If both room1 and room2 were available, they might both be used.
        # Let's create an extra 45 students so 3 rooms are needed: room1, room2, and Dummy Room 1
        for i in range(46, 91):
            s_ce = Student.objects.create(
                student_class=self.class_ce,
                roll_number=f"CE{i:02d}",
                student_name=f"CE Student {i}",
            )
            ExamRegistration.objects.create(student=s_ce, exam=self.exam_ce)

        bp = BlueprintService.allocate_departments_for_slot(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
            force_reallocate=True,
        )

        # Total 135 students across Room 101, Room 102, and Dummy Room 1
        self.assertEqual(bp.total_allocated_students, 135)
        dummy_rb = bp.room_blueprints.filter(room__room_number__startswith="Dummy Room").first()
        self.assertIsNotNone(dummy_rb)

        # Create an unassigned real room "Seminar Hall"
        seminar_hall = Room.objects.create(
            session=self.session,
            room_number="Seminar Hall",
            capacity=45,
            benches=15,
            building="North Block",
        )

        res = BlueprintService.assign_real_room_name(
            slot_blueprint=bp,
            room_blueprint_id=dummy_rb.room_blueprint_id,
            target_room_id=seminar_hall.room_id,
        )
        self.assertTrue(res["success"])

        dummy_rb.refresh_from_db()
        self.assertEqual(dummy_rb.room.room_number, "Seminar Hall")
        self.assertEqual(dummy_rb.room.room_id, seminar_hall.room_id)

    def test_api_assign_room_name(self):
        """Test the assign-room-name HTTP API endpoint."""
        bp = BlueprintService.allocate_departments_for_slot(
            session=self.session,
            exam_date=self.exam_date,
            shift=self.shift,
        )

        dummy_rb = bp.room_blueprints.filter(room__room_number__startswith="Dummy Room").first()
        self.assertIsNotNone(dummy_rb)

        import json
        from django.urls import reverse

        url = reverse("exam_allocator:api_blueprint_assign_room_name", args=[self.session.session_id])
        response = self.client.post(
            url,
            data=json.dumps({
                "blueprint_id": bp.blueprint_id,
                "room_blueprint_id": dummy_rb.room_blueprint_id,
                "new_room_number": "Auditorium Hall A",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

        dummy_rb.refresh_from_db()
        self.assertEqual(dummy_rb.room.room_number, "Auditorium Hall A")
        self.assertFalse(dummy_rb.room.is_dummy_room)
