from itertools import permutations

from engine.adaptive.candidate import AllocationCandidate, StreamAssignment
from engine.models.room_allocation import subject_conflict_key


class CandidateGenerator:
    def __init__(self, max_groups_per_step=8, max_candidates=70):
        self.max_groups_per_step = max_groups_per_step
        self.max_candidates = max_candidates

    def generate(self, context, room_index, features):
        room = context.room_allocations[room_index]
        groups = [g for g in context.groups if g.remaining_count > 0]
        groups.sort(key=lambda g: (-g.remaining_count, g.group_id))

        if not groups:
            return []

        candidates = []
        candidates.extend(self._abc_candidates(room, room_index, groups))
        candidates.extend(self._aba_candidates(room, room_index, groups))
        candidates.extend(
            self._continuation_candidates(context, room_index, groups)
        )
        candidates.extend(self._balance_first(room, room_index, groups))
        candidates.extend(self._leftover_reduction(room, room_index, groups))
        candidates.extend(self._maximum_utilization(room, room_index, groups))
        candidates.extend(self._future_balance(room, room_index, groups))

        return self._dedupe(candidates)

    def _abc_candidates(self, room, room_index, groups):
        candidates = []
        selected = groups[:self.max_groups_per_step]

        for combo in permutations(selected, min(3, len(selected))):
            departments = {group.department for group in combo}
            if len(departments) < 3:
                continue

            assignments = self._assignments_for(
                room,
                zip(("A", "B", "C"), combo),
            )
            if assignments:
                candidates.append(
                    AllocationCandidate(
                        room_index,
                        assignments,
                        "abc_global",
                        decision_level=1,
                    )
                )

        return candidates

    def _aba_candidates(self, room, room_index, groups):
        candidates = []
        selected = groups[:self.max_groups_per_step]
        repeated_order = sorted(
            selected,
            key=lambda g: (-g.remaining_count, g.group_id),
        )

        for repeated_group in repeated_order:
            for buffer_group in selected:
                if buffer_group.group_id == repeated_group.group_id:
                    continue
                if buffer_group.department == repeated_group.department:
                    continue
                if self._subject_key(buffer_group) == self._subject_key(repeated_group):
                    continue

                assignments = self._assignments_for(
                    room,
                    (
                        ("A", repeated_group),
                        ("B", buffer_group),
                        ("C", repeated_group),
                    ),
                )
                if assignments:
                    candidates.append(
                        AllocationCandidate(
                            room_index,
                            assignments,
                            "aba_largest_repeat",
                            decision_level=2,
                        )
                    )

        return candidates

    def _continuation_candidates(self, context, room_index, groups):
        candidates = []
        current_room = context.room_allocations[room_index]

        for group in groups[:self.max_groups_per_step]:
            target_indexes = self._rooms_with_department(
                context,
                group.department,
            )
            target_indexes = [
                index for index in target_indexes
                if index <= room_index
            ]

            for target_index in target_indexes:
                room = context.room_allocations[target_index]
                assignments = []

                for stream_name in ("A", "B", "C"):
                    stream = room.get_stream(stream_name)
                    if not stream or stream.remaining_capacity <= 0:
                        continue

                    count = min(stream.remaining_capacity, group.remaining_count)
                    if count <= 0:
                        continue

                    assignments.append(
                        StreamAssignment(stream_name, group.group_id, count)
                    )

                for assignment in assignments:
                    candidates.append(
                        AllocationCandidate(
                            target_index,
                            [assignment],
                            "department_continuation",
                            decision_level=3,
                        )
                    )

        if current_room.used_capacity == 0:
            return candidates

        return candidates[:self.max_candidates]

    def _balance_first(self, room, room_index, groups):
        ordered = sorted(
            groups[:self.max_groups_per_step],
            key=lambda g: (
                abs(g.remaining_count - 15),
                -g.remaining_count,
                g.group_id,
            ),
        )
        return self._permutation_candidates(
            room, room_index, ordered, "balance_first"
        )

    def _leftover_reduction(self, room, room_index, groups):
        ordered = sorted(
            groups[:self.max_groups_per_step],
            key=lambda g: (
                self._future_remainder_penalty(g.remaining_count),
                -g.remaining_count,
                g.group_id,
            ),
        )
        return self._permutation_candidates(
            room, room_index, ordered, "leftover_reduction"
        )

    def _maximum_utilization(self, room, room_index, groups):
        ordered = sorted(
            groups[:self.max_groups_per_step],
            key=lambda g: (
                0 if g.remaining_count >= 15 else 1,
                -min(g.remaining_count, 15),
                g.group_id,
            ),
        )
        return self._permutation_candidates(
            room, room_index, ordered, "maximum_utilization"
        )

    def _future_balance(self, room, room_index, groups):
        ordered = sorted(
            groups[:self.max_groups_per_step],
            key=lambda g: (
                self._future_remainder_penalty(g.remaining_count),
                abs(g.remaining_count - 30),
                g.group_id,
            ),
        )
        return self._permutation_candidates(
            room, room_index, ordered, "future_balance"
        )

    def _permutation_candidates(self, room, room_index, groups, heuristic_name):
        candidates = []
        selected = groups[:min(len(groups), self.max_groups_per_step)]
        size = min(3, len(selected))

        for combo in permutations(selected, size):
            assignments = self._assignments_for(
                room,
                zip(("A", "B", "C"), combo),
            )
            if assignments:
                candidates.append(
                    AllocationCandidate(
                        room_index,
                        assignments,
                        heuristic_name,
                        decision_level=4,
                    )
                )
            if len(candidates) >= self.max_candidates:
                break

        return candidates

    def _assignments_for(self, room, stream_groups):
        assignments = []
        planned = {}

        for stream_name, group in stream_groups:
            stream = room.get_stream(stream_name)
            if not stream or stream.remaining_capacity <= 0:
                continue

            already_planned = planned.get(group.group_id, 0)
            remaining = group.remaining_count - already_planned
            count = min(stream.remaining_capacity, remaining)

            if count <= 0:
                continue

            planned[group.group_id] = already_planned + count
            assignments.append(
                StreamAssignment(stream_name, group.group_id, count)
            )

        return assignments

    def _dedupe(self, candidates):
        seen = set()
        unique = []

        for candidate in candidates:
            signature = candidate.signature()
            if not signature or signature in seen:
                continue
            seen.add(signature)
            unique.append(candidate)
            if len(unique) >= self.max_candidates:
                break

        return unique

    def _future_remainder_penalty(self, remaining_count):
        count = min(15, remaining_count)
        remaining = remaining_count - count
        distance = min(abs(remaining - x) for x in (0, 15, 30, 45, 60, 75))
        tiny_penalty = 20 if 0 < remaining < 5 else 0
        return distance + tiny_penalty

    def _subject_key(self, group):
        return subject_conflict_key(
            group.subject_code,
            group.department,
            group.subject_name,
        )

    def _rooms_with_department(self, context, department):
        indexes = []
        for index, room in enumerate(context.room_allocations):
            if department in room.departments:
                indexes.append(index)
        return indexes
