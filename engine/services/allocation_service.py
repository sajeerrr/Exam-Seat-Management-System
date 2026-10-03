from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
from engine.allocators.seat_generator import SeatGenerator


class AllocationService:

    def __init__(self):
        self.allocator = ConstrainedBestFitAllocator()
        self.seat_generator = SeatGenerator()

    def execute(self, context):
        from engine.adaptive.invariant import AbcInvariant
        if not getattr(context, "abc_invariant", None):
            capacity = context.room_allocations[0].classroom.column_capacity if context.room_allocations else 15
            context.abc_invariant = AbcInvariant(context, stream_capacity=capacity)

        # 1. Constrained Best-Fit Allocation pipeline pass
        context = self.allocator.execute(context)
        if context is None:
            raise ValueError(
                "ConstrainedBestFitAllocator.execute() returned None! It must return 'context'."
            )

        # 2. Generate Seats
        seat_plan = self.seat_generator.generate(context)

        # CRITICAL: Must return tuple (context, seat_plan)
        return context, seat_plan



