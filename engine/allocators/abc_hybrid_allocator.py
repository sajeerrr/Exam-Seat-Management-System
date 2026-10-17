# engine/allocators/abc_hybrid_allocator.py
"""
ABC-First, Consolidation-Aware Hybrid Allocator.

Architecture:
1. Pure ABC Block Placement:
   - Identifies full 15-student stream blocks across all departments.
   - Pairs triplets of distinct departments into Streams A, B, C of rooms.
   - Generates 100% pure ABC rooms (45 capacity, exactly 3 departments, 0 mixed streams).
2. Remainder Subproblem CP-SAT Solver:
   - Takes the fractional remainders and remaining rooms.
   - Solves the subproblem in <1 second with CP-SAT subject/department constraints.
   - Maximizes purity and ABC patterns while ensuring 0 unallocated students.
3. Fallback:
   - Full CP-SAT solver from clean initial snapshot if needed.
"""

import logging
from typing import List, Dict, Optional, Tuple
from ortools.sat.python import cp_model

from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation, subject_conflict_key
from engine.validators.allocation_validator import AllocationValidator
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.cp.cp_model_builder import CPModelBuilder
from engine.cp.cp_solver import CPSolver
from engine.config import AllocationLimits

logger = logging.getLogger(__name__)


class ABCHybridAllocator:
    """
    High-performance hybrid allocator prioritizing ABC patterns, stream purity,
    and minimal room fragmentation.
    """

    def __init__(self):
        self.validator = AllocationValidator()
        self.local_optimizer = LocalOptimizer()
        self.cp_solver = CPSolver()
        self.cp_builder = CPModelBuilder()

    def execute(self, context: AllocationContext, allow_unallocated: bool = False) -> AllocationContext:
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        initial_snapshot = context.snapshot()
        has_special = any(g.is_special_subject for g in context.groups)

        # For cohorts with special subjects (Elective/Minor/Honours with complex seat adjacency),
        # use CP-SAT or constrained best-fit.
        if has_special:
            cp_ctx = self.cp_solver.solve(context.groups, context.room_allocations)
            if cp_ctx is not None:
                val = self.validator.validate(cp_ctx)
                if val.success and sum(g.remaining_count for g in cp_ctx.groups) == 0:
                    return cp_ctx
            from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
            return ConstrainedBestFitAllocator().execute(context, allow_unallocated=allow_unallocated)

        # Stage 1 + 2: ABC-First Hybrid Execution
        try:
            success = self._run_abc_hybrid_pipeline(context)
            if success:
                val = self.validator.validate(context)
                if allow_unallocated:
                    val.errors = [e for e in val.errors if "unallocated student(s)" not in e]
                    val.success = (len(val.errors) == 0)

                if val.success and (allow_unallocated or sum(g.remaining_count for g in context.groups) == 0):
                    return context
        except Exception as ex:
            logger.warning(f"ABCHybridAllocator exception: {ex}")

        # Stage 3: Global CP-SAT Solver Fallback
        context.restore(initial_snapshot)
        cp_ctx = self.cp_solver.solve(context.groups, context.room_allocations)
        if cp_ctx is not None:
            cp_val = self.validator.validate(cp_ctx)
            if allow_unallocated:
                cp_val.errors = [e for e in cp_val.errors if "unallocated student(s)" not in e]
                cp_val.success = (len(cp_val.errors) == 0)
            if cp_val.success and (allow_unallocated or sum(g.remaining_count for g in cp_ctx.groups) == 0):
                return cp_ctx

        # Final Fallback
        context.restore(initial_snapshot)
        from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
        return ConstrainedBestFitAllocator().execute(context, allow_unallocated=allow_unallocated)

    def _run_abc_hybrid_pipeline(self, context: AllocationContext) -> bool:
        rooms = context.room_allocations
        if not rooms:
            return False

        stream_cap = rooms[0].streams["A"].capacity if rooms[0].streams.get("A") else 15
        groups = context.groups
        rem_groups = list(groups)

        def get_available_blocks():
            res = {}
            for g in rem_groups:
                if g.remaining_count >= stream_cap:
                    res.setdefault(g.department, []).append(g)
            return res

        # 1. Place pure ABC rooms using 15-student full blocks
        rooms_assigned = 0
        total_rooms = len(rooms)

        # We leave at least enough rooms for remaining fractional cohorts
        # Calculate how many rooms are needed for remainders:
        # Both by student count AND by distinct departments (max 3 depts per room)
        total_blocks = sum(g.remaining_count // stream_cap for g in rem_groups)
        total_students = sum(g.remaining_count for g in rem_groups)
        rem_students_total = sum(g.remaining_count % stream_cap for g in rem_groups)
        num_distinct_depts = len(set(g.department for g in rem_groups))
        max_depts_per_room = AllocationLimits.MAX_DEPARTMENTS_NORMAL
        min_rooms_for_depts = (num_distinct_depts + max_depts_per_room - 1) // max_depts_per_room
        min_rooms_for_capacity = max(1, (rem_students_total + 44) // 45) if rem_students_total > 0 else 0
        rooms_needed_for_rem = max(min_rooms_for_capacity, min_rooms_for_depts, 4)
        max_abc_rooms = min(max(0, total_rooms - rooms_needed_for_rem), total_blocks // 3)

        for r_idx in range(max_abc_rooms):
            avail = get_available_blocks()
            depts = sorted(avail.keys(), key=lambda d: sum(g.remaining_count for g in avail[d]), reverse=True)
            if len(depts) < 3:
                break

            d1, d2, d3 = depts[0], depts[1], depts[2]
            g1 = avail[d1][0]
            g2 = avail[d2][0]
            g3 = avail[d3][0]

            # Verify no adjacent subject conflict
            k1 = subject_conflict_key(g1.subject_code, g1.department, g1.subject_name)
            k2 = subject_conflict_key(g2.subject_code, g2.department, g2.subject_name)
            k3 = subject_conflict_key(g3.subject_code, g3.department, g3.subject_name)

            if k1 == k2 or k2 == k3:
                if k1 != k3 and k3 != k2:
                    g2, g3 = g3, g2
                else:
                    break

            r = rooms[r_idx]
            r.assign_to_stream("A", g1, stream_cap)
            r.assign_to_stream("B", g2, stream_cap)
            r.assign_to_stream("C", g3, stream_cap)
            rooms_assigned += 1

        # 2. Solve remainder subproblem for remaining rooms using CP-SAT
        active_rem_groups = [g for g in rem_groups if g.remaining_count > 0]
        unalloc_remaining = sum(g.remaining_count for g in active_rem_groups)

        if unalloc_remaining == 0:
            context.remaining_pool = RemainingPool(context.groups)
            from engine.adaptive.aba_to_abc_optimizer import ABAToABCOptimizer
            context = ABAToABCOptimizer().optimize(context)
            return True

        rem_rooms = rooms[rooms_assigned:]
        if not rem_rooms:
            return False

        # Build CP-SAT subproblem for remainder rooms
        model, assign = self.cp_builder.build(active_rem_groups, rem_rooms)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 4
        status = solver.Solve(model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for g_idx, group in enumerate(active_rem_groups):
                for local_r_idx, room in enumerate(rem_rooms):
                    for s_idx, s_name in enumerate(["A", "B", "C"]):
                        val = solver.Value(assign[(g_idx, local_r_idx, s_idx)])
                        if val > 0:
                            room.assign_to_stream(s_name, group, val)

            context.remaining_pool = RemainingPool(context.groups)
            from engine.adaptive.aba_to_abc_optimizer import ABAToABCOptimizer
            context = ABAToABCOptimizer().optimize(context)
            return True

        return False

