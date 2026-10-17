# tests/test_aba_to_abc_optimizer.py
from django.test import TestCase
from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.models.student import Student
from engine.models.classroom import Classroom
from engine.adaptive.aba_to_abc_optimizer import ABAToABCOptimizer
from engine.validators.allocation_validator import AllocationValidator


class ABAToABCOptimizerTests(TestCase):
    def setUp(self):
        self.optimizer = ABAToABCOptimizer()
        self.validator = AllocationValidator()

    def _create_students(self, dept: str, subject_code: str, count: int, start_id: int = 1):
        students = []
        for i in range(count):
            s = Student(
                register_no=f"REG{dept}{start_id + i:03d}",
                roll_no=f"{dept}{start_id + i:03d}",
                name=f"Student {start_id + i}",
                department=dept,
                semester=8,
                section="A",
                subject_code=subject_code,
                subject_name=f"{dept} Subject",
                exam_date="2026-03-12",
                session="AN",
            )
            students.append(s)
        return students

    def test_converts_two_aba_rooms_into_two_abc_rooms(self):
        """
        Room 1: ME (15) - CHE (15) - ME (15)  [ABA]
        Room 2: CE (15) - EL (15)  - CE (15)  [ABA]
        After swap of Stream C:
        Room 1: ME (15) - CHE (15) - CE (15)  [ABC]
        Room 2: CE (15) - EL (15)  - ME (15)  [ABC]
        """
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3)
        c2 = Classroom(room_no="102", rows=5, benches_per_row=3)
        r1 = RoomAllocation(classroom=c1)
        r2 = RoomAllocation(classroom=c2)

        # Room 1 students
        r1.get_stream("A").students.extend(self._create_students("ME", "ME101", 15, 100))
        r1.get_stream("B").students.extend(self._create_students("CHE", "CH101", 15, 200))
        r1.get_stream("C").students.extend(self._create_students("ME", "ME101", 15, 300))

        # Room 2 students
        r2.get_stream("A").students.extend(self._create_students("CE", "CE101", 15, 400))
        r2.get_stream("B").students.extend(self._create_students("EL", "EL101", 15, 500))
        r2.get_stream("C").students.extend(self._create_students("CE", "CE101", 15, 600))

        context = AllocationContext(
            groups=[],
            room_allocations=[r1, r2],
            remaining_pool=RemainingPool(),
        )

        self.assertTrue(self.optimizer._is_aba_room(r1))
        self.assertTrue(self.optimizer._is_aba_room(r2))
        self.assertFalse(self.optimizer._is_abc_room(r1))
        self.assertFalse(self.optimizer._is_abc_room(r2))

        context = self.optimizer.optimize(context)

        # Both rooms should now be ABC
        self.assertTrue(self.optimizer._is_abc_room(r1))
        self.assertTrue(self.optimizer._is_abc_room(r2))
        self.assertFalse(self.optimizer._is_aba_room(r1))
        self.assertFalse(self.optimizer._is_aba_room(r2))

        # Check departments
        self.assertEqual(r1.get_stream("A").departments, {"ME"})
        self.assertEqual(r1.get_stream("B").departments, {"CHE"})
        self.assertEqual(r1.get_stream("C").departments, {"CE"})

        self.assertEqual(r2.get_stream("A").departments, {"CE"})
        self.assertEqual(r2.get_stream("B").departments, {"EL"})
        self.assertEqual(r2.get_stream("C").departments, {"ME"})

    def test_rejects_swap_if_subject_conflict_introduced(self):
        """
        If swapping Stream C causes adjacent Stream B and C to have identical subjects,
        the swap should be rejected.
        """
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3)
        c2 = Classroom(room_no="102", rows=5, benches_per_row=3)
        r1 = RoomAllocation(classroom=c1)
        r2 = RoomAllocation(classroom=c2)

        # Room 1: ME (ME101) - CHE (CH101) - ME (ME101)
        r1.get_stream("A").students.extend(self._create_students("ME", "ME101", 15, 100))
        r1.get_stream("B").students.extend(self._create_students("CHE", "CH101", 15, 200))
        r1.get_stream("C").students.extend(self._create_students("ME", "ME101", 15, 300))

        # Room 2: CE (CE101) - EL (CH101) - CE (CE101)
        # Note: Stream B in Room 2 has same subject code as Stream B in Room 1 (CH101)
        r2.get_stream("A").students.extend(self._create_students("CE", "CE101", 15, 400))
        r2.get_stream("B").students.extend(self._create_students("EL", "ME101", 15, 500))  # Adjacency with ME
        r2.get_stream("C").students.extend(self._create_students("CE", "CE101", 15, 600))

        context = AllocationContext(
            groups=[],
            room_allocations=[r1, r2],
            remaining_pool=RemainingPool(),
        )

        context = self.optimizer.optimize(context)

        # Room 2 Stream B has ME101, so swapping ME into Room 2 Stream C would conflict!
        # The optimizer should ensure no adjacent conflict is created.
        s_b = r2.get_stream("B")
        s_c = r2.get_stream("C")
        self.assertFalse(s_b.subject_codes.intersection(s_c.subject_codes))
