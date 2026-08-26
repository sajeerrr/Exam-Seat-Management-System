from dataclasses import dataclass


STREAMS = ("A", "B", "C")


@dataclass(frozen=True)
class ColumnSwap:
    room_a_index: int
    stream_a: str
    room_b_index: int
    stream_b: str
    score_delta: float


class PatternDetector:
    def detect(self, room):
        labels = []
        department_ids = {}
        next_label = "A"

        for stream_name in STREAMS:
            signature = self._stream_signature(room.get_stream(stream_name))

            if not signature:
                labels.append("-")
                continue

            if signature not in department_ids:
                department_ids[signature] = next_label
                next_label = chr(ord(next_label) + 1)

            labels.append(department_ids[signature])

        return "".join(labels)

    def diversity_score(self, room):
        signatures = [
            self._stream_signature(room.get_stream(stream_name))
            for stream_name in STREAMS
            if room.get_stream(stream_name).students
        ]
        if not signatures:
            return 0
        return len(set(signatures)) / len(signatures)

    def repeated_department_count(self, room):
        signatures = [
            self._stream_signature(room.get_stream(stream_name))
            for stream_name in STREAMS
            if room.get_stream(stream_name).students
        ]
        return len(signatures) - len(set(signatures))

    def mixed_column_count(self, room):
        return sum(
            1
            for stream in room.streams.values()
            if len(stream.departments) > 1
        )

    def _stream_signature(self, stream):
        departments = sorted(stream.departments)
        if not departments:
            return ""
        if len(departments) > 1:
            return "MIXED:" + "+".join(departments)
        return "+".join(departments)


class CandidateSwapGenerator:
    def __init__(self, window=4):
        self.window = window

    def generate(self, context):
        used_indexes = [
            index
            for index, room in enumerate(context.room_allocations)
            if room.used_capacity > 0
        ]

        for left_position, left_index in enumerate(used_indexes):
            nearby = used_indexes[
                left_position + 1:left_position + 1 + self.window
            ]

            for right_index in nearby:
                for left_stream in STREAMS:
                    for right_stream in STREAMS:
                        yield left_index, left_stream, right_index, right_stream


class PatternEvaluator:
    def __init__(self):
        self.detector = PatternDetector()

    def score_context(self, context):
        used_rooms = [
            room for room in context.room_allocations
            if room.used_capacity > 0
        ]
        if not used_rooms:
            return 0

        diversity = sum(
            self.detector.diversity_score(room)
            for room in used_rooms
        )
        repeated = sum(
            self.detector.repeated_department_count(room)
            for room in used_rooms
        )
        mixed = sum(
            self.detector.mixed_column_count(room)
            for room in used_rooms
        )
        fragmentation = self._department_fragmentation(context)
        abc_count = self.abc_count(context)

        return (
            500 * abc_count
            + 60 * diversity
            - 45 * repeated
            - 35 * mixed
            - 80 * fragmentation
        )

    def abc_count(self, context):
        return sum(
            1
            for room in context.room_allocations
            if room.used_capacity > 0 and self.detector.detect(room) == "ABC"
        )

    def is_valid_swap(self, context, left_index, left_stream, right_index, right_stream):
        left_room = context.room_allocations[left_index]
        right_room = context.room_allocations[right_index]

        if left_room is right_room:
            return False

        left_column = left_room.get_stream(left_stream)
        right_column = right_room.get_stream(right_stream)

        if not left_column.students or not right_column.students:
            return False

        if len(left_column.students) > right_column.capacity:
            return False

        if len(right_column.students) > left_column.capacity:
            return False

        before_fragments = self._department_fragmentation(context)
        before_abc = self.abc_count(context)
        self._swap(left_column, right_column)
        valid = (
            self._room_subjects_valid(left_room)
            and self._room_subjects_valid(right_room)
            and self._department_fragmentation(context) <= before_fragments
            and self.abc_count(context) >= before_abc
        )
        self._swap(left_column, right_column)
        return valid

    def score_swap(self, context, left_index, left_stream, right_index, right_stream):
        left_room = context.room_allocations[left_index]
        right_room = context.room_allocations[right_index]
        left_column = left_room.get_stream(left_stream)
        right_column = right_room.get_stream(right_stream)

        before = self.score_context(context)
        movement_penalty = (
            len(left_column.students)
            + len(right_column.students)
        ) / 45

        self._swap(left_column, right_column)
        after = self.score_context(context)
        self._swap(left_column, right_column)

        return after - before - movement_penalty

    def apply_swap(self, context, swap):
        left_room = context.room_allocations[swap.room_a_index]
        right_room = context.room_allocations[swap.room_b_index]
        self._swap(
            left_room.get_stream(swap.stream_a),
            right_room.get_stream(swap.stream_b),
        )

    def _room_subjects_valid(self, room):
        subjects = {
            stream_name: room.get_stream(stream_name).subject_codes
            for stream_name in STREAMS
        }
        if subjects["A"].intersection(subjects["B"]):
            return False
        if subjects["B"].intersection(subjects["C"]):
            return False
        return True

    def _department_fragmentation(self, context):
        rooms_by_department = {}

        for index, room in enumerate(context.room_allocations):
            if room.used_capacity == 0:
                continue

            for department in room.departments:
                rooms_by_department.setdefault(department, set()).add(index)

        return sum(
            max(0, len(room_indexes) - 1)
            for room_indexes in rooms_by_department.values()
        )

    def _swap(self, left_column, right_column):
        left_column.students, right_column.students = (
            right_column.students,
            left_column.students,
        )


class StreamPatternOptimizer:
    def __init__(self, max_passes=10):
        self.generator = CandidateSwapGenerator()
        self.evaluator = PatternEvaluator()
        self.max_passes = max_passes

    def optimize(self, context):
        passes = 0

        while passes < self.max_passes:
            best_swap = self._best_swap(context)
            if not best_swap or best_swap.score_delta <= 0:
                break

            self.evaluator.apply_swap(context, best_swap)
            passes += 1

        return context

    def _best_swap(self, context):
        best = None

        for left_index, left_stream, right_index, right_stream in self.generator.generate(context):
            if not self.evaluator.is_valid_swap(
                context,
                left_index,
                left_stream,
                right_index,
                right_stream,
            ):
                continue

            delta = self.evaluator.score_swap(
                context,
                left_index,
                left_stream,
                right_index,
                right_stream,
            )

            if delta <= 0:
                continue

            candidate = ColumnSwap(
                left_index,
                left_stream,
                right_index,
                right_stream,
                delta,
            )

            if not best or candidate.score_delta > best.score_delta:
                best = candidate

        return best
