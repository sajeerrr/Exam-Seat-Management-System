class ConstraintChecker:

    def __init__(self, conflict_graph):

        self.conflict_graph = conflict_graph

    def can_allocate(self, group, stream):

        # Stream already occupied
        if stream.room.streams[stream.stream] is not None:
            return False

        # Capacity check
        if not stream.is_available:
            return False

        # Check conflicts inside the room
        for allocation in stream.room.allocations:

            existing_group = allocation.group

            if self.conflict_graph.has_conflict(
                group.department,
                existing_group.department,
            ):
                return False

        return True