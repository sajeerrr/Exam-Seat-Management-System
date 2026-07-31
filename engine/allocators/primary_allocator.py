from engine.models.allocation import Allocation
from engine.services.constraint_checker import ConstraintChecker


class PrimaryAllocator:

    def execute(self, context):
        checker = ConstraintChecker(context.conflict_graph)

        groups = sorted(
            context.groups,
            key=lambda g: g.remaining_count,
            reverse=True,
        )

        for group in groups:
            while group.remaining_count >= context.streams[0].capacity:
                allocated = False

                for stream in context.streams:
                    if not checker.can_allocate(group, stream):
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