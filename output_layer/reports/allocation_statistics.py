# output_layer/reports/allocation_statistics.py
"""
Computes allocation statistics from a finished context.
"""

import logging
from engine.context.allocation_context import AllocationContext

logger = logging.getLogger(__name__)


class AllocationStatistics:
    """
    Usage
    -----
    stats = AllocationStatistics().compute(context, students_loaded=423)
    stats.print_summary()
    """

    def compute(self, context: AllocationContext, students_loaded: int) -> "Statistics":

        allocated = sum(
            a.allocated_count
            for room in context.room_allocations
            for a in room.allocations
        )

        remaining = sum(
            g.remaining_count for g in context.remaining_pool.groups
        )

        seen: set[str] = set()
        duplicates = 0
        for room in context.room_allocations:
            for allocation in room.allocations:
                for student in allocation.students:
                    if student.register_no in seen:
                        duplicates += 1
                    seen.add(student.register_no)

        rooms_used  = sum(1 for room in context.room_allocations if room.allocations)
        rooms_total = len(context.room_allocations)

        total_seats = sum(room.classroom.capacity for room in context.room_allocations)
        avg_util    = (allocated / total_seats * 100) if total_seats else 0.0

        stats = Statistics(
            students_loaded     = students_loaded,
            allocated           = allocated,
            remaining           = remaining,
            duplicates          = duplicates,
            rooms_used          = rooms_used,
            rooms_total         = rooms_total,
            average_utilization = round(avg_util, 1),
        )

        logger.info(
            "Statistics: loaded=%d  allocated=%d  remaining=%d  "
            "duplicates=%d  rooms=%d/%d  utilization=%.1f%%",
            students_loaded, allocated, remaining,
            duplicates, rooms_used, rooms_total, avg_util,
        )

        return stats


class Statistics:
    """Plain data container with a pretty-print method."""

    def __init__(
        self,
        students_loaded: int,
        allocated: int,
        remaining: int,
        duplicates: int,
        rooms_used: int,
        rooms_total: int,
        average_utilization: float,
    ):
        self.students_loaded     = students_loaded
        self.allocated           = allocated
        self.remaining           = remaining
        self.duplicates          = duplicates
        self.rooms_used          = rooms_used
        self.rooms_total         = rooms_total
        self.average_utilization = average_utilization

    def as_dict(self) -> dict:
        return self.__dict__.copy()

    def print_summary(self) -> None:
        print("=" * 40)
        print("  ALLOCATION STATISTICS")
        print("=" * 40)
        print(f"  Students Loaded     : {self.students_loaded}")
        print(f"  Allocated           : {self.allocated}")
        print(f"  Remaining           : {self.remaining}")
        print(f"  Duplicates          : {self.duplicates}")
        print(f"  Rooms Used          : {self.rooms_used} / {self.rooms_total}")
        print(f"  Avg Utilization     : {self.average_utilization}%")
        print("=" * 40)
