# tests/test_dynamic_room_occupancy.py

from django.test import TestCase
from engine.config import AllocationLimits
from engine.models.classroom import Classroom as EngineClassroom
from engine.models.room_allocation import RoomAllocation
from engine.models.group import Group
from engine.models.student import Student as EngineStudent
from engine.models.remaining_pool import RemainingPool
from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.validators.allocation_validator import AllocationValidator
from engine.cp.cp_model_builder import CPModelBuilder
from engine.cp.cp_solver import CPSolver


class DynamicRoomOccupancyTests(TestCase):

    def setUp(self):
        self.validator = AllocationValidator()
        self.allocator = ConstrainedBestFitAllocator()

    def _create_students(self, dept: str, count: int, subject_code: str = "SUB101", prefix: str = "S"):
        students = []
        for i in range(1, count + 1):
            s = EngineStudent(
                register_no=f"{prefix}_{dept}_{i}",
                name=f"Student {i}",
                department=dept,
                semester=3,
                section="A",
                subject_code=subject_code,
                subject_name=f"{dept} Subject",
                exam_date="2026-10-20",
                session="FN",
            )
            students.append(s)
        return students

    def _create_room(self, room_no: str):
        classroom = EngineClassroom(
            room_no=room_no,
            rows=5,
            benches_per_row=3,
            seats_per_bench=3,
        )
        return RoomAllocation(classroom=classroom)

    def test_dynamic_minimum_formula(self):
        """Verify dynamic minimum calculation logic across small, medium, and large student batches."""
        # Case 1: Small batch (< 25 students)
        n1 = 18
        min_rooms1 = max(1, (n1 + 44) // 45)
        dyn_min1 = min(AllocationLimits.MIN_ROOM_STUDENTS, n1 // min_rooms1)
        self.assertEqual(dyn_min1, 18)

        # Case 2: Batch requiring 2 rooms with slight underflow (48 students across 2 rooms)
        n2 = 48
        min_rooms2 = max(1, (n2 + 44) // 45)
        dyn_min2 = min(AllocationLimits.MIN_ROOM_STUDENTS, n2 // min_rooms2)
        self.assertEqual(dyn_min2, 24)

        # Case 3: Standard 2 rooms with 60 students (target 30 each)
        n3 = 60
        min_rooms3 = max(1, (n3 + 44) // 45)
        dyn_min3 = min(AllocationLimits.MIN_ROOM_STUDENTS, n3 // min_rooms3)
        self.assertEqual(dyn_min3, 25)

        # Case 4: Large batch with 108 students across 3 rooms
        n4 = 108
        min_rooms4 = max(1, (n4 + 44) // 45)
        dyn_min4 = min(AllocationLimits.MIN_ROOM_STUDENTS, n4 // min_rooms4)
        self.assertEqual(dyn_min4, 25)

    def test_validator_detects_underfilled_room(self):
        """Verify that AllocationValidator flags active rooms with fewer than dynamic_min students."""
        r1 = self._create_room("R101")
        r2 = self._create_room("R102")

        # R101 gets 45 students
        cse_students = self._create_students("CSE", 45, "CS101", prefix="A")
        r1.get_stream("A").students = cse_students[:15]
        r1.get_stream("B").students = cse_students[15:30]
        r1.get_stream("C").students = cse_students[30:45]

        # R102 gets only 10 students (underfilled when total is 55)
        ece_students = self._create_students("ECE", 10, "EC101", prefix="B")
        r2.get_stream("A").students = ece_students

        all_students = cse_students + ece_students
        groups = GroupBuilder().build(all_students)
        # Mark groups as allocated since we manually put them into rooms for validator testing
        for g in groups:
            g.allocated_count = g.strength

        context = AllocationContext(
            groups=groups,
            room_allocations=[r1, r2],
            remaining_pool=RemainingPool(),
        )

        val_result = self.validator.validate(context)
        # Total is 55. Min rooms needed = 2. Dyn min = 55 // 2 = 25 (capped at 25).
        # R102 has only 10 students, so it should be flagged as underfilled
        self.assertEqual(val_result.underfilled_rooms, 1)
        self.assertTrue(any("underfilled" in w.lower() or "dynamic target" in w.lower() for w in val_result.warnings))

    def test_small_batch_dynamic_minimum_no_warning(self):
        """A small batch of 18 students in 1 room should have dynamic_min=18 and not be flagged as underfilled."""
        r1 = self._create_room("R101")
        ce_students = self._create_students("CE", 18, "CE101", prefix="C")
        r1.get_stream("A").students = ce_students[:15]
        r1.get_stream("B").students = ce_students[15:]

        groups = GroupBuilder().build(ce_students)
        for g in groups:
            g.allocated_count = g.strength

        context = AllocationContext(
            groups=groups,
            room_allocations=[r1],
            remaining_pool=RemainingPool(),
        )

        val_result = self.validator.validate(context)
        self.assertEqual(val_result.underfilled_rooms, 0)

    def test_consolidation_balances_60_students_across_two_rooms(self):
        """When 60 students are allocated, optimizer ensures both rooms receive >= 25-30 students."""
        cse_students = self._create_students("CSE", 30, "CS101", prefix="C")
        ece_students = self._create_students("ECE", 30, "EC101", prefix="E")

        groups = GroupBuilder().build(cse_students + ece_students)

        r1 = self._create_room("R101")
        r2 = self._create_room("R102")

        context = AllocationContext(
            groups=groups,
            room_allocations=[r1, r2],
            remaining_pool=RemainingPool(),
        )

        result_context = self.allocator.execute(context)
        val = self.validator.validate(result_context)
        self.assertTrue(val.success)

        active_rooms = [r for r in result_context.room_allocations if r.used_capacity > 0]
        self.assertEqual(len(active_rooms), 2)
        for r in active_rooms:
            # Each active room must have at least 25 students (target 30)
            self.assertGreaterEqual(r.used_capacity, 25)
            self.assertLessEqual(r.used_capacity, 35)

    def test_consolidation_75_students_uses_minimum_rooms_with_target_occupancy(self):
        """75 students across 3 available rooms should occupy exactly 2 rooms (45 + 30) instead of 3 rooms (45 + 15 + 15)."""
        cse_students = self._create_students("CSE", 45, "CS101", prefix="C")
        ece_students = self._create_students("ECE", 30, "EC101", prefix="E")

        groups = GroupBuilder().build(cse_students + ece_students)

        r1 = self._create_room("R101")
        r2 = self._create_room("R102")
        r3 = self._create_room("R103")

        context = AllocationContext(
            groups=groups,
            room_allocations=[r1, r2, r3],
            remaining_pool=RemainingPool(),
        )

        result_context = self.allocator.execute(context)
        val = self.validator.validate(result_context)
        self.assertTrue(val.success)

        active_rooms = [r for r in result_context.room_allocations if r.used_capacity > 0]
        # Must occupy only 2 rooms (45 + 30), not 3 rooms
        self.assertEqual(len(active_rooms), 2)
        for r in active_rooms:
            self.assertGreaterEqual(r.used_capacity, 25)

    def test_cp_model_builder_underfilled_variables(self):
        """Verify CPModelBuilder creates underfilled constraint variables and maximizes objective."""
        cse_students = self._create_students("CSE", 30, "CS101", prefix="C")
        ece_students = self._create_students("ECE", 30, "EC101", prefix="E")
        groups = GroupBuilder().build(cse_students + ece_students)

        r1 = self._create_room("R101")
        r2 = self._create_room("R102")

        builder = CPModelBuilder()
        model, assign = builder.build(groups, [r1, r2])
        self.assertIsNotNone(model)
        self.assertTrue(len(assign) > 0)
        # Model should have objective defined
        self.assertTrue(model.HasObjective())
