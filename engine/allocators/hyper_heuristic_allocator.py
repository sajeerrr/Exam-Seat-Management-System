# engine/allocators/hyper_heuristic_allocator.py

import warnings
from engine.adaptive.adaptive_allocator import AdaptiveAllocationEngine
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.adaptive.pattern_optimizer import StreamPatternOptimizer
from engine.cp.cp_solver import CPSolver
from engine.lns.lns_engine import LNSEngine
from engine.validators.allocation_validator import AllocationValidator
from engine.allocators.sequential_allocator import SequentialAllocator


class HyperHeuristicAllocator:
    """Hybrid: Sequential Room Packing -> CP Solver -> Hyper-Heuristic -> LNS."""

    def __init__(self):
        self.sequential_allocator = SequentialAllocator()
        self.cp_solver = CPSolver()
        self.adaptive_engine = AdaptiveAllocationEngine()
        self.lns_engine = LNSEngine()
        self.pattern_optimizer = StreamPatternOptimizer()
        self.local_optimizer = LocalOptimizer()
        self.validator = AllocationValidator()

    def execute(self, context):
        # Phase 1: Sequential Room Packing (reliable constructive baseline)
        context = self.sequential_allocator.execute(context)

        # Check if complete; if not, try CP Solver fallback
        unallocated = sum(g.remaining_count for g in context.groups)
        if unallocated > 0:
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

        # Phase 2: Hyper-Heuristic Refinement & Pattern Optimization
        context = self.pattern_optimizer.optimize(context)
        context = self.local_optimizer.optimize(context)

        # Phase 3: LNS Optimization (optional/transactional)
        snapshot_lns = context.snapshot()
        try:
            context = self.lns_engine.optimize(context)
            res = self.validator.validate(context)
            if not res.success or sum(g.remaining_count for g in context.groups) > 0:
                context.restore(snapshot_lns)
        except Exception:
            context.restore(snapshot_lns)

        # Final Validation Check
        result = self.validator.validate(context)
        if not result.success or sum(g.remaining_count for g in context.groups) > 0:
            raise ValueError(f"ALLOCATION FAILED VALIDATION: {result.errors}")

        return context

