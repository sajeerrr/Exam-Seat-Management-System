from models.allocation import Allocation

STREAMS = ["A", "B", "C"]#three students in a bench


class PrimaryAllocator:

    def execute(self, context):

        room_index = 0

        for group in context.groups:

            while True:

                if room_index >= len(context.room_allocations):
                    raise Exception("Not enough classrooms available.")

                current_room = context.room_allocations[room_index]

                stream_size = current_room.stream_capacity 

                # Group cannot fill one complete stream
                if group.remaining_count < stream_size:
                    break

                # Room already has 3 streams
                if len(current_room.allocations) == 3:
                    room_index += 1
                    continue

                allocation = Allocation(
                    stream=STREAMS[len(current_room.allocations)],
                    group=group,
                    start_index=group.next_start_index,
                    end_index=group.next_start_index + stream_size - 1,
                    allocated_count=stream_size,
                )

                current_room.allocations.append(allocation)

                group.allocate(stream_size)

        # Build Remaining Pool
        for group in context.groups:
            context.remaining_pool.add(group)

        return context