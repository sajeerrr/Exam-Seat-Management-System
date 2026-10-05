# tests/test_hybrid_engine.py

import unittest
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.student import Student
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.allocators.hyper_heuristic_allocator import HyperHeuristicAllocator


class TestHybridEngine(unittest.TestCase):

    def test_hybrid_allocation_end_to_end(self):
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3, seats_per_bench=3)
        c2 = Classroom(room_no="102", rows=5, benches_per_row=3, seats_per_bench=3)
        room1 = RoomAllocation(c1)
        room2 = RoomAllocation(c2)

        students_a = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN") for i in range(30)]
        students_b = [Student(register_no=f"EC_{i}", name=f"EC_{i}", department="EC", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN") for i in range(30)]
        students_c = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN") for i in range(30)]

        g1 = Group(group_id="G1", department="CS", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN", students=students_a, allocated_count=0)
        g2 = Group(group_id="G2", department="EC", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN", students=students_b, allocated_count=0)
        g3 = Group(group_id="G3", department="ME", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN", students=students_c, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(
            groups=groups,
            room_allocations=[room1, room2],
            remaining_pool=RemainingPool(groups)
        )

        allocator = HyperHeuristicAllocator()
        result_context = allocator.execute(context)

        self.assertIsNotNone(result_context)
        # Verify all students allocated
        for g in result_context.groups:
            self.assertEqual(g.remaining_count, 0)


if __name__ == '__main__':
    unittest.main()
