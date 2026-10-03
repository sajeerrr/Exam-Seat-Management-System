# engine/allocators/sequential_allocator.py

from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.validators.allocation_validator import AllocationValidator

class SequentialAllocator:
    """
    Deterministic sequential room-packing allocator.
    - Official room order
    - Maximum filling (greedily fill rooms to capacity)
    - Remainder balancing / cleaning
    - Hard constraint enforcement (capacity, subject conflicts)
    """

    def __init__(self):
        self.validator = AllocationValidator()

    def execute(self, context: AllocationContext) -> AllocationContext:
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        # Sort groups by remaining count descending
        groups = sorted([g for g in context.groups if g.remaining_count > 0], key=lambda g: (-g.remaining_count, g.department, g.subject_code))

        room_allocations = context.room_allocations

        active_room_idx = 0
        for group in groups:
            while group.remaining_count > 0:
                if active_room_idx >= len(room_allocations):
                    break

                room = room_allocations[active_room_idx]

                # Check if room can accept department
                if not room.can_add_department(group.department, is_fallback_pass=True):
                    active_room_idx += 1
                    continue

                allocated_in_room = False
                for stream_name in ["A", "B", "C"]:
                    if group.remaining_count <= 0:
                        break
                    stream = room.get_stream(stream_name)
                    if not stream or stream.remaining_capacity <= 0:
                        continue

                    if not room.can_seat_subject(stream_name, group.subject_code, group.department, group.subject_name):
                        continue

                    take = min(stream.remaining_capacity, group.remaining_count)
                    if take > 0:
                        room.assign_to_stream(stream_name, group, take)
                        allocated_in_room = True

                # If room is full across all streams, move to next room
                if room.used_capacity >= room.classroom.capacity:
                    active_room_idx += 1
                elif not allocated_in_room:
                    # If we couldn't allocate in this room due to subject conflicts, try next room
                    active_room_idx += 1
                else:
                    # Room still has space and students were allocated, but group still has students remaining
                    # If current room streams are all full or conflicted, move to next room
                    room_full_or_blocked = all(
                        s.remaining_capacity == 0 or not room.can_seat_subject(name, group.subject_code, group.department, group.subject_name)
                        for name, s in room.streams.items()
                    )
                    if room_full_or_blocked:
                        active_room_idx += 1

        context.remaining_pool = RemainingPool(context.groups)
        return context
