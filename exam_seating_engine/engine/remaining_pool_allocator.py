from ..models.allocation import Allocation

STREAMS = ["A", "B", "C"]


class RemainingPoolAllocator:

    def execute(self, context):
        groups = context.remaining_pool.groups #take all remaining group
        groups.sort(
            key=lambda group: group.remaining_count,
            reverse=True
        )

        for group in groups: 
            while group.remaining_count > 0:
                room = self._find_best_room( #find a room
                    context.room_allocations,
                    group
                )

                if room is None:
                    raise Exception(
                        f"No room available for {group.group_id}"
                    )

                self._allocate(room, group) #every iteration find the best room and allocate


    def _find_best_room(self, room_allocations, group):
        best_room = None
        best_score = -1

        for room in room_allocations: #check every room
            if not self._can_allocate(room, group): #skip the invalid rooms
                continue
            score = self._calculate_score(room, group)
            if score > best_score:
                best_score = score
                best_room = room

        return best_room
    
    def _can_allocate(self, room, group): #this check as can this group be placed in a room
        if room.remaining_capacity <= 0: # Room is completely full
            return False
        
        if room.get_empty_stream() is None: # No free stream available
            return False
        
        if room.has_group(group.group_id): # Same department already exists in this room
            return False

        # Future: department/subject conflict
        # if self._has_conflict(room, group):
        #     return False

        return True

    def _calculate_score(self, room, group):
        PARTIAL_ROOM_BONUS = 50
        FULL_FIT_BONUS = 100
        score = 0
        # Prefer rooms that already have students
        if room.classroom.capacity > room.remaining_capacity:
            score += PARTIAL_ROOM_BONUS
        # Prefer rooms that can fit the entire group
        if room.column_capacity >= group.remaining_count:
            score += FULL_FIT_BONUS
        # Prefer rooms with less unused space after allocation
        allocated = min(
            room.column_capacity,
            group.remaining_count
        )

        # wasted = room.remaining_capacity - allocated
        wasted = room.column_capacity - allocated
        score -= wasted
        return score

    def _allocate(self, room, group):
        stream = room.get_empty_stream()
        if stream is None:
            raise Exception("No empty stream available.")

        allocated_count = min(
            room.column_capacity,
            group.remaining_count
        )

        # allocation = Allocation(
        #     group=group,
        #     stream=stream,
        #     allocated_count=allocated_count,
        # )

        allocation = Allocation(
            group=group,
            stream=stream,
            start_index=0,
            end_index=0,
            allocated_count=allocated_count,
        )

        room.add_allocation(allocation)
        # group.remaining_count -= allocated_count
        group.allocate(allocated_count)