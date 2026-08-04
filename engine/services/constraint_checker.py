# engine/services/constraint_checker.py
"""
ConstraintChecker — guards the allocation engine's placement decisions.

Rules applied (in order):
  1. Stream slot must be free (not already allocated).
  2. Stream must have remaining capacity.
  3. No two streams in the same room may have the same subject_code.
     This guarantees that Stream A, Stream B, Stream C always carry
     students writing *different* papers — so adjacent bench rows have
     different subjects and copying is impossible.
  4. Manual conflict-graph check (for any extra constraints added externally).
"""


class ConstraintChecker:

    def __init__(self, conflict_graph):
        self.conflict_graph = conflict_graph

    def can_allocate(self, group, stream) -> bool:
        # Rule 1: Stream slot already occupied
        if stream.room.streams[stream.stream] is not None:
            return False

        # Rule 2: No capacity left in this stream
        if not stream.is_available:
            return False

        # Inspect existing allocations already placed in this room
        for existing_allocation in stream.room.allocations:
            existing_group = existing_allocation.group

            # Rule 3: Same subject in this room → block
            # (CE A+B are now one merged group so this also catches
            #  any remaining same-subject situation)
            if existing_group.subject_code == group.subject_code:
                return False

            # Rule 4: External conflict graph
            if self.conflict_graph.has_conflict(
                group.department, existing_group.department
            ):
                return False

        return True