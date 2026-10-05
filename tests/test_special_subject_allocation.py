import unittest
from engine.models.student import Student
from engine.models.classroom import Classroom
from engine.models.room_allocation import RoomAllocation
from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
from engine.validators.allocation_validator import AllocationValidator


class SpecialSubjectAllocationEngineTests(unittest.TestCase):

    def setUp(self):
        self.allocator = ConstrainedBestFitAllocator()
        self.validator = AllocationValidator()

    def test_1_normal_subjects_preserve_existing_behavior(self):
        """TEST 1: Normal subjects preserve existing behavior (department consolidation, ABC pattern)."""
        students = []
        # Department CE: 15 students writing 23CET601
        for i in range(15):
            students.append(Student(
                register_no=f"TKM23CE{i+1:03d}",
                name=f"CE Student {i+1}",
                department="CE",
                semester=6,
                section="A",
                subject_code="23CET601",
                subject_name="Civil Core",
                exam_date="12-03-2026",
                session="FN",
                roll_no=f"CE{i+1}",
                subject_category="NORMAL",
            ))
        # Department ME: 15 students writing 23MET601
        for i in range(15):
            students.append(Student(
                register_no=f"TKM23ME{i+1:03d}",
                name=f"ME Student {i+1}",
                department="ME",
                semester=6,
                section="A",
                subject_code="23MET601",
                subject_name="Mech Core",
                exam_date="12-03-2026",
                session="FN",
                roll_no=f"ME{i+1}",
                subject_category="NORMAL",
            ))
        # Department CS: 15 students writing 23CST601
        for i in range(15):
            students.append(Student(
                register_no=f"TKM23CS{i+1:03d}",
                name=f"CS Student {i+1}",
                department="CS",
                semester=6,
                section="A",
                subject_code="23CST601",
                subject_name="CS Core",
                exam_date="12-03-2026",
                session="FN",
                roll_no=f"CS{i+1}",
                subject_category="NORMAL",
            ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.normal_subject_violations, 0)
        self.assertEqual(val.missing_students, 0)
        # Verify streams have distinct departments (CE, ME, CS consolidated in distinct streams)
        stream_depts = [list(r.get_stream(s).departments) for r in ctx.room_allocations for s in ["A", "B", "C"]]
        self.assertTrue(all(len(d) == 1 for d in stream_depts if d))

    def test_2_same_elective_subject_students_never_adjacent(self):
        """TEST 2: Same elective subject students are never adjacent (left/right, front/back, diagonal)."""
        students = []
        # 4 electives across 40 students
        electives = ["22ECE803.1", "22ECE803.2", "22ECE803.3", "22ECE803.4"]
        for idx, code in enumerate(electives, 1):
            for i in range(10):
                students.append(Student(
                    register_no=f"EC_{idx}_{i}",
                    name=f"EC Student {idx}_{i}",
                    department="EC",
                    semester=8,
                    section="A",
                    subject_code=code,
                    subject_name=f"Elective {idx}",
                    exam_date="12-03-2026",
                    session="FN",
                    subject_category="ELECTIVE",
                ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3)), RoomAllocation(Classroom("102", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.elective_adjacency_violations, 0)

        # Manually verify all 8 adjacent neighbors for every student
        col_map = {"A": 0, "B": 1, "C": 2}
        for room in ctx.room_allocations:
            for s_name in ["A", "B", "C"]:
                stream = room.get_stream(s_name)
                for idx, st in enumerate(stream.students):
                    bench = idx + 1
                    adj_students = room.get_adjacent_students(s_name, bench)
                    for adj in adj_students:
                        self.assertNotEqual(
                            st.normalized_subject_code, adj.normalized_subject_code,
                            f"Adjacent seats {s_name}{bench} and neighbor share elective {st.subject_code}"
                        )

    def test_3_same_department_students_different_electives_can_be_adjacent(self):
        """TEST 3: Same department students from different elective subjects CAN be adjacent."""
        students = []
        # EC Department: 2 students in E1, 2 students in E2, 2 students in E3, 2 students in E4
        for i in range(2):
            students.append(Student(f"EC_E1_{i}", f"EC E1 {i}", "EC", 8, "A", "22ECE803.1", "E1", "12-03-2026", "FN", subject_category="ELECTIVE"))
            students.append(Student(f"EC_E2_{i}", f"EC E2 {i}", "EC", 8, "A", "22ECE803.2", "E2", "12-03-2026", "FN", subject_category="ELECTIVE"))
            students.append(Student(f"EC_E3_{i}", f"EC E3 {i}", "EC", 8, "A", "22ECE803.3", "E3", "12-03-2026", "FN", subject_category="ELECTIVE"))
            students.append(Student(f"EC_E4_{i}", f"EC E4 {i}", "EC", 8, "A", "22ECE803.4", "E4", "12-03-2026", "FN", subject_category="ELECTIVE"))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.elective_adjacency_violations, 0)
        # Verify that all students in the room are from department EC and sit adjacent to each other without error
        room = ctx.room_allocations[0]
        self.assertEqual(room.departments, {"EC"})
        # Check that adjacent seats contain students from different subjects
        for s_name in ["A", "B", "C"]:
            stream = room.get_stream(s_name)
            for idx, st in enumerate(stream.students):
                bench = idx + 1
                adj = room.get_adjacent_students(s_name, bench)
                for other in adj:
                    self.assertEqual(other.department, "EC")  # Both from EC
                    self.assertNotEqual(st.normalized_subject_code, other.normalized_subject_code)  # Different electives

    def test_4_minor_subject_students_never_adjacent(self):
        """TEST 4: Minor subject students with same subject code are never adjacent."""
        students = []
        minor_codes = ["22MAT201-M", "22EST201-M", "22CST201-M", "22MET201-M"]
        for idx, code in enumerate(minor_codes, 1):
            for i in range(8):
                students.append(Student(
                    register_no=f"MIN_{idx}_{i}",
                    name=f"Minor Student {idx}_{i}",
                    department="CE",
                    semester=4,
                    section="A",
                    subject_code=code,
                    subject_name=f"Minor Subject {idx}",
                    exam_date="14-03-2026",
                    session="FN",
                    subject_category="MINOR",
                ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3)), RoomAllocation(Classroom("102", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.minor_adjacency_violations, 0)

    def test_5_honours_subject_students_never_adjacent(self):
        """TEST 5: Honours subject students with same subject code are never adjacent."""
        students = []
        honours_codes = ["22CSH301", "22ECH301", "22EEH301", "22MEH301"]
        for idx, code in enumerate(honours_codes, 1):
            for i in range(8):
                students.append(Student(
                    register_no=f"HON_{idx}_{i}",
                    name=f"Honours Student {idx}_{i}",
                    department="CS",
                    semester=6,
                    section="A",
                    subject_code=code,
                    subject_name=f"Honours Subject {idx}",
                    exam_date="15-03-2026",
                    session="FN",
                    subject_category="HONOURS",
                ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3)), RoomAllocation(Classroom("102", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.honours_adjacency_violations, 0)

    def test_6_mixed_room_respects_both_rule_sets(self):
        """TEST 6: Mixed room containing normal and elective students respects both rule sets correctly."""
        students = []
        # Normal CE students (15)
        for i in range(15):
            students.append(Student(
                register_no=f"TKM23CE{i+1:03d}",
                name=f"CE Student {i+1}",
                department="CE",
                semester=6,
                section="A",
                subject_code="23CET601",
                subject_name="Civil Core",
                exam_date="12-03-2026",
                session="FN",
                subject_category="NORMAL",
            ))
        # Elective students from EC (4 different electives, 5 students each = 20 students)
        for idx in range(1, 5):
            for i in range(5):
                students.append(Student(
                    register_no=f"EC_E_{idx}_{i}",
                    name=f"EC Student {idx}_{i}",
                    department="EC",
                    semester=8,
                    section="A",
                    subject_code=f"22ECE803.{idx}",
                    subject_name=f"Elective {idx}",
                    exam_date="12-03-2026",
                    session="FN",
                    subject_category="ELECTIVE",
                ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.normal_subject_violations, 0)
        self.assertEqual(val.elective_adjacency_violations, 0)
        self.assertEqual(val.missing_students, 0)

    def test_7_elective_code_normalization(self):
        """TEST 7: Elective code normalization treats different codes (e.g. 22ECE803.1 vs 22ECE803.2) as distinct subjects."""
        s1 = Student("REG1", "Student 1", "EC", 8, "A", "22ECE803.1", "El 1", "12-03-2026", "FN", subject_category="ELECTIVE")
        s2 = Student("REG2", "Student 2", "EC", 8, "A", "22ECE803.2", "El 2", "12-03-2026", "FN", subject_category="ELECTIVE")

        self.assertNotEqual(s1.normalized_subject_code, s2.normalized_subject_code)
        groups = GroupBuilder().build([s1, s2])
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].normalized_subject_code, "22ECE803.1")
        self.assertEqual(groups[1].normalized_subject_code, "22ECE803.2")

    def test_8_maximizing_distance_distributes_same_elective(self):
        """TEST 8: Maximizing distance distributes same elective subject across available seats/rooms (A B C A B C preferred over clumped)."""
        students = []
        # 3 electives with 6 students each (18 students total)
        for idx in [1, 2, 3]:
            for i in range(6):
                students.append(Student(
                    register_no=f"ST_{idx}_{i}",
                    name=f"Student {idx}_{i}",
                    department="EC",
                    semester=8,
                    section="A",
                    subject_code=f"22ECE803.{idx}",
                    subject_name=f"Elective {idx}",
                    exam_date="12-03-2026",
                    session="FN",
                    subject_category="ELECTIVE",
                ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")
        self.assertEqual(val.elective_adjacency_violations, 0)

        # Verify that within any stream, consecutive benches have different subjects
        room = ctx.room_allocations[0]
        for s_name in ["A", "B", "C"]:
            st = room.get_stream(s_name)
            for idx in range(len(st.students) - 1):
                self.assertNotEqual(
                    st.students[idx].normalized_subject_code,
                    st.students[idx + 1].normalized_subject_code,
                    f"Stream {s_name} benches {idx+1} and {idx+2} share subject"
                )

    def test_9_validation_catches_same_special_subject_adjacency(self):
        """TEST 9: Validation catches SAME_SPECIAL_SUBJECT_ADJACENCY when violated and reports correctly."""
        s1 = Student("REG1", "Student 1", "EC", 8, "A", "22ECE803.1", "El 1", "12-03-2026", "FN", subject_category="ELECTIVE")
        s2 = Student("REG2", "Student 2", "EC", 8, "A", "22ECE803.1", "El 1", "12-03-2026", "FN", subject_category="ELECTIVE")

        room = RoomAllocation(Classroom("101", 5, 3, 3))
        # Deliberately place s1 and s2 adjacently in Stream A (benches 1 and 2: front/back conflict)
        room.get_stream("A").students.append(s1)
        room.get_stream("A").students.append(s2)

        context = AllocationContext(groups=[], room_allocations=[room], remaining_pool=RemainingPool())
        val = self.validator.validate(context)

        self.assertFalse(val.success)
        self.assertEqual(val.elective_adjacency_violations, 1)
        self.assertTrue(any("SAME_SPECIAL_SUBJECT_ADJACENCY" in err for err in val.errors))

    def test_10_final_validation_report_outputs_all_8_metrics(self):
        """TEST 10: Final validation report outputs all 8 required metrics."""
        students = []
        for idx in range(1, 5):
            for i in range(8):
                students.append(Student(
                    register_no=f"ST_{idx}_{i}",
                    name=f"Student {idx}_{i}",
                    department="EC",
                    semester=8,
                    section="A",
                    subject_code=f"22ECE803.{idx}",
                    subject_name=f"Elective {idx}",
                    exam_date="12-03-2026",
                    session="FN",
                    subject_category="ELECTIVE",
                ))

        groups = GroupBuilder().build(students)
        rooms = [RoomAllocation(Classroom("101", 5, 3, 3))]
        context = AllocationContext(groups=groups, room_allocations=rooms, remaining_pool=RemainingPool())

        ctx = self.allocator.execute(context)
        val = self.validator.validate(ctx)

        self.assertTrue(val.success, f"Validation failed: {val.errors}")

        report = val.generate_report()
        self.assertIn("Normal subject violations:", report)
        self.assertIn("Elective subject adjacency violations:", report)
        self.assertIn("Minor subject adjacency violations:", report)
        self.assertIn("Honours subject adjacency violations:", report)
        self.assertIn("Maximum departments per room:", report)
        self.assertIn("Missing students:", report)
        self.assertIn("Duplicate students:", report)
        self.assertIn("Capacity violations:", report)

        self.assertEqual(val.normal_subject_violations, 0)
        self.assertEqual(val.elective_adjacency_violations, 0)
        self.assertEqual(val.minor_adjacency_violations, 0)
        self.assertEqual(val.honours_adjacency_violations, 0)
        self.assertLessEqual(val.max_departments_per_room, 4)
        self.assertEqual(val.missing_students, 0)
        self.assertEqual(val.duplicate_students, 0)
        self.assertEqual(val.capacity_violations, 0)


if __name__ == "__main__":
    unittest.main()

