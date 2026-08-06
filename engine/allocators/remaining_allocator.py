from engine.services.constraint_checker import ConstraintChecker
from engine.models.allocation import Allocation


class RemainingAllocator:

    def execute(self, context):
        checker_strict = ConstraintChecker(
            context.conflict_graph,
            allow_non_adjacent_same_subject=False,
        )
        checker_exception = ConstraintChecker(
            context.conflict_graph,
            allow_non_adjacent_same_subject=True,
        )

        for group in list(context.remaining_pool.groups):
            if group.remaining_count == 0:
                context.remaining_pool.remove(group)
                continue

            self.allocate_group_smart(
                group,
                context,
                checker_strict,
                checker_exception,
            )

    def allocate_group_smart(self, group, context, checker_strict, checker_exception):
        # Active rooms (rooms with allocations)
        active_rooms = [r for r in context.room_allocations if len(r.allocations) > 0]
        active_streams = [s for s in context.streams if s.room in active_rooms]

        # Pass 1: Active rooms + Strict rule
        stream = self.find_best_stream(group, active_streams, checker_strict)

        # Pass 2: Active rooms + Exception Fallback (Stream A & C same subject allowed)
        if stream is None:
            stream = self.find_best_stream(group, active_streams, checker_exception)

        # Pass 3: Inactive / New rooms + Strict rule
        if stream is None:
            inactive_rooms = [r for r in context.room_allocations if len(r.allocations) == 0]
            inactive_streams = [s for s in context.streams if s.room in inactive_rooms]
            stream = self.find_best_stream(group, inactive_streams, checker_strict)

        if stream is None:
            return

        students = group.allocate_students(group.remaining_count)

        allocation = Allocation(
            group=group,
            students=students,
            stream=stream.stream,
        )

        stream.room.add_allocation(allocation)
        context.remaining_pool.remove(group)

    def find_best_stream(self, group, streams, checker):
        best_stream = None
        minimum_waste = float("inf")

        for stream in streams:
            if not checker.can_allocate(group, stream, count_needed=group.remaining_count):
                continue

            waste = stream.remaining_capacity - group.remaining_count

            if waste < minimum_waste:
                minimum_waste = waste
                best_stream = stream

        return best_stream