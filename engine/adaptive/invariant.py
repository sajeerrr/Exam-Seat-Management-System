"""engine/adaptive/invariant.py

Provides:
    max_abc_rooms(dept_counts)  - theoretical upper bound on ABC rooms
    AbcInvariant                - guards the engine against ABA/non-ABC allocations
"""


def max_abc_rooms(dept_counts: dict) -> int:
    """Return the maximum number of ABC rooms achievable.

    An ABC room requires one full stream-slot from each of three distinct
    departments.  The bottleneck is the rarest department.

    Args:
        dept_counts: mapping of department → number of stream slots available
                     (e.g. {"ME": 3, "CS": 3, "EC": 3} → 3 ABC rooms)

    Returns:
        0 if fewer than 3 departments are present, otherwise min of the
        three largest dept counts (i.e. min over all depts when ≥ 3 exist).
    """
    if len(dept_counts) < 3:
        return 0
    # Sort descending; with exactly 3+ depts the limiting factor is the smallest.
    sorted_counts = sorted(dept_counts.values(), reverse=True)
    # We need one slot per dept per room → limited by the smallest dept.
    return sorted_counts[2]  # third-largest = bottleneck when exactly 3


# ---------------------------------------------------------------------------


class AbcInvariant:
    """Ensures the engine never destroys ABC achievability.

    Created once before allocation starts.  The engine (or AllocationService)
    attaches it to the context as ``context.abc_invariant`` so that
    post-allocation checks can call ``invariant.holds(context)``.

    Attributes:
        target_abc   (int):  theoretical max ABC rooms from initial pool
        reserved_tail (dict): {group_id: count} – students that must be kept
                              back to fulfil a future ABC room
    """

    def __init__(self, context, stream_capacity: int = 15):
        import math
        self.stream_capacity = stream_capacity
        self.reserved_tail: dict = {}          # populated externally if needed

        # Count how many full or partial stream-slots each department can supply.
        dept_slots: dict[str, int] = {}
        for group in context.groups:
            slots = math.ceil(group.remaining_count / stream_capacity)
            dept_slots[group.department] = (
                dept_slots.get(group.department, 0) + slots
            )

        self.target_abc: int = max_abc_rooms(dept_slots)

    # ------------------------------------------------------------------
    # Gate: should the engine be allowed to make `candidate` allocation?
    # ------------------------------------------------------------------

    def allows(self, context, candidate) -> bool:
        """Return False if this candidate would violate the ABC invariant.

        Two checks:
        1. ABA rejection – if a single group/department appears in both
           stream A and stream C of the same room, it consumes two of the
           three stream slots for the same dept, making an ABC room
           impossible in that room.
        2. Reserved-tail check – if a group has a reserved tail, prevent
           any assignment that would consume more than
           (remaining_count − reserved) students from that group.
        """
        groups = {g.group_id: g for g in context.groups}

        # ── Check 1: reserved tail ──────────────────────────────────────
        from collections import defaultdict
        planned_by_group: dict[str, int] = defaultdict(int)
        for assignment in candidate.assignments:
            planned_by_group[assignment.group_id] += assignment.count

        for group_id, planned in planned_by_group.items():
            group = groups.get(group_id)
            if group is None:
                continue
            reserved = self.reserved_tail.get(group_id, 0)
            max_allocatable = group.remaining_count - reserved
            if planned > max_allocatable:
                return False

        # ── Check 2: ABA pattern rejection ─────────────────────────────
        dept_by_stream: dict[str, set] = {"A": set(), "B": set(), "C": set()}
        room = context.room_allocations[candidate.room_index]

        # Existing students in the room.
        for stream_name, slot in room.streams.items():
            dept_by_stream[stream_name].update(slot.departments)

        # Students that would be added.
        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if group:
                dept_by_stream[assignment.stream].add(group.department)

        # ABA: dept appears in both A and C (but not B alone — that is fine).
        a_depts = dept_by_stream["A"]
        c_depts = dept_by_stream["C"]
        if a_depts & c_depts:
            return False

        return True

    # ------------------------------------------------------------------
    # Post-allocation check
    # ------------------------------------------------------------------

    def holds(self, context) -> bool:
        """Return True if the final allocation achieved the target ABC count.

        We count rooms where all three streams have exactly one distinct
        department each and all three departments are different (pure ABC).
        """
        from engine.adaptive.pattern_optimizer import PatternDetector
        detector = PatternDetector()
        abc_achieved = sum(
            1
            for room in context.room_allocations
            if room.used_capacity > 0 and detector.detect(room) == "ABC"
        )
        return abc_achieved >= self.target_abc
