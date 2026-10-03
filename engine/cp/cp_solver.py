# engine/cp/cp_solver.py

from ortools.sat.python import cp_model
from engine.cp.cp_model_builder import CPModelBuilder
from engine.cp.cp_solution_converter import CPSolutionConverter
from engine.config import CPSolverConfig


class CPSolver:
    """Phase 1: Find initial feasible solution using CP-SAT."""

    def __init__(self, time_limit_seconds=None):
        self.builder = CPModelBuilder()
        self.converter = CPSolutionConverter()
        self.time_limit = time_limit_seconds or CPSolverConfig.TIME_LIMIT_SECONDS

    def solve(self, groups, room_allocations):
        """
        1. Build CP model from groups + room_allocations
        2. Solve with time limit
        3. If feasible -> convert to AllocationContext
        4. If infeasible -> return None (fallback to hyper-heuristic)
        """
        model, assign = self.builder.build(groups, room_allocations)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.time_limit)
        solver.parameters.num_search_workers = CPSolverConfig.NUM_WORKERS

        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            return self.converter.convert(solver, assign, groups, room_allocations)

        return None
