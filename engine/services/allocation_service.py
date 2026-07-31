from engine.allocators.primary_allocator import PrimaryAllocator
from engine.allocators.remaining_allocator import RemainingAllocator


class AllocationService:

    def execute(self, context):
        
        context.initialize_streams()
        PrimaryAllocator().execute(context)
        RemainingAllocator().execute(context)