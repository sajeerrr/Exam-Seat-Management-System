class ConstraintChecker:

    def __init__(self, conflict_graph, allow_non_adjacent_same_subject: bool = False):
        self.conflict_graph = conflict_graph
        self.allow_non_adjacent_same_subject = allow_non_adjacent_same_subject

    def can_allocate(self, group, stream, count_needed: int = None) -> bool:
        # Default needed count is the group's remaining count if not specified
        needed = count_needed if count_needed is not None else group.remaining_count

        # Rule 1: Capacity check against needed batch size
        if stream.remaining_capacity < needed:
            return False

        # Inspect existing allocations already placed in this room
        for existing_allocation in stream.room.allocations:
            existing_group = existing_allocation.group
            existing_stream = existing_allocation.stream
            target_stream = stream.stream

            # Rule 2: Same subject / department handling
            if (
                existing_group.subject_code == group.subject_code
                or existing_group.department == group.department
            ):
                if existing_stream == target_stream:
                    # Same stream column -> allowed
                    continue
                else:
                    # Different stream column in same room
                    if not self.allow_non_adjacent_same_subject:
                        return False

                    # Exception Case: Allow same subject ONLY between Stream A and Stream C
                    is_non_adjacent = (existing_stream == "A" and target_stream == "C") or (
                        existing_stream == "C" and target_stream == "A"
                    )
                    if not is_non_adjacent:
                        return False  # Stream B cannot share a subject with A or C

            # Rule 3: External conflict graph
            if self.conflict_graph.has_conflict(
                group.department, existing_group.department
            ):
                return False

        return True