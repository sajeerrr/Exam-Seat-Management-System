# engine/lns/lns_engine.py

from engine.context.allocation_context import AllocationContext
import random
from engine.lns.destroy_operators import (
    WorstRoomsDestroy,
    RandomClusterDestroy,
    DepartmentFocusDestroy,
)
from engine.lns.repair_operator import RepairOperator
from engine.adaptive.evaluator import CandidateEvaluator
from engine.config import LNSConfig


class LNSEngine:
    """Phase 3: Large Neighborhood Search for iterative improvement."""

    def __init__(self, max_iterations=None, time_limit_seconds=None):
        self.destroy_operators = [
            WorstRoomsDestroy(),
            RandomClusterDestroy(),
            DepartmentFocusDestroy(),
        ]
        self.repair_operator = RepairOperator()
        self.evaluator = CandidateEvaluator()
        self.max_iterations = max_iterations or LNSConfig.MAX_ITERATIONS
        self.time_limit = time_limit_seconds or LNSConfig.TIME_LIMIT_SECONDS

    def _score_context(self, context) -> float:
        """Compute a global evaluation score for the context."""
        # Sum of utilization and ABC rewards across all rooms
        total_score = 0.0
        features = {}
        for room in context.room_allocations:
            util = room.used_capacity / room.classroom.capacity if room.classroom.capacity else 0
            total_score += util * 50.0

            # ABC check
            streams = room.streams
            depts_a = streams["A"].departments
            depts_b = streams["B"].departments
            depts_c = streams["C"].departments
            if len(depts_a) == 1 and len(depts_b) == 1 and len(depts_c) == 1:
                if len({next(iter(depts_a)), next(iter(depts_b)), next(iter(depts_c))}) == 3:
                    total_score += 150.0
        return total_score

    def optimize(self, context) -> AllocationContext:
        """
        Iterative LNS destroy-and-repair loop.
        """
        num_rooms = len(context.room_allocations)
        if num_rooms <= 1:
            return context

        best_score = self._score_context(context)

        for iteration in range(self.max_iterations):
            # 1. Snapshot current state
            snapshot = context.snapshot()

            # 2. Select destroy operator and rooms
            operator = random.choice(self.destroy_operators)
            destroy_size = random.randint(LNSConfig.DESTROY_SIZE_MIN, min(LNSConfig.DESTROY_SIZE_MAX, num_rooms))
            destroyed_indices = operator.select_rooms(context, num_rooms=destroy_size)

            # 3. Destroy selected rooms (clear streams and de-allocate students)
            for idx in destroyed_indices:
                room = context.room_allocations[idx]
                for stream in room.streams.values():
                    for student in stream.students:
                        # Find corresponding group and deallocate
                        for group in context.groups:
                            if student in group.students:
                                group.deallocate(1)
                    stream.students.clear()

            # 4. Repair destroyed rooms using CP solver
            success = self.repair_operator.repair(context, destroyed_indices, time_limit=LNSConfig.REPAIR_TIME_LIMIT)

            if not success:
                # Rollback
                context.restore(snapshot)
                continue

            # 5. Evaluate new solution
            new_score = self._score_context(context)

            # 6. Accept or reject
            if new_score >= best_score + LNSConfig.ACCEPTANCE_THRESHOLD:
                best_score = new_score
            else:
                # Rollback
                context.restore(snapshot)

        return context
