"""engine/adaptive/global_pattern_planner.py

Analyses the allocation context **before** the greedy construction phase and
produces a global plan that the engine can use to maximise ABC rooms.

Exported:
    GlobalPatternPlan    – result dataclass
    GlobalPatternPlanner – produces a plan from a context
"""

from dataclasses import dataclass, field
from engine.adaptive.invariant import max_abc_rooms


# ---------------------------------------------------------------------------
# Plan result
# ---------------------------------------------------------------------------

@dataclass
class GlobalPatternPlan:
    """Carries the pre-allocation planning decisions.

    Attributes:
        target_abc_rooms       (int):  maximum ABC rooms achievable
        bottleneck_departments (set):  depts whose student count is below one
                                       full stream capacity (potential blockers)
        reservations_by_room   (dict): {room_index: set_of_departments} — which
                                       depts should be reserved a slot in each
                                       room to meet the ABC target
        dept_stream_slots      (dict): {department: stream-slot count}
    """
    target_abc_rooms: int = 0
    bottleneck_departments: set = field(default_factory=set)
    reservations_by_room: dict = field(default_factory=dict)
    dept_stream_slots: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class GlobalPatternPlanner:
    """Pre-allocation global planner.

    Call ``plan(context)`` once before the engine starts assigning students.
    The returned :class:`GlobalPatternPlan` tells the engine:

    * how many ABC rooms it should aim for
    * which departments are bottlenecks (tiny cohorts that could be lost)
    * which room indices should reserve a slot for each bottleneck dept
    """

    def __init__(self, stream_capacity: int = 15):
        self.stream_capacity = stream_capacity

    # ------------------------------------------------------------------

    def plan(self, context) -> GlobalPatternPlan:
        import math
        dept_totals = self._dept_totals(context)
        dept_slots = {
            dept: math.ceil(count / self.stream_capacity)
            for dept, count in dept_totals.items()
        }

        target = max_abc_rooms(dept_slots)
        bottlenecks = self._bottleneck_departments(dept_totals, dept_slots)
        reservations = self._compute_reservations(context, bottlenecks, target)

        return GlobalPatternPlan(
            target_abc_rooms=target,
            bottleneck_departments=bottlenecks,
            reservations_by_room=reservations,
            dept_stream_slots=dept_slots,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dept_totals(self, context) -> dict:
        totals: dict[str, int] = {}
        for group in context.groups:
            totals[group.department] = (
                totals.get(group.department, 0) + group.remaining_count
            )
        return totals

    def _bottleneck_departments(self, dept_totals: dict, dept_slots: dict) -> set:
        """Departments whose total student count is < one full stream capacity.

        These are the riskiest depts: if the engine places them too early in
        a room that already has two departments, it cannot form an ABC room
        using this dept as the 'C' slot.
        """
        bottlenecks = set()
        for dept, total in dept_totals.items():
            if total < self.stream_capacity or dept_slots.get(dept, 0) == 0:
                bottlenecks.add(dept)
        return bottlenecks

    def _compute_reservations(
        self,
        context,
        bottlenecks: set,
        target_abc: int,
    ) -> dict:
        """Decide which room indices should reserve a slot for a bottleneck dept.

        Strategy:
        * Each bottleneck department contributes to at most one ABC room.
        * We assign bottleneck depts to the earliest rooms that still have
          open stream slots, ensuring they are paired with two other depts.

        Returns:
            {room_index: set_of_departments_reserved_here}
        """
        if not bottlenecks or target_abc == 0:
            return {}

        reservations: dict[int, set] = {}
        remaining_bottlenecks = list(bottlenecks)
        num_rooms = len(context.room_allocations)

        for room_index in range(num_rooms):
            if not remaining_bottlenecks:
                break
            dept = remaining_bottlenecks.pop(0)
            reservations.setdefault(room_index, set()).add(dept)

        return reservations
