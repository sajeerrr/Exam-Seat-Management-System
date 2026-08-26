from engine.adaptive.candidate_generator import CandidateGenerator
from engine.adaptive.controller import HyperHeuristicController
from engine.adaptive.evaluator import CandidateEvaluator
from engine.adaptive.features import FeatureExtractor
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.adaptive.lookahead import LookaheadSimulator
from engine.config import AllocationLimits
from engine.validators.allocation_validator import AllocationValidator


class AdaptiveAllocationEngine:
    def __init__(self):
        self.feature_extractor = FeatureExtractor()
        self.generator = CandidateGenerator()
        self.evaluator = CandidateEvaluator()
        self.controller = HyperHeuristicController()
        self.lookahead = LookaheadSimulator(depth=1)
        self.optimizer = LocalOptimizer()
        self.validator = AllocationValidator()

    def execute(self, context):
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        target_count = self._target_room_count(
            context.room_allocations,
            total_students,
        )

        for room_index in range(target_count):
            if not self._has_remaining_groups(context):
                break
            self._allocate_room(context, room_index)

        # Fallback: Handle any remaining students with greedy allocation
        if self._has_remaining_groups(context):
            self._fallback_greedy_allocation(context)

        return self.optimizer.optimize(context)

    def _allocate_room(self, context, room_index):
        room = context.room_allocations[room_index]
        stalled_steps = 0

        while (
            self._has_remaining_groups(context)
            and room.used_capacity < room.classroom.capacity
        ):
            features = self.feature_extractor.extract(context)
            candidates = self.generator.generate(context, room_index, features)

            # If no candidates generated, try fallback
            if not candidates:
                if not self._fallback_room_allocation(context, room_index):
                    break
                stalled_steps = 0
                continue

            scored = [
                self.evaluator.evaluate(candidate, context, features)
                for candidate in candidates
            ]
            scored = self.lookahead.adjust_scores(scored, context, features)
            best = self.controller.select(scored)

            if best is None or best.used_capacity <= 0:
                # Try fallback before giving up
                if not self._fallback_room_allocation(context, room_index):
                    break
                stalled_steps = 0
                continue

            before = self._remaining_students(context)
            self._apply(best, context)
            after = self._remaining_students(context)

            if after >= before:
                stalled_steps += 1
                if stalled_steps >= AllocationLimits.MAX_STALLED_STEPS:
                    break
            else:
                stalled_steps = 0

            if best.room_index != room_index:
                continue

            if room.used_capacity >= room.classroom.capacity:
                break

    def _fallback_greedy_allocation(self, context):
        """Simple greedy allocation when hyper-heuristic fails.

        Allocates remaining students to any available room/stream that
        can accommodate them, respecting subject conflicts.
        """
        for room_alloc in context.room_allocations:
            if not self._has_remaining_groups(context):
                break

            for stream_name in ["A", "B", "C"]:
                stream = room_alloc.get_stream(stream_name)
                if not stream or stream.remaining_capacity == 0:
                    continue

                for group in context.groups:
                    if group.remaining_count == 0:
                        continue

                    if not room_alloc.can_add_department(
                        group.department, is_fallback_pass=True
                    ):
                        continue

                    if not room_alloc.can_seat_subject(
                        stream_name,
                        group.subject_code,
                        group.department,
                        group.subject_name,
                    ):
                        continue

                    take = min(stream.remaining_capacity, group.remaining_count)
                    room_alloc.assign_to_stream(stream_name, group, take)

    def _fallback_room_allocation(self, context, room_index):
        """Fallback allocation for a single room when no candidates work.

        Returns True if any students were allocated, False otherwise.
        """
        room = context.room_allocations[room_index]
        allocated_any = False

        for stream_name in ["A", "B", "C"]:
            stream = room.get_stream(stream_name)
            if not stream or stream.remaining_capacity == 0:
                continue

            for group in context.groups:
                if group.remaining_count == 0:
                    continue

                if not room.can_add_department(group.department, is_fallback_pass=True):
                    continue

                if not room.can_seat_subject(
                    stream_name,
                    group.subject_code,
                    group.department,
                    group.subject_name,
                ):
                    continue

                take = min(stream.remaining_capacity, group.remaining_count)
                room.assign_to_stream(stream_name, group, take)
                allocated_any = True

        return allocated_any

    def _apply(self, candidate, context):
        room = context.room_allocations[candidate.room_index]
        groups = {g.group_id: g for g in context.groups}

        for assignment in candidate.assignments:
            group = groups[assignment.group_id]
            room.assign_to_stream(
                assignment.stream,
                group,
                assignment.count,
            )

    def _has_remaining_groups(self, context):
        return any(g.remaining_count > 0 for g in context.groups)

    def _remaining_students(self, context):
        return sum(g.remaining_count for g in context.groups)

    def _target_room_count(self, room_allocations, total_students):
        capacity = 0
        for index, room_alloc in enumerate(room_allocations, start=1):
            capacity += room_alloc.classroom.capacity
            if capacity >= total_students:
                return index
        return len(room_allocations)

    def _validate_optimization(self, context):
        """Validate that optimizer didn't introduce constraint violations.

        Logs warnings if validation fails but doesn't prevent allocation.
        """
        result = self.validator.validate(context)
        if not result.success:
            import warnings
            warnings.warn(
                f"LocalOptimizer introduced constraint violations: {result.errors}"
            )
        if result.warnings:
            import warnings
            for warning in result.warnings:
                warnings.warn(f"Allocation warning: {warning}")
        return context
