from ..models.allocation import Allocation

STREAMS = ["A", "B", "C"]


class PrimaryAllocator:

    def execute(self, context):

        # Create runtime state
        self.context = context
        self.room_index = 0
        self.group_index = 0

        # Active group for each stream
        self.active_groups = {
            "A": None,
            "B": None,
            "C": None,
        }
        self._initialize_streams()

        while (
            self.room_index < len(self.context.room_allocations)
            and self._has_active_groups()
        ):
            self._allocate_room()

        return self.context
    
    def _initialize_streams(self):
        for stream in STREAMS:
            if self.group_index < len(self.context.groups):
                self.active_groups[stream] = self.context.groups[self.group_index]
                self.group_index += 1
    
    def _has_active_groups(self):
        return any(
            group is not None
            for group in self.active_groups.values()
        )

    def _allocate_room(self):
        room = self.context.room_allocations[self.room_index]
        for stream in STREAMS:
            self._allocate_stream(room, stream)

        self.room_index += 1

    def _allocate_stream(self, room, stream):
        group = self.active_groups[stream]

        # No active group for this stream
        if group is None:
            return

        column_capacity = room.column_capacity

        if room.remaining_capacity < column_capacity:
            return

        # Current group cannot fill one complete column
        while True:
            if group is None:
                return

            if group.remaining_count >= column_capacity:
                break

            self._move_to_remaining_pool(group)
            self._load_next_group(stream)
            group = self.active_groups.get(stream)

        allocation = Allocation(
            stream=stream,
            group=group,
            start_index=group.next_start_index,
            end_index=group.next_start_index + column_capacity - 1,
            allocated_count=column_capacity,
        )

        room.streams[stream] = allocation
        room.allocations.append(allocation)
        group.allocate(column_capacity)

    def _load_next_group(self, stream):
        if self.group_index >= len(self.context.groups):
            self.active_groups[stream] = None
            return

        self.active_groups[stream] = self.context.groups[self.group_index]
        self.group_index += 1

    def _move_to_remaining_pool(self, group):
        if group.remaining_count > 0:
            self.context.remaining_pool.add(group)