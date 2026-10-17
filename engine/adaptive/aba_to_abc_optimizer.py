# engine/adaptive/aba_to_abc_optimizer.py
"""
ABA-to-ABC Stream Pair Optimizer.

Transforms ABA room allocations into pure ABC room allocations by identifying
complementary room pairs and swapping streams (Stream C, Stream A, or Stream B)
to break repeated department patterns while strictly preserving capacity,
seat adjacency, and department limit constraints.
"""

import logging
from typing import List, Tuple, Optional, Set
from engine.context.allocation_context import AllocationContext
from engine.models.room_allocation import RoomAllocation, StreamSlot, subject_conflict_key
from engine.validators.allocation_validator import AllocationValidator
from engine.config import AllocationLimits

logger = logging.getLogger(__name__)


class ABAToABCOptimizer:
    """
    Global stream swap optimizer that converts ABA allocations to ABC allocations.
    """

    def __init__(self, max_passes: int = 20):
        self.max_passes = max_passes
        self.validator = AllocationValidator()

    def optimize(self, context: AllocationContext) -> AllocationContext:
        """
        Executes multi-pass global stream swaps to maximize pure ABC rooms
        and eliminate ABA room configurations.
        """
        active_rooms = [r for r in context.room_allocations if r.used_capacity > 0]
        if len(active_rooms) < 2:
            return context

        snapshot_start = context.snapshot()
        try:
            # Pass 1: Direct Stream C swaps between ABA pairs
            self._swap_aba_stream_c_pairs(active_rooms)

            # Pass 2: Multi-stream swaps (Stream A, B, C) across all non-ABC rooms
            self._swap_multi_stream_candidates(active_rooms)

            # Pass 3: Final validation check (hard constraints: conflicts, room capacity, max depts)
            val = self.validator.validate(context)
            hard_errors = [e for e in val.errors if "unallocated student(s)" not in e]
            if hard_errors:
                logger.warning(f"ABAToABCOptimizer validation failed: {hard_errors}. Restoring snapshot.")
                context.restore(snapshot_start)
                return context

            return context
        except Exception as ex:
            logger.warning(f"ABAToABCOptimizer exception: {ex}. Restoring snapshot.")
            context.restore(snapshot_start)
            return context

    def _is_abc_room(self, room: RoomAllocation) -> bool:
        """A room is ABC iff Streams A, B, C each have students, have distinct departments, and no adjacent conflicts."""
        s_a = room.get_stream("A")
        s_b = room.get_stream("B")
        s_c = room.get_stream("C")
        if not s_a or not s_b or not s_c:
            return False
        if not s_a.students or not s_b.students or not s_c.students:
            return False
        
        depts_a = s_a.departments
        depts_b = s_b.departments
        depts_c = s_c.departments

        if len(depts_a) != 1 or len(depts_b) != 1 or len(depts_c) != 1:
            # Has mixed streams or empty
            return len(room.departments) >= 3 and not (depts_a.intersection(depts_b) or depts_b.intersection(depts_c))

        dept_a = next(iter(depts_a))
        dept_b = next(iter(depts_b))
        dept_c = next(iter(depts_c))

        return dept_a != dept_b and dept_b != dept_c and dept_a != dept_c

    def _is_aba_room(self, room: RoomAllocation) -> bool:
        """A room is ABA if Stream A and Stream C share the same department and Stream B is different."""
        s_a = room.get_stream("A")
        s_b = room.get_stream("B")
        s_c = room.get_stream("C")
        if not s_a or not s_b or not s_c or not s_a.students or not s_b.students or not s_c.students:
            return False

        depts_a = s_a.departments
        depts_c = s_c.departments
        return bool(depts_a.intersection(depts_c))

    def _is_valid_room(self, room: RoomAllocation) -> bool:
        """Checks subject conflict key adjacency and department limit."""
        s_a = room.get_stream("A")
        s_b = room.get_stream("B")
        s_c = room.get_stream("C")

        if s_a and s_b and s_a.students and s_b.students:
            if s_a.subject_codes.intersection(s_b.subject_codes):
                return False
        if s_b and s_c and s_b.students and s_c.students:
            if s_b.subject_codes.intersection(s_c.subject_codes):
                return False

        max_depts = getattr(AllocationLimits, "MAX_DEPARTMENTS_NORMAL", 3)
        if len(room.departments) > max_depts:
            return False

        return True

    def _swap_aba_stream_c_pairs(self, rooms: List[RoomAllocation]) -> None:
        """
        Pairs up ABA rooms and swaps Stream C between them whenever doing so
        turns both rooms (or at least one without degrading the other) into ABC.
        """
        for _ in range(self.max_passes):
            improved = False
            for i in range(len(rooms)):
                for j in range(i + 1, len(rooms)):
                    r1, r2 = rooms[i], rooms[j]
                    s1 = r1.get_stream("C")
                    s2 = r2.get_stream("C")
                    if not s1 or not s2 or not s1.students or not s2.students:
                        continue
                    if len(s1.students) != len(s2.students):
                        continue

                    r1_aba = self._is_aba_room(r1)
                    r2_aba = self._is_aba_room(r2)
                    if not (r1_aba or r2_aba):
                        continue

                    # Evaluate before score
                    score_before = (2 if self._is_abc_room(r1) else (0 if r1_aba else 1)) + \
                                   (2 if self._is_abc_room(r2) else (0 if r2_aba else 1))

                    # Perform trial swap
                    s1.students, s2.students = s2.students, s1.students

                    if self._is_valid_room(r1) and self._is_valid_room(r2):
                        new_r1_aba = self._is_aba_room(r1)
                        new_r2_aba = self._is_aba_room(r2)
                        score_after = (2 if self._is_abc_room(r1) else (0 if new_r1_aba else 1)) + \
                                      (2 if self._is_abc_room(r2) else (0 if new_r2_aba else 1))

                        if score_after > score_before:
                            improved = True
                            continue

                    # Revert swap
                    s1.students, s2.students = s2.students, s1.students

            if not improved:
                break

    def _swap_multi_stream_candidates(self, rooms: List[RoomAllocation]) -> None:
        """
        Tries swapping Stream A, B, or C between any rooms where at least one room is not ABC.
        """
        for _ in range(self.max_passes):
            improved = False
            for i in range(len(rooms)):
                for j in range(len(rooms)):
                    if i == j:
                        continue
                    r1, r2 = rooms[i], rooms[j]
                    if self._is_abc_room(r1) and self._is_abc_room(r2):
                        continue

                    for stream_name in ("C", "A", "B"):
                        s1 = r1.get_stream(stream_name)
                        s2 = r2.get_stream(stream_name)
                        if not s1 or not s2 or not s1.students or not s2.students:
                            continue
                        if len(s1.students) != len(s2.students):
                            continue
                        if s1.departments == s2.departments:
                            continue

                        score_before = (2 if self._is_abc_room(r1) else 0) + \
                                       (2 if self._is_abc_room(r2) else 0)

                        s1.students, s2.students = s2.students, s1.students

                        if self._is_valid_room(r1) and self._is_valid_room(r2):
                            score_after = (2 if self._is_abc_room(r1) else 0) + \
                                          (2 if self._is_abc_room(r2) else 0)

                            if score_after > score_before:
                                improved = True
                                break

                        # Revert
                        s1.students, s2.students = s2.students, s1.students

                    if improved:
                        break

            if not improved:
                break

