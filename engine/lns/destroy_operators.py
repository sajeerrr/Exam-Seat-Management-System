# engine/lns/destroy_operators.py

import random


class DestroyOperator:
    """Base class for LNS destroy operators."""
    def select_rooms(self, context, num_rooms=3) -> list[int]:
        raise NotImplementedError


class WorstRoomsDestroy(DestroyOperator):
    """Destroy rooms with lowest pattern score or lowest utilization."""
    def select_rooms(self, context, num_rooms=3) -> list[int]:
        room_scores = []
        for idx, room in enumerate(context.room_allocations):
            util = room.used_capacity / room.classroom.capacity if room.classroom.capacity else 0
            room_scores.append((idx, util))

        # Sort by utilization ascending (worst filled rooms first)
        room_scores.sort(key=lambda x: x[1])
        selected = [idx for idx, _ in room_scores[:num_rooms]]
        return selected


class RandomClusterDestroy(DestroyOperator):
    """Destroy a random contiguous block of rooms."""
    def select_rooms(self, context, num_rooms=3) -> list[int]:
        total_rooms = len(context.room_allocations)
        if total_rooms <= num_rooms:
            return list(range(total_rooms))

        start = random.randint(0, total_rooms - num_rooms)
        return list(range(start, start + num_rooms))


class DepartmentFocusDestroy(DestroyOperator):
    """Destroy all rooms containing a specific fragmented department."""
    def select_rooms(self, context, num_rooms=3) -> list[int]:
        # Find departments and room counts
        dept_rooms = {}
        for idx, room in enumerate(context.room_allocations):
            for dept in room.departments:
                dept_rooms.setdefault(dept, []).append(idx)

        # Find most fragmented department (appears in most rooms)
        if not dept_rooms:
            return list(range(min(num_rooms, len(context.room_allocations))))

        most_fragmented_dept = max(dept_rooms.keys(), key=lambda d: len(dept_rooms[d]))
        rooms = dept_rooms[most_fragmented_dept]

        if len(rooms) >= num_rooms:
            return rooms[:num_rooms]

        # Fill remaining slots with random rooms
        remaining = [i for i in range(len(context.room_allocations)) if i not in rooms]
        selected = rooms + random.sample(remaining, min(num_rooms - len(rooms), len(remaining)))
        return selected
