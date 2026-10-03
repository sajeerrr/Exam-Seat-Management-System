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
        # Import config for weights
        from engine.config import CPSolverConfig

        total_score = 0.0

        # Counters for metrics
        abc_count = 0
        aba_count = 0
        total_utilization = 0.0
        total_rooms_used = 0

        for room in context.room_allocations:
            # Room utilization
            util = room.used_capacity / room.classroom.capacity if room.classroom.capacity else 0
            total_utilization += util

            if room.used_capacity > 0:
                total_rooms_used += 1

            # Stream analysis
            streams = room.streams
            depts_a = streams["A"].departments
            depts_b = streams["B"].departments
            depts_c = streams["C"].departments

            # Check for ABC: three different departments, one per stream
            if (len(depts_a) == 1 and len(depts_b) == 1 and len(depts_c) == 1 and
                len(depts_a | depts_b | depts_c) == 3):  # Union has 3 distinct departments
                abc_count += 1
                total_score += CPSolverConfig.ABC_BONUS

            # Check for ABA: A and C same department, B different (and all streams have exactly one dept)
            elif (len(depts_a) == 1 and len(depts_b) == 1 and len(depts_c) == 1 and
                  len(depts_a) == 1 and len(depts_b) == 1 and len(depts_c) == 1 and
                  next(iter(depts_a)) == next(iter(depts_c)) and
                  next(iter(depts_a)) != next(iter(depts_b))):
                aba_count += 1
                total_score += CPSolverConfig.ABA_BONUS

            # Reward for occupied streams (encourages 3-stream usage)
            occupied_streams = sum(1 for s in streams.values() if len(s.students) > 0)
            total_score += occupied_streams * CPSolverConfig.STREAM_OCCUPANCY_BONUS

            # Small penalty for room usage (encourages consolidation)
            if room.used_capacity > 0:
                total_score -= CPSolverConfig.ROOM_USAGE_PENALTY

        # Add utilization component (smaller weight now)
        total_score += total_utilization * CPSolverConfig.UTILIZATION_BONUS * len(context.room_allocations)

        # Fragmentation penalty: extra rooms per department beyond the first needed
        # We'll compute this separately
        fragmentation_penalty = self._compute_fragmentation_penalty(context)
        total_score -= fragmentation_penalty * CPSolverConfig.FRAGMENTATION_PENALTY

        return total_score

    def _compute_fragmentation_penalty(self, context) -> float:
        """Compute fragmentation penalty: extra rooms each department occupies beyond minimum needed."""
        from collections import defaultdict

        # Count rooms each department appears in
        dept_room_count = defaultdict(int)
        for room in context.room_allocations:
            if room.used_capacity == 0:
                continue
            # Count unique departments in this room
            room_depts = set()
            for stream in room.streams.values():
                if stream.students:  # Only count if stream has students
                    room_depts.update(stream.departments)
            for dept in room_depts:
                dept_room_count[dept] += 1

        # For each department, penalty is (rooms_used - 1)
        # (first room is free, each additional room is fragmentation)
        penalty = 0
        for dept, room_count in dept_room_count.items():
            if room_count > 1:
                penalty += (room_count - 1)

        return penalty

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
                        # Find corresponding group and deallocate properly
                        for group in context.groups:
                            if student in group.students:
                                # Remove student from group and reset allocation
                                group.students.remove(student)
                                group.allocated_count = max(0, group.allocated_count - 1)
                                # Re-add to group's main student list
                                group.students.append(student)
                                # But mark that this student is no longer allocated to this room
                                # We'll handle this in the repair phase
                    stream.students.clear()

            # 4. Repair destroyed rooms using CP solver
            success = self.repair_operator.repair(context, destroyed_indices, time_limit=LNSConfig.REPAIR_TIME_LIMIT)

            if not success:
                # Rollback
                context.restore(snapshot)
                continue

            # 5. Evaluate new solution
            new_score = self._score_context(context)

            # 6. Check for duplicates (validation) - if invalid, reject and rollback
            from engine.validators.allocation_validator import AllocationValidator
            validator = AllocationValidator()
            validation_result = validator.validate(context)
            if not validation_result.success:
                # Repair produced invalid allocation (e.g., duplicates), reject and rollback
                context.restore(snapshot)
                continue

            # 7. Accept or reject based on score
            if new_score >= best_score + LNSConfig.ACCEPTANCE_THRESHOLD:
                best_score = new_score
            else:
                # Rollback
                context.restore(snapshot)

        return context
