import unittest
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.student import Student
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.adaptive.local_optimizer import LocalOptimizer

class TestGlobalAbcOptimization(unittest.TestCase):

    def test_aba_to_abc_conversion(self):
        c1 = Classroom(room_no="204", rows=5, benches_per_row=3, seats_per_bench=3)
        c2 = Classroom(room_no="205", rows=5, benches_per_row=3, seats_per_bench=3)

        room204 = RoomAllocation(c1)
        room205 = RoomAllocation(c2)

        students_me1 = [Student(register_no=f"ME1_{i}", name=f"ME1_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_el = [Student(register_no=f"EL_{i}", name=f"EL_{i}", department="EL", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_me2 = [Student(register_no=f"ME2_{i}", name=f"ME2_{i}", department="ME", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN") for i in range(15)]
        students_cs = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB4", subject_name="S4", exam_date="12-03-2026", session="FN") for i in range(15)]

        room204.streams["A"].students.extend(students_me1)
        room204.streams["B"].students.extend(students_el)
        room204.streams["C"].students.extend(students_me2)

        room205.streams["A"].students.extend(students_cs)
        room205.streams["B"].students.extend(students_me2)

        g1 = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN", students=students_me1, allocated_count=15)
        g2 = Group(group_id="G2", department="EL", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="FN", students=students_el, allocated_count=15)
        g3 = Group(group_id="G3", department="ME", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="FN", students=students_me2, allocated_count=15)
        g4 = Group(group_id="G4", department="CS", semester=3, section="A", subject_code="SUB4", subject_name="S4", exam_date="12-03-2026", session="FN", students=students_cs, allocated_count=15)

        groups = [g1, g2, g3, g4]
        context = AllocationContext(
            groups=groups,
            room_allocations=[room204, room205],
            remaining_pool=RemainingPool(groups)
        )

        initial_abc = LocalOptimizer()._measure_global_pattern_quality(context)['abc_count']
        optimizer = LocalOptimizer()
        optimized_context = optimizer.optimize(context)
        final_metrics = optimizer._measure_global_pattern_quality(optimized_context)

        self.assertGreater(final_metrics['abc_count'], initial_abc)
        pattern = optimizer.pattern_optimizer.evaluator.detector.detect(optimized_context.room_allocations[0])
        self.assertEqual(pattern, "ABC")

    def test_student_conservation(self):
        c1 = Classroom(room_no="204", rows=5, benches_per_row=3, seats_per_bench=3)
        room204 = RoomAllocation(c1)
        students = [Student(register_no=f"S_{i}", name=f"S_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN") for i in range(10)]
        room204.streams["A"].students.extend(students)

        g = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="FN", students=students, allocated_count=10)

        groups = [g]
        context = AllocationContext(groups=groups, room_allocations=[room204], remaining_pool=RemainingPool(groups))
        total_before = sum(room.used_capacity for room in context.room_allocations)

        optimized = LocalOptimizer().optimize(context)
        total_after = sum(room.used_capacity for room in optimized.room_allocations)

        self.assertEqual(total_before, total_after)

if __name__ == '__main__':
    unittest.main()
