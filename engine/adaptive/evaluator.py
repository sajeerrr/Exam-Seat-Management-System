from engine.adaptive.constraints import ConstraintValidator
from engine.adaptive.continuation import ContinuationSearch
from engine.config import ScoringWeights, AllocationThresholds


class CandidateEvaluator:
    def __init__(self, validator=None, continuation=None):
        self.validator = validator or ConstraintValidator()
        self.continuation = continuation or ContinuationSearch()

    def evaluate(self, candidate, context, features):
        if not self.validator.is_feasible(candidate, context):
            candidate.total_score = float("-inf")
            candidate.score_breakdown = {"feasible": 0}
            return candidate

        projected = self._project_remaining(candidate, context)
        room = context.room_allocations[candidate.room_index]
        room_capacity = room.classroom.capacity
        used_after = room.used_capacity + candidate.used_capacity
        utilization = used_after / room_capacity if room_capacity else 0
        balance = self._balance_score(projected)
        fragmentation = self._fragmentation_score(candidate, projected)
        diversity = self._diversity_score(candidate, context)
        leftover = self._leftover_score(projected)
        future = self._future_room_pressure(projected, context, candidate)
        partial_penalty = self._partial_room_penalty(
            used_after,
            room_capacity,
            projected,
        )
        final_tail_penalty = self._final_tail_penalty(
            projected,
            room_capacity,
        )
        continuity = self.continuation.continuation_score(candidate, context)
        new_fragments = self.continuation.new_fragment_count(candidate, context)
        department_room_penalty = self._department_room_penalty(
            candidate,
            context,
        )
        mixed_column_penalty = self._mixed_column_penalty(candidate, context)
        abc_reward = self._abc_reward(candidate, context)
        repeated_pattern_penalty = self._repeated_pattern_penalty(
            candidate,
            context,
        )

        candidate.score_breakdown = {
            "abc_reward": abc_reward,
            "continuity": continuity,
            "utilization": utilization,
            "balance": balance,
            "fragmentation": fragmentation,
            "diversity": diversity,
            "leftover": leftover,
            "future": future,
            "partial_penalty": partial_penalty,
            "final_tail_penalty": final_tail_penalty,
            "new_fragments": new_fragments,
            "department_room_penalty": department_room_penalty,
            "mixed_column_penalty": mixed_column_penalty,
            "repeated_pattern_penalty": repeated_pattern_penalty,
        }
        candidate.total_score = (
            ScoringWeights.ABC_REWARD * abc_reward
            + ScoringWeights.CONTINUITY * continuity
            + ScoringWeights.FRAGMENTATION * fragmentation
            + ScoringWeights.LEFTOVER * leftover
            + ScoringWeights.BALANCE * balance
            + ScoringWeights.DIVERSITY * diversity
            + ScoringWeights.UTILIZATION * utilization
            + ScoringWeights.FUTURE * future
            - ScoringWeights.NEW_FRAGMENTS_PENALTY * new_fragments
            - ScoringWeights.DEPARTMENT_ROOM_PENALTY * department_room_penalty
            - ScoringWeights.MIXED_COLUMN_PENALTY * mixed_column_penalty
            - ScoringWeights.REPEATED_PATTERN_PENALTY * repeated_pattern_penalty
            - ScoringWeights.PARTIAL_PENALTY * partial_penalty
            - ScoringWeights.FINAL_TAIL_PENALTY * final_tail_penalty
        )
        return candidate

    def _project_remaining(self, candidate, context):
        projected = {
            g.group_id: g.remaining_count
            for g in context.groups
            if g.remaining_count > 0
        }
        for assignment in candidate.assignments:
            projected[assignment.group_id] -= assignment.count
        return {
            group_id: count
            for group_id, count in projected.items()
            if count > 0
        }

    def _balance_score(self, projected):
        values = list(projected.values())
        if not values:
            return 1
        average = sum(values) / len(values)
        variance = sum((v - average) ** 2 for v in values) / len(values)
        return 1 / (1 + variance / 100)

    def _fragmentation_score(self, candidate, projected):
        assigned = {a.group_id for a in candidate.assignments}
        if not assigned:
            return 0
        completed = len([g for g in assigned if g not in projected])
        return min(1, 0.25 + completed / len(assigned))

    def _diversity_score(self, candidate, context):
        groups = {g.group_id: g for g in context.groups}
        departments = {
            groups[a.group_id].department
            for a in candidate.assignments
            if a.group_id in groups
        }
        b_assignment = next(
            (a for a in candidate.assignments if a.stream == "B"),
            None,
        )
        b_bonus = 0
        if b_assignment:
            b_dept = groups[b_assignment.group_id].department
            side_depts = {
                groups[a.group_id].department
                for a in candidate.assignments
                if a.stream in {"A", "C"}
            }
            if b_dept not in side_depts:
                b_bonus = 0.25
        return min(1, len(departments) / 3 + b_bonus)

    def _leftover_score(self, projected):
        if not projected:
            return 1
        scores = []
        preferred = AllocationThresholds.PREFERRED_REMAINDERS
        for remaining in projected.values():
            distance = min(abs(remaining - p) for p in preferred)
            tiny_penalty = AllocationThresholds.TINY_REMAINDER_PENALTY if 0 < remaining < AllocationThresholds.TINY_REMAINDER_THRESHOLD else 0
            scores.append(1 / (1 + distance + tiny_penalty))
        return sum(scores) / len(scores)

    def _future_room_pressure(self, projected, context, candidate):
        remaining = sum(projected.values())
        future_rooms = context.room_allocations[candidate.room_index + 1:]
        capacity = sum(r.classroom.capacity for r in future_rooms)
        if remaining == 0:
            return 1
        if capacity <= 0:
            return 0
        pressure = remaining / capacity
        if pressure > 1:
            return 0
        return max(0, 1 - abs(0.75 - pressure))

    def _partial_room_penalty(self, used_after, room_capacity, projected):
        if not projected or used_after == room_capacity:
            return 0
        return (room_capacity - used_after) / room_capacity

    def _final_tail_penalty(self, projected, room_capacity):
        remaining = sum(projected.values())
        if remaining == 0 or remaining >= room_capacity:
            return 0

        if remaining < room_capacity // 3:
            return (room_capacity // 3 - remaining) / (room_capacity // 3)

        return 0

    def _department_room_penalty(self, candidate, context):
        counts = self.continuation.department_room_count_after(
            candidate,
            context,
        )
        if not counts:
            return 0
        return sum(max(0, count - 1) for count in counts.values()) / len(counts)

    def _mixed_column_penalty(self, candidate, context):
        room = context.room_allocations[candidate.room_index]
        groups = {g.group_id: g for g in context.groups}
        departments_by_stream = {
            name: set(stream.departments)
            for name, stream in room.streams.items()
        }

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if group:
                departments_by_stream[assignment.stream].add(group.department)

        mixed = [
            stream_depts
            for stream_depts in departments_by_stream.values()
            if len(stream_depts) > 1
        ]
        return len(mixed) / 3

    def _abc_reward(self, candidate, context):
        room = context.room_allocations[candidate.room_index]
        groups = {g.group_id: g for g in context.groups}
        departments_by_stream = {
            name: set(stream.departments)
            for name, stream in room.streams.items()
        }

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if group:
                departments_by_stream[assignment.stream].add(group.department)

        occupied = [
            next(iter(departments))
            for departments in departments_by_stream.values()
            if len(departments) == 1
        ]

        if any(len(departments) > 1 for departments in departments_by_stream.values()):
            return 0

        if len(occupied) == 3 and len(set(occupied)) == 3:
            return 1

        return 0

    def _repeated_pattern_penalty(self, candidate, context):
        room = context.room_allocations[candidate.room_index]
        groups = {g.group_id: g for g in context.groups}
        departments_by_stream = {
            name: set(stream.departments)
            for name, stream in room.streams.items()
        }

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if group:
                departments_by_stream[assignment.stream].add(group.department)

        signatures = [
            "+".join(sorted(departments))
            for departments in departments_by_stream.values()
            if departments
        ]
        if not signatures:
            return 0

        return (len(signatures) - len(set(signatures))) / len(signatures)
