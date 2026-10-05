import unittest
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.student import Student
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.adaptive.global_pattern_planner import GlobalPatternPlanner
from engine.services.allocation_service import AllocationService


class TestGlobalPatternPlanner(unittest.TestCase):

    def test_planner_abc_target_and_bottlenecks(self):
        c1 = Classroom(room_no="204", rows=5, benches_per_row=3, seats_per_bench=3)
        room204 = RoomAllocation(c1)

        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_el = [Student(register_no=f"EL_{i}", name=f"EL_{i}", department="EL", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_cs = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN") for i in range(5)]

        g1 = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN", students=students_me, allocated_count=0)
        g2 = Group(group_id="G2", department="EL", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN", students=students_el, allocated_count=0)
        g3 = Group(group_id="G3", department="CS", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN", students=students_cs, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(
            groups=groups,
            room_allocations=[room204],
            remaining_pool=RemainingPool(groups)
        )

        planner = GlobalPatternPlanner()
        plan = planner.plan(context)

        self.assertIn("CS", plan.bottleneck_departments)
        self.assertGreaterEqual(plan.target_abc_rooms, 0)

    def test_allocation_with_global_planner_integration(self):
        c1 = Classroom(room_no="204", rows=5, benches_per_row=3, seats_per_bench=3)
        room204 = RoomAllocation(c1)

        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_el = [Student(register_no=f"EL_{i}", name=f"EL_{i}", department="EL", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_ce = [Student(register_no=f"CE_{i}", name=f"CE_{i}", department="CE", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN") for i in range(15)]

        g1 = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN", students=students_me, allocated_count=0)
        g2 = Group(group_id="G2", department="EL", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN", students=students_el, allocated_count=0)
        g3 = Group(group_id="G3", department="CE", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN", students=students_ce, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(
            groups=groups,
            room_allocations=[room204],
            remaining_pool=RemainingPool(groups)
        )

        ctx, seat_plan = AllocationService().execute(context)
        self.assertIsNotNone(ctx)
        self.assertIsNotNone(seat_plan)
        self.assertEqual(len(seat_plan.seats), 45)


if __name__ == '__main__':
    unittest.main()
