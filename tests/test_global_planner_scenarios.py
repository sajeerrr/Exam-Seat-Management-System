import unittest
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.student import Student
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.adaptive.global_pattern_planner import GlobalPatternPlanner


class TestGlobalPatternPlannerScenarios(unittest.TestCase):

    def test_bottleneck_reservation_and_abc_targets(self):
        c1 = Classroom(room_no="201", rows=5, benches_per_row=3, seats_per_bench=3)
        c2 = Classroom(room_no="202", rows=5, benches_per_row=3, seats_per_bench=3)
        room201 = RoomAllocation(c1)
        room202 = RoomAllocation(c2)

        # Bottleneck department ARCH with only 10 students (< 15 stream capacity)
        students_arch = [Student(register_no=f"ARCH_{i}", name=f"ARCH_{i}", department="ARCH", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN") for i in range(10)]
        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN") for i in range(30)]
        students_el = [Student(register_no=f"EL_{i}", name=f"EL_{i}", department="EL", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN") for i in range(30)]

        g1 = Group(group_id="G1", department="ARCH", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN", students=students_arch, allocated_count=0)
        g2 = Group(group_id="G2", department="ME", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN", students=students_me, allocated_count=0)
        g3 = Group(group_id="G3", department="EL", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN", students=students_el, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(
            groups=groups,
            room_allocations=[room201, room202],
            remaining_pool=RemainingPool(groups)
        )

        planner = GlobalPatternPlanner()
        plan = planner.plan(context)

        self.assertIn("ARCH", plan.bottleneck_departments)
        self.assertGreaterEqual(plan.target_abc_rooms, 1)
        self.assertIn("ARCH", plan.reservations_by_room[0])


if __name__ == '__main__':
    unittest.main()
