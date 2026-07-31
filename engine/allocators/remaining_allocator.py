from engine.services.constraint_checker import ConstraintChecker
from engine.models.allocation import Allocation


class RemainingAllocator:

    def execute(self, context):
        checker = ConstraintChecker(
            context.conflict_graph
        )

        for group in list(context.remaining_pool.groups):

            self.allocate_group(
                group,
                context,
                checker,
            )

    def find_best_stream(self,group,context,checker,):
        best_stream = None
        minimum_waste = float("inf")

        for stream in context.streams:

            if not checker.can_allocate(group, stream):
                continue

            if stream.remaining_capacity < group.remaining_count:
                continue

            waste = (
                stream.remaining_capacity
                - group.remaining_count
            )

            if waste < minimum_waste:

                minimum_waste = waste
                best_stream = stream

        return best_stream


    def allocate_group(self,group,context,checker,):
        stream = self.find_best_stream(
            group,
            context,
            checker,
        )

        if stream is None:
            return

        students = group.allocate_students(
            group.remaining_count
        )

        allocation = Allocation(
            group=group,
            students=students,
            stream=stream.stream,
        )

        stream.room.add_allocation(allocation)
        context.remaining_pool.remove(group)