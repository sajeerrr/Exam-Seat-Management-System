from exam_seating_engine.models.remaining_pool import RemainingPool

class PrimaryAllocator:

    def allocate(self, groups, classrooms):
        room_allocations = []
        remaining_pool = RemainingPool()

        return room_allocations, remaining_pool