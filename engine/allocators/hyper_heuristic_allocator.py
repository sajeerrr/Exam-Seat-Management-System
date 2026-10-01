# engine/allocators/hyper_heuristic_allocator.py

import warnings
from engine.adaptive.adaptive_allocator import AdaptiveAllocationEngine
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.adaptive.pattern_optimizer import StreamPatternOptimizer
from engine.cp.cp_solver import CPSolver
from engine.lns.lns_engine import LNSEngine
from engine.validators.allocation_validator import AllocationValidator


class HyperHeuristicAllocator:
    """Hybrid: CP Solver -> Hyper-Heuristic -> LNS."""

    def __init__(self):
        self.cp_solver = CPSolver()
        self.adaptive_engine = AdaptiveAllocationEngine()
        self.lns_engine = LNSEngine()
        self.pattern_optimizer = StreamPatternOptimizer()
        self.local_optimizer = LocalOptimizer()
        self.validator = AllocationValidator()

    def execute(self, context):
        # Phase 1: CP Solver
        cp_context = self.cp_solver.solve(context.groups, context.room_allocations)

        if cp_context is None:
            # Fallback: use existing hyper-heuristic as construction
            context = self.adaptive_engine.execute(context)
        else:
            context = cp_context

        # Phase 2: Hyper-Heuristic Refinement
        context = self.pattern_optimizer.optimize(context)
        context = self.local_optimizer.optimize(context)

        # Phase 3: LNS Optimization
        context = self.lns_engine.optimize(context)

        # Final Validation Check (warnings only)
        result = self.validator.validate(context)
        if not result.success:
            warnings.warn(f"Final hybrid allocation validation errors: {result.errors}")

        return context
