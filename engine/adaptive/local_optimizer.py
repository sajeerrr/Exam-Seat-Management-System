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
        snapshot_start = context.snapshot()
        try:
            changed = True
            passes = 0

            while changed and passes < AllocationLimits.MAX_OPTIMIZATION_PASSES:
                changed = self._repair_tiny_fragments(context)
                passes += 1

            context = self.pattern_optimizer.optimize(context)

            # Consolidate or balance underfilled rooms (< dynamic_min students)
            self._consolidate_underfilled_rooms(context)

            from engine.adaptive.stream_balancer import RoomStreamBalancer
            RoomStreamBalancer().balance(context)

            result = self.validator.validate(context)
            if not result.success:
                context.restore(snapshot_start)
                return context
            return context
        except Exception:
            context.restore(snapshot_start)
            return context

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
                    snapshot = context.snapshot()
                    before = self.pattern_evaluator.score_context(context)
                    before_abc = self.pattern_evaluator.abc_count(context)
                    self._move_fragment(
                        source_stream,
                        target_room.get_stream(target_stream_name),
                        fragment,
                    )
                    after = self.pattern_evaluator.score_context(context)
                    after_abc = self.pattern_evaluator.abc_count(context)

                    val = self.validator.validate(context)
                    if val.success and after >= before and after_abc >= before_abc:
                        return True

                    context.restore(snapshot)

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
        if bool(departments and departments != {department}):
            return True
        # Also prevent mixing different subjects within the same stream
        if stream.students:
            stream_subjects = {
                getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                for s in stream.students
            }
            first_stu = fragment["students"][0]
            frag_subject = getattr(first_stu, "normalized_subject_code", str(first_stu.subject_code).strip().upper())
            if stream_subjects != {frag_subject}:
                return True
        return False

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

    def _measure_global_pattern_quality(self, context) -> dict:
        """Return a snapshot of the current global allocation quality.

        Returns a dict with the following keys:
            - abc_count       (int):   rooms with perfect ABC pattern
            - diversity_score (float): sum of per-room diversity scores
            - repeated_count  (int):   total repeated-department count across rooms
            - mixed_count     (int):   total mixed-column count across rooms
            - fragmentation   (int):   dept-fragmentation count (extra rooms per dept)
        """
        from engine.adaptive.pattern_optimizer import PatternDetector
        detector = PatternDetector()
        used_rooms = [
            room for room in context.room_allocations
            if room.used_capacity > 0
        ]

        abc_count = sum(
            1 for room in used_rooms if detector.detect(room) == "ABC"
        )
        diversity_score = sum(
            detector.diversity_score(room) for room in used_rooms
        )
        repeated_count = sum(
            detector.repeated_department_count(room) for room in used_rooms
        )
        mixed_count = sum(
            detector.mixed_column_count(room) for room in used_rooms
        )

        # Fragmentation: number of extra rooms a department occupies.
        rooms_by_dept: dict = {}
        for idx, room in enumerate(context.room_allocations):
            for dept in room.departments:
                rooms_by_dept.setdefault(dept, set()).add(idx)
        fragmentation = sum(
            max(0, len(idxs) - 1) for idxs in rooms_by_dept.values()
        )

        return {
            "abc_count": abc_count,
            "diversity_score": diversity_score,
            "repeated_count": repeated_count,
            "mixed_count": mixed_count,
            "fragmentation": fragmentation,
        }

    def _consolidate_underfilled_rooms(self, context):
        """Attempts to consolidate or balance rooms having fewer than dynamic_min students (~25-30 students minimum)."""
        total_students = sum(len(s.students) for r in context.room_allocations for s in r.streams.values())
        if total_students == 0:
            return False

        min_rooms = max(1, (total_students + 44) // 45)
        dynamic_min = min(AllocationLimits.MIN_ROOM_STUDENTS, total_students // min_rooms) if min_rooms > 0 else 0
        if dynamic_min <= 0:
            return False

        changed = False

        # Phase 1: Try to move streams from underfilled rooms into empty streams in existing rooms
        for source_room in reversed(context.room_allocations):
            if source_room.used_capacity == 0 or source_room.used_capacity >= dynamic_min:
                continue

            for s_name, source_stream in list(source_room.streams.items()):
                if not source_stream.students:
                    continue

                stream_students = list(source_stream.students)
                stu_count = len(stream_students)

                for target_room in context.room_allocations:
                    if target_room == source_room:
                        continue

                    for t_name, target_stream in target_room.streams.items():
                        if len(target_stream.students) == 0 and target_stream.remaining_capacity >= stu_count:
                            snapshot = context.snapshot()
                            source_stream.students = []
                            target_stream.students = list(stream_students)

                            val = self.validator.validate(context)
                            if val.success:
                                changed = True
                                break
                            else:
                                context.restore(snapshot)

                    if not source_stream.students:
                        break

        # Phase 2: If an underfilled room still exists, try rebalancing from another room
        for target_room in context.room_allocations:
            if target_room.used_capacity == 0 or target_room.used_capacity >= dynamic_min:
                continue

            for donor_room in context.room_allocations:
                if donor_room == target_room or donor_room.used_capacity <= dynamic_min:
                    continue

                for d_stream_name in ["C", "A"]:
                    d_stream = donor_room.get_stream(d_stream_name)
                    if not d_stream or not d_stream.students:
                        continue

                    d_count = len(d_stream.students)
                    if donor_room.used_capacity - d_count < dynamic_min:
                        continue
                    for t_stream_name in ["C", "A", "B"]:
                        t_stream = target_room.get_stream(t_stream_name)
                        if t_stream and len(t_stream.students) == 0 and t_stream.remaining_capacity >= d_count:
                            snapshot = context.snapshot()
                            moved = list(d_stream.students)
                            d_stream.students = []
                            t_stream.students = moved

                            val = self.validator.validate(context)
                            if val.success and target_room.used_capacity >= dynamic_min and donor_room.used_capacity >= dynamic_min:
                                changed = True
                                break
                            else:
                                context.restore(snapshot)

                    if target_room.used_capacity >= dynamic_min:
                        break

        return changed
