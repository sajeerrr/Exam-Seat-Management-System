from engine.allocators.primary_allocator import PrimaryAllocator
from engine.allocators.remaining_allocator import RemainingAllocator
from engine.validators.allocation_validator import AllocationValidator
from engine.allocators.seat_generator import SeatGenerator


class AllocationService:

    def execute(self, context):
        context.initialize_streams()
        PrimaryAllocator().execute(context)
        RemainingAllocator().execute(context)
        validation = AllocationValidator().validate(context)
        plan = SeatGenerator().execute(context)

        if not validation.success:
            raise Exception("\n".join(validation.errors))

        return context, plan