class RemainingAllocator:

    def execute(self, context):
        active_groups = [g for g in context.groups if g.remaining_count > 0]
        if not active_groups:
            return context

        # Pack leftovers into any partially filled active rooms
        for room_alloc in context.room_allocations:
            if room_alloc.used_capacity == 0:
                continue

            for stream_name in ["A", "B", "C"]:
                stream = room_alloc.get_stream(stream_name)
                if not stream or stream.remaining_capacity == 0:
                    continue

                for group in active_groups:
                    if group.remaining_count == 0:
                        continue

                    if not room_alloc.can_add_department(
                        group.department, is_fallback_pass=True
                    ):
                        continue

                    if not room_alloc.can_seat_subject(
                        stream_name, group.subject_code
                    ):
                        continue

                    take = min(stream.remaining_capacity, group.remaining_count)
                    room_alloc.assign_to_stream(stream_name, group, take)

        return context