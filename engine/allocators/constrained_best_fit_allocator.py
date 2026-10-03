# engine/allocators/constrained_best_fit_allocator.py

from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.validators.allocation_validator import AllocationValidator
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.cp.cp_solver import CPSolver

class ConstrainedBestFitAllocator:
    """
    Core Allocation Pipeline:
    1. Constrained Best-Fit Allocation with Department Consolidation & Practical Room Filling
    2. Remainder Balancing & Fragment Consolidation (Transactional Local Optimizer)
    3. Optional CP-SAT Fallback (Emergency only if unallocated students remain)
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

        room_allocations = context.room_allocations
        active_room_idx = 0

        # Process rooms in exact official order from resources/Class.xlsx
        for room_idx, room in enumerate(room_allocations):
            if all(g.remaining_count == 0 for g in context.groups):
                break

            # Continue filling this room until practically full or no valid groups can be seated
            room_active = True
            while room_active and room.used_capacity < room.classroom.capacity:
                # Find best candidate group according to priority:
                # 1. Valid under hard constraints & stream/subject rules
                # 2. Continues a department already present in the room (Department Consolidation)
                # 3. Maximizes practical room utilization (largest remaining group that fits)
                best_group = None
                best_stream_name = None
                best_take = 0

                # Get available active groups with remaining students
                available_groups = [g for g in context.groups if g.remaining_count > 0]
                if not available_groups:
                    room_active = False
                    break

                # Sort candidates:
                # Priority A: Groups belonging to departments already present in this room
                # Priority B: Largest remaining count (practical filling)
                current_room_depts = room.departments

                def group_sort_key(g):
                    has_dept_match = 0 if (g.department in current_room_depts or not current_room_depts) else 1
                    return (has_dept_match, -g.remaining_count, g.department, g.subject_code)

                available_groups.sort(key=group_sort_key)

                allocated_in_iteration = False
                for group in available_groups:
                    # Check department limit for room
                    if not room.can_add_department(group.department, is_fallback_pass=True):
                        continue

                    # Try streams A, B, C
                    for stream_name in ["A", "B", "C"]:
                        stream = room.get_stream(stream_name)
                        if not stream or stream.remaining_capacity <= 0:
                            continue

                        # Check subject separation / hard rules
                        if not room.can_seat_subject(stream_name, group.subject_code, group.department, group.subject_name):
                            continue

                        take = min(stream.remaining_capacity, group.remaining_count)
                        if take > 0:
                            best_group = group
                            best_stream_name = stream_name
                            best_take = take
                            break
                    if best_group:
                        break

                if best_group and best_take > 0:
                    room.assign_to_stream(best_stream_name, best_group, best_take)
                    allocated_in_iteration = True
                else:
                    room_active = False

        context.remaining_pool = RemainingPool(context.groups)

        # Fallback if any students remain unallocated
        unallocated_sum = sum(g.remaining_count for g in context.groups)
        if unallocated_sum > 0:
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

        # Remainder Balancing & Fragment Consolidation (Transactional)
        snapshot_before_balance = context.snapshot()
        try:
            context = self.local_optimizer.optimize(context)
            bal_result = self.validator.validate(context)
            if not bal_result.success or sum(g.remaining_count for g in context.groups) > 0:
                context.restore(snapshot_before_balance)
        except Exception:
            context.restore(snapshot_before_balance)

        # Final Strict Validation
        final_validation = self.validator.validate(context)
        if not final_validation.success or sum(g.remaining_count for g in context.groups) > 0:
            raise ValueError(f"ALLOCATION FAILED VALIDATION: {final_validation.errors}")

        return context
