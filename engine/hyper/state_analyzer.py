from engine.hyper.allocation_state import AllocationState


class StateAnalyzer:

    def analyze(self, context):
        groups = [
            g
            for g in context.groups
            if g.remaining_count > 0
        ]

        strengths = [
            g.remaining_count
            for g in groups
        ]

        largest = max(strengths) if strengths else 0
        smallest = min(strengths) if strengths else 0
        average = sum(strengths) / len(strengths) if strengths else 0
        students = sum(strengths)
        remaining_rooms = len(
            [
                r
                for r in context.room_allocations
                if r.used_capacity < r.classroom.capacity
            ]
        )

        return AllocationState(
            context=context,
            largest_group=largest,
            smallest_group=smallest,
            average_group_size=average,
            active_groups=len(groups),
            remaining_students=students,
            remaining_rooms=remaining_rooms,
        )
