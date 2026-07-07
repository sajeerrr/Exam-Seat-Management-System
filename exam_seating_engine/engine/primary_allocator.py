from models.allocation import Allocation


class PrimaryAllocator:

    def execute(self, context):
        room_index = 0
        current_room = context.room_allocations[room_index]
        for group in context.groups:
            pass
        return context