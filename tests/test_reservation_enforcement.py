import unittest
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.student import Student
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.services.allocation_service import AllocationService


AccessibilityTest = unittest.TestCase

class TestReservationEnforcement(unittest.TestCase):

    def test_reservation_prevents_premature_depletion(self):
        # 12-03-2026 AN scenario: B.ARCH=112, CS=62, EC=55
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3, seats_per_bench=3)
        c2 = Classroom(room_no="105", rows=5, benches_per_row=3, seats_per_bench=3)
        c3 = Classroom(room_no="200", rows=5, benches_per_row=3, seats_per_bench=3)
        room101 = RoomAllocation(c1)
        room105 = RoomAllocation(c2)
        room200 = RoomAllocation(c3)

        students_arch = [Student(register_no=f"ARCH_{i}", name=f"ARCH_{i}", department="B.ARCH", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN") for i in range(112)]
        students_cs = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN") for i in range(62)]
        students_ec = [Student(register_no=f"EC_{i}", name=f"EC_{i}", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN") for i in range(55)]

        g1 = Group(group_id="G1", department="B.ARCH", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN", students=students_arch, allocated_count=0)
        g2 = Group(group_id="G2", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN", students=students_cs, allocated_count=0)
        g3 = Group(group_id="G3", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN", students=students_ec, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(
            groups=groups,
            room_allocations=[room101, room105, room200],
            remaining_pool=RemainingPool(groups)
        )

        ctx, seat_plan = AllocationService().execute(context)

        # Measure ABC rooms
        from engine.adaptive.local_optimizer import LocalOptimizer
        metrics = LocalOptimizer()._measure_global_pattern_quality(ctx)
        self.assertGreaterEqual(metrics['abc_count'], 2)


if __name__ == '__main__':
    unittest.main()
