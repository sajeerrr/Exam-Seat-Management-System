# engine/lns/repair_operator.py

from engine.cp.cp_model_builder import CPModelBuilder
from ortools.sat.python import cp_model
from engine.config import CPSolverConfig


class RepairOperator:
    """Repair destroyed rooms using CP solver."""

    def repair(self, context, destroyed_indices, time_limit=5.0):
        """
        1. Collect all students currently unallocated (due to destroy)
        2. Build a sub-problem CP model for the destroyed rooms
        3. Solve and merge back into context
        """
        rooms_to_repair = [context.room_allocations[i] for i in destroyed_indices]

        # Get all groups with remaining students
        groups = context.groups

        builder = CPModelBuilder()
        model, assign = builder.build(groups, rooms_to_repair)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit)
        solver.parameters.num_search_workers = CPSolverConfig.NUM_WORKERS

        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            streams_map = ["A", "B", "C"]
            for g_idx, group in enumerate(groups):
                for local_r_idx, room in enumerate(rooms_to_repair):
                    for s_idx, stream_name in enumerate(streams_map):
                        val = solver.Value(assign[(g_idx, local_r_idx, s_idx)])
                        if val > 0:
                            allocated_students = group.allocate_students(val)
                            room.assign_to_stream(stream_name, group, len(allocated_students))
            return True

        return False
