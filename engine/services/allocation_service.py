from engine.allocators.primary_allocator import PrimaryAllocator
from engine.allocators.remaining_allocator import RemainingAllocator
from engine.allocators.seat_generator import SeatGenerator


class AllocationService:

    def __init__(self):
        self.primary_allocator = PrimaryAllocator()
        self.remaining_allocator = RemainingAllocator()
        self.seat_generator = SeatGenerator()

    def execute(self, context):
        # 1. Primary Pass
        context = self.primary_allocator.execute(context)
        if context is None:
            raise ValueError(
                "PrimaryAllocator.execute() returned None! It must return 'context'."
            )

        # 2. Remaining Pass
        context = self.remaining_allocator.execute(context)
        if context is None:
            raise ValueError(
                "RemainingAllocator.execute() returned None! It must return 'context'."
            )

        # 3. Generate Seats
        seat_plan = self.seat_generator.generate(context)

        # CRITICAL: Must return tuple (context, seat_plan)
        return context, seat_plan