from engine.models.allocation import Allocation
from engine.services.constraint_checker import ConstraintChecker


class PrimaryAllocator:

    def execute(self, context):
        checker = ConstraintChecker(context.conflict_graph)

        if not context.streams:
            for group in context.groups:
                context.remaining_pool.add(group)
            return

        groups = sorted(
            context.groups,
            key=lambda g: g.remaining_count,
            reverse=True,
        )

        for group in groups:
            # Place full stream batches (e.g. 15 students) into available streams
            while True:
                allocated = False

                for stream in context.streams:
                    stream_batch = stream.capacity
                    if group.remaining_count < stream_batch:
                        break

                    if not checker.can_allocate(group, stream, count_needed=stream_batch):
                        continue

                    self.allocate(group, stream)
                    allocated = True
                    break

                if not allocated:
                    break

            if group.remaining_count > 0:
                context.remaining_pool.add(group)

    def allocate(self, group, stream):
        count = stream.capacity
        students = group.allocate_students(count)

        allocation = Allocation(
            group=group,
            students=students,
            stream=stream.stream,
        )

        stream.room.add_allocation(allocation)