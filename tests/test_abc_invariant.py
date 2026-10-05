import unittest
from engine.adaptive.invariant import max_abc_rooms, AbcInvariant
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom
from engine.models.student import Student
from engine.models.group import Group
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.services.allocation_service import AllocationService
from engine.adaptive.candidate import AllocationCandidate as Candidate, StreamAssignment as CandidateAssignment
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.adaptive.pattern_optimizer import StreamPatternOptimizer


class TestAbcInvariant(unittest.TestCase):

    def test_max_abc_rooms_cases(self):
        self.assertEqual(max_abc_rooms({}), 0)
        self.assertEqual(max_abc_rooms({"A": 1}), 0)
        self.assertEqual(max_abc_rooms({"A": 1, "B": 1}), 0)
        self.assertEqual(max_abc_rooms({"A": 1, "B": 1, "C": 1}), 1)
        self.assertEqual(max_abc_rooms({"A": 3, "B": 3, "C": 3}), 3)
        self.assertEqual(max_abc_rooms({"A": 10, "B": 5, "C": 5}), 5)
        self.assertEqual(max_abc_rooms({"A": 10, "B": 2, "C": 2}), 2)
        self.assertEqual(max_abc_rooms({"A": 4, "B": 4, "C": 1}), 1)

    def test_aba_steal_rejected(self):
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3, seats_per_bench=3)
        room101 = RoomAllocation(c1)

        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN") for i in range(45)]
        students_cs = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN") for i in range(45)]
        students_ec = [Student(register_no=f"EC_{i}", name=f"EC_{i}", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN") for i in range(45)]

        g1 = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN", students=students_me, allocated_count=0)
        g2 = Group(group_id="G2", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN", students=students_cs, allocated_count=0)
        g3 = Group(group_id="G3", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN", students=students_ec, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(groups=groups, room_allocations=[room101], remaining_pool=RemainingPool(groups))
        invariant = AbcInvariant(context, stream_capacity=15)
        context.abc_invariant = invariant

        self.assertEqual(invariant.target_abc, 3)

        # ABA candidate: A=ME(15), B=CS(15), C=ME(15)
        cand = Candidate(
            room_index=0,
            assignments=[
                CandidateAssignment("A", "G1", 15),
                CandidateAssignment("B", "G2", 15),
                CandidateAssignment("C", "G1", 15),
            ],
            heuristic_name="test",
            decision_level=1
        )

        self.assertFalse(invariant.allows(context, cand))

    def test_genuine_abc_accepted(self):
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3, seats_per_bench=3)
        room101 = RoomAllocation(c1)

        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN") for i in range(45)]
        students_cs = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN") for i in range(45)]
        students_ec = [Student(register_no=f"EC_{i}", name=f"EC_{i}", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN") for i in range(45)]

        g1 = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN", students=students_me, allocated_count=0)
        g2 = Group(group_id="G2", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN", students=students_cs, allocated_count=0)
        g3 = Group(group_id="G3", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN", students=students_ec, allocated_count=0)

        groups = [g1, g2, g3]
        context = AllocationContext(groups=groups, room_allocations=[room101], remaining_pool=RemainingPool(groups))
        invariant = AbcInvariant(context, stream_capacity=15)
        context.abc_invariant = invariant

        # ABC candidate: A=ME(15), B=CS(15), C=EC(15)
        cand = Candidate(
            room_index=0,
            assignments=[
                CandidateAssignment("A", "G1", 15),
                CandidateAssignment("B", "G2", 15),
                CandidateAssignment("C", "G3", 15),
            ],
            heuristic_name="test",
            decision_level=1
        )

        self.assertTrue(invariant.allows(context, cand))

    def test_reserved_tail_enforcement(self):
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3, seats_per_bench=3)
        room101 = RoomAllocation(c1)

        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN") for i in range(20)]
        g1 = Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN", students=students_me, allocated_count=0)

        context = AllocationContext(groups=[g1], room_allocations=[room101], remaining_pool=RemainingPool([g1]))
        invariant = AbcInvariant(context, stream_capacity=15)
        invariant.reserved_tail["G1"] = 5
        context.abc_invariant = invariant

        cand = Candidate(
            room_index=0,
            assignments=[CandidateAssignment("A", "G1", 16)],
            heuristic_name="test",
            decision_level=1
        )
        self.assertFalse(invariant.allows(context, cand))

        cand_valid = Candidate(
            room_index=0,
            assignments=[CandidateAssignment("A", "G1", 15)],
            heuristic_name="test",
            decision_level=1
        )
        self.assertTrue(invariant.allows(context, cand_valid))

    def test_invariant_holds_after_execute(self):
        c1 = Classroom(room_no="101", rows=5, benches_per_row=3, seats_per_bench=3)
        c2 = Classroom(room_no="105", rows=5, benches_per_row=3, seats_per_bench=3)
        rooms = [RoomAllocation(c1), RoomAllocation(c2)]

        students_me = [Student(register_no=f"ME_{i}", name=f"ME_{i}", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN") for i in range(30)]
        students_cs = [Student(register_no=f"CS_{i}", name=f"CS_{i}", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN") for i in range(30)]
        students_ec = [Student(register_no=f"EC_{i}", name=f"EC_{i}", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN") for i in range(30)]

        groups = [
            Group(group_id="G1", department="ME", semester=3, section="A", subject_code="SUB1", subject_name="S1", exam_date="12-03-2026", session="AN", students=students_me, allocated_count=0),
            Group(group_id="G2", department="CS", semester=3, section="A", subject_code="SUB2", subject_name="S2", exam_date="12-03-2026", session="AN", students=students_cs, allocated_count=0),
            Group(group_id="G3", department="EC", semester=3, section="A", subject_code="SUB3", subject_name="S3", exam_date="12-03-2026", session="AN", students=students_ec, allocated_count=0),
        ]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool(groups))
        ctx, seat_plan = AllocationService().execute(context)
        self.assertTrue(ctx.abc_invariant.holds(ctx))


if __name__ == '__main__':
    unittest.main()
