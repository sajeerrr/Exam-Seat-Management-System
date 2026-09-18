from dataclasses import dataclass
from engine.context.allocation_context import AllocationContext


@dataclass
class AllocationState:
    context: AllocationContext
    largest_group: int
    smallest_group: int
    average_group_size: float
    active_groups: int
    remaining_students: int
    remaining_rooms: int