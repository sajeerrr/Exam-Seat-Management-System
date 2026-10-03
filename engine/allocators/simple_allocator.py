# engine/allocators/simple_allocator.py

from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.validators.allocation_validator import AllocationValidator
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.cp.cp_solver import CPSolver

class SimpleAllocator:
    """
    Simplified Core Allocation Pipeline:
    1. Sequential Room Allocator (Primary: official room order, greedy filling, hard constraints)
    2. Remainder Balancer / Local Optimizer (Transactional cleanup of tiny fragments and remainder consolidation)
    3. CP-SAT Fallback (Optional fallback only if sequential allocation fails)
    4. Strict Final Validation
    """

    def __init__(self):
        self.validator = AllocationValidator()
        self.local_optimizer = LocalOptimizer()
        self.cp_solver = CPSolver()

    def execute(self, context: AllocationContext) -> AllocationContext:
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        # 1. Sort groups by remaining count descending (deterministic priority)
        groups = sorted(
            [g for g in context.groups if g.remaining_count > 0],
            key=lambda g: (-g.remaining_count, g.department, g.subject_code)
        )

        room_allocations = context.room_allocations
        active_room_idx = 0

        # 2. Sequential Room Allocation (official room order, maximum practical filling)
        for group in groups:
            while group.remaining_count > 0:
                if active_room_idx >= len(room_allocations):
                    break

                room = room_allocations[active_room_idx]

                # Check if room can accept department
                if not room.can_add_department(group.department, is_fallback_pass=True):
                    active_room_idx += 1
                    continue

                allocated_in_room = False
                for stream_name in ["A", "B", "C"]:
                    if group.remaining_count <= 0:
                        break
                    stream = room.get_stream(stream_name)
                    if not stream or stream.remaining_capacity <= 0:
                        continue

                    if not room.can_seat_subject(stream_name, group.subject_code, group.department, group.subject_name):
                        continue

                    take = min(stream.remaining_capacity, group.remaining_count)
                    if take > 0:
                        room.assign_to_stream(stream_name, group, take)
                        allocated_in_room = True

                # Advance room pointer if current room is full or blocked by subject conflicts
                room_full_or_blocked = all(
                    s.remaining_capacity == 0 or not room.can_seat_subject(name, group.subject_code, group.department, group.subject_name)
                    for name, s in room.streams.items()
                )
                if room.used_capacity >= room.classroom.capacity or not allocated_in_room or room_full_or_blocked:
                    active_room_idx += 1

        context.remaining_pool = RemainingPool(context.groups)

        # 3. Check intermediate validity; if incomplete or invalid, try CP-SAT fallback
        val_result = self.validator.validate(context)
        unallocated_sum = sum(g.remaining_count for g in context.groups)

        if not val_result.success or unallocated_sum > 0:
            # Snapshot before fallback
            snapshot = context.snapshot()
            cp_context = self.cp_solver.solve(context.groups, context.room_allocations)
            if cp_context is not None:
                cp_val = self.validator.validate(cp_context)
                cp_unalloc = sum(g.remaining_count for g in cp_context.groups)
                if cp_val.success and cp_unalloc == 0:
                    cp_context.abc_invariant = getattr(context, "abc_invariant", None)
                    context = cp_context
                else:
                    context.restore(snapshot)
            else:
                context.restore(snapshot)

        # 4. Remainder Balancing & Fragment Consolidation (Transactional Local Optimizer)
        snapshot_before_balance = context.snapshot()
        try:
            context = self.local_optimizer.optimize(context)
            bal_result = self.validator.validate(context)
            if not bal_result.success or sum(g.remaining_count for g in context.groups) > 0:
                context.restore(snapshot_before_balance)
        except Exception:
            context.restore(snapshot_before_balance)

        # 5. Final Strict Validation
        final_validation = self.validator.validate(context)
        if not final_validation.success or sum(g.remaining_count for g in context.groups) > 0:
            context.restore(snapshot_before_balance)
            final_validation = self.validator.validate(context)

        if not final_validation.success or sum(g.remaining_count for g in context.groups) > 0:
            raise ValueError(f"ALLOCATION FAILED VALIDATION: {final_validation.errors}")

        return context

