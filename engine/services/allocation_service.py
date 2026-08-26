from engine.allocators.hyper_heuristic_allocator import HyperHeuristicAllocator
from engine.allocators.seat_generator import SeatGenerator


class AllocationService:

    def __init__(self):
        self.allocator = HyperHeuristicAllocator()
        self.seat_generator = SeatGenerator()

    def execute(self, context):
        # 1. Hyper-heuristic allocation pass
        context = self.allocator.execute(context)
        if context is None:
            raise ValueError(
                "HyperHeuristicAllocator.execute() returned None! It must return 'context'."
            )

        # 2. Generate Seats
        seat_plan = self.seat_generator.generate(context)

        # CRITICAL: Must return tuple (context, seat_plan)
        return context, seat_plan
