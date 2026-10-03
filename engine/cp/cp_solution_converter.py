# engine/cp/cp_solution_converter.py

from engine.context.allocation_context import AllocationContext


class CPSolutionConverter:
    """Converts CP solver output to AllocationContext with populated RoomAllocations."""

    def convert(self, solver, assign, groups, room_allocations) -> AllocationContext:
        # Clear any existing allocations in room streams
        for room in room_allocations:
            for stream in room.streams.values():
                stream.students.clear()

        # Reset group allocated counts
        for group in groups:
            group.allocated_count = 0

        # Assign students based on solution values
        streams_map = ["A", "B", "C"]
        for g_idx, group in enumerate(groups):
            for r_idx, room in enumerate(room_allocations):
                for s_idx, stream_name in enumerate(streams_map):
                    val = solver.Value(assign[(g_idx, r_idx, s_idx)])
                    if val > 0:
                        room.assign_to_stream(stream_name, group, val)

        # Build context
        from engine.models.remaining_pool import RemainingPool
        context = AllocationContext(
            groups=groups,
            room_allocations=room_allocations,
            remaining_pool=RemainingPool(groups)
        )
        return context
