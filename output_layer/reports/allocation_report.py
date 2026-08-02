# output_layer/reports/allocation_report.py
"""
Generates a human-readable allocation report from a finished AllocationContext.
"""

import logging
from engine.context.allocation_context import AllocationContext

logger = logging.getLogger(__name__)

_LINE = "=" * 55
_DASH = "-" * 40



class AllocationReport:
    """
    Usage
    -----
    report = AllocationReport().generate(context)
    print(report)
    """

    def generate(self, context: AllocationContext) -> str:
        lines: list[str] = []
        lines.append("=" * 55)
        lines.append("  EXAM SEAT ALLOCATION REPORT")
        lines.append("=" * 55)

        total_allocated = 0

        for room in context.room_allocations:
            lines.append(f"\n  Room {room.classroom.room_no}")
            lines.append(f"  {_DASH}")

            if not room.allocations:
                lines.append("    (no allocations)")
            else:
                for allocation in room.allocations:
                    dept  = allocation.group.department
                    count = allocation.allocated_count
                    stream = allocation.stream
                    subj  = allocation.group.subject_code
                    lines.append(
                        f"    Stream {stream}  ->  {dept:5s}  {subj:12s}  ({count} students)"
                    )
                    total_allocated += count

            lines.append(f"    Remaining capacity: {room.remaining_capacity}")

        if not context.remaining_pool.is_empty():
            lines.append("\n" + "=" * 55)
            lines.append("  REMAINING POOL (not yet allocated)")
            lines.append("=" * 55)
            for group in context.remaining_pool.groups:
                lines.append(
                    f"    {group.department:5s}  {group.subject_code:12s}  "
                    f"({group.remaining_count} students remaining)"
                )

        lines.append("\n" + "=" * 55)
        lines.append(f"  Total allocated : {total_allocated}")
        lines.append("=" * 55)

        report = "\n".join(lines)
        logger.info("Allocation report generated (%d rooms)", len(context.room_allocations))
        return report
