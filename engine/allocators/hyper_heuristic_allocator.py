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
        # Phase 1: CP Solver (with Sequential Room Packing fallback)
        cp_context = self.cp_solver.solve(context.groups, context.room_allocations)

        if cp_context is not None:
            cp_context.abc_invariant = getattr(context, "abc_invariant", None)
            context = cp_context
        else:
            context = self.sequential_allocator.execute(context)

        # Phase 2: Hyper-Heuristic Refinement & Pattern Optimization
        context = self.pattern_optimizer.optimize(context)
        context = self.local_optimizer.optimize(context)

        # Phase 3: LNS Optimization
        context = self.lns_engine.optimize(context)

        # Final Validation Check (warnings only)
        result = self.validator.validate(context)
        if not result.success:
            warnings.warn(f"Final hybrid allocation validation errors: {result.errors}")

        return context
