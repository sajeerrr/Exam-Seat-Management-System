from engine.models.room_allocation import subject_conflict_key
from engine.adaptive.pattern_optimizer import PatternEvaluator, StreamPatternOptimizer
from engine.config import AllocationLimits
from engine.validators.allocation_validator import AllocationValidator


class LocalOptimizer:
    """Repairs tiny department fragments after constructive allocation.

    This optimizer runs after the main allocation to:
    1. Move tiny fragments (≤5 students) to better locations
    2. Optimize stream patterns for ABC configuration
    3. Validate that optimizations don't violate constraints

    Fragment Key Structure:
        Each fragment stores a key tuple: (department, subject_conflict_key)
        - Index 0: Department name (e.g., "CSE", "ECE")
        - Index 1: Subject conflict key string for subject matching
    """

    def __init__(self):
        self.pattern_optimizer = StreamPatternOptimizer()
        self.pattern_evaluator = PatternEvaluator()
        self.validator = AllocationValidator()

    def optimize(self, context):
        changed = True
        passes = 0

        while changed and passes < AllocationLimits.MAX_OPTIMIZATION_PASSES:
            changed = self._repair_tiny_fragments(context)
            passes += 1

        context = self.pattern_optimizer.optimize(context)

        # Validate after optimization to ensure no constraint violations
        return self._validate_optimization(context)

    def _repair_tiny_fragments(self, context):
        """Move tiny fragments to consolidate department placements.

        A fragment is a contiguous group of students from the same department/subject.
        Fragments with ≤5 students are considered "tiny" and candidates for relocation.
        """
        for source_room in reversed(context.room_allocations):
            for source_stream_name, source_stream in source_room.streams.items():
                fragments = self._stream_fragments(source_stream)

                for fragment in fragments:
                    # Use configurable threshold from AllocationLimits
                    if fragment["count"] > AllocationLimits.TINY_FRAGMENT_THRESHOLD:
                        continue

                    target = self._find_target(
                        context,
                        source_room,
                        source_stream_name,
                        fragment,
                    )
                    if not target:
                        continue

                    target_room, target_stream_name = target
                    before = self.pattern_evaluator.score_context(context)
                    before_abc = self.pattern_evaluator.abc_count(context)
                    self._move_fragment(
                        source_stream,
                        target_room.get_stream(target_stream_name),
                        fragment,
                    )
                    after = self.pattern_evaluator.score_context(context)
                    after_abc = self.pattern_evaluator.abc_count(context)

                    if after >= before and after_abc >= before_abc:
                        return True

                    target_stream = target_room.get_stream(target_stream_name)
                    del target_stream.students[-fragment["count"]:]
                    source_stream.students[
                        fragment["start"]:fragment["start"]
                    ] = fragment["students"]

        return False

    def _stream_fragments(self, stream):
        fragments = []
        if not stream.students:
            return fragments

        start = 0
        current_key = self._student_key(stream.students[0])

        for index, student in enumerate(stream.students[1:], start=1):
            key = self._student_key(student)
            if key == current_key:
                continue

            fragments.append(
                {
                    "key": current_key,
                    "start": start,
                    "end": index,
                    "count": index - start,
                    "students": stream.students[start:index],
                }
            )
            start = index
            current_key = key

        fragments.append(
            {
                "key": current_key,
                "start": start,
                "end": len(stream.students),
                "count": len(stream.students) - start,
                "students": stream.students[start:],
            }
        )
        return fragments

    def _find_target(self, context, source_room, source_stream_name, fragment):
        for target_room in context.room_allocations:
            if target_room is source_room:
                continue

            if fragment["key"][0] not in target_room.departments:
                continue

            for target_stream_name in ("A", "B", "C"):
                target_stream = target_room.get_stream(target_stream_name)
                if target_stream.remaining_capacity < fragment["count"]:
                    continue

                if self._creates_subject_conflict(
                    target_room,
                    target_stream_name,
                    fragment,
                ):
                    continue

                if self._creates_department_mix(target_stream, fragment):
                    continue

                return target_room, target_stream_name

        return None

    def _move_fragment(self, source_stream, target_stream, fragment):
        del source_stream.students[fragment["start"]:fragment["end"]]
        target_stream.students.extend(fragment["students"])

    def _creates_subject_conflict(self, room, stream_name, fragment):
        subject_key = fragment["key"][1]
        adjacent = []

        if stream_name == "A":
            adjacent = ["B"]
        elif stream_name == "B":
            adjacent = ["A", "C"]
        elif stream_name == "C":
            adjacent = ["B"]

        for adjacent_name in adjacent:
            if subject_key in room.get_stream(adjacent_name).subject_codes:
                return True

        return False

    def _creates_department_mix(self, stream, fragment):
        departments = set(stream.departments)
        department = fragment["key"][0]
        return bool(departments and departments != {department})

    def _student_key(self, student):
        """Generate a key tuple for grouping students.

        Returns:
            tuple: (department, subject_conflict_key)
                - department: Student's department (e.g., "CSE")
                - subject_conflict_key: Normalized subject identifier
        """
        return (
            getattr(student, "department", ""),
            subject_conflict_key(
                getattr(student, "subject_code", ""),
                getattr(student, "department", ""),
                getattr(student, "subject_name", ""),
            ),
        )

    def _validate_optimization(self, context):
        """Validate that optimizations didn't introduce constraint violations.

        Returns the context unchanged, but logs warnings if validation fails.
        """
        result = self.validator.validate(context)
        if not result.success:
            import warnings
            warnings.warn(
                f"LocalOptimizer introduced constraint violations: {result.errors}",
                UserWarning,
            )
        if result.warnings:
            import warnings
            for warning in result.warnings:
                warnings.warn(f"Allocation warning: {warning}", UserWarning)
        return context
