# engine/cp/cp_model_builder.py

from ortools.sat.python import cp_model
from engine.config import CPSolverConfig, AllocationLimits
from engine.models.room_allocation import subject_conflict_key


class CPModelBuilder:
    """Builds a CP-SAT model for the exam seating allocation problem."""

    def build(self, groups, room_allocations) -> tuple[cp_model.CpModel, dict]:
        model = cp_model.CpModel()

        num_groups = len(groups)
        num_rooms = len(room_allocations)
        streams = ["A", "B", "C"]

        # Decision variables: assign[g, r, s] = number of students from group g assigned to room r, stream s
        assign = {}
        for g_idx, group in enumerate(groups):
            for r_idx, room in enumerate(room_allocations):
                for s_idx, stream_name in enumerate(streams):
                    stream = room.get_stream(stream_name)
                    max_cap = stream.capacity if stream else 15
                    upper_bound = min(group.remaining_count, max_cap)
                    var_name = f"assign_g{g_idx}_r{r_idx}_s{s_idx}"
                    assign[(g_idx, r_idx, s_idx)] = model.NewIntVar(0, upper_bound, var_name)

        # Constraint 1: Every student in each group must be allocated fully across rooms/streams
        for g_idx, group in enumerate(groups):
            model.Add(
                sum(assign[(g_idx, r_idx, s_idx)]
                    for r_idx in range(num_rooms)
                    for s_idx in range(3)) == group.remaining_count
            )

        # Constraint 2: Stream capacity limits
        for r_idx, room in enumerate(room_allocations):
            for s_idx, stream_name in enumerate(streams):
                stream = room.get_stream(stream_name)
                stream_cap = stream.capacity if stream else 15
                model.Add(
                    sum(assign[(g_idx, r_idx, s_idx)] for g_idx in range(num_groups)) <= stream_cap
                )

        # Constraint 3: Room capacity limits
        for r_idx, room in enumerate(room_allocations):
            room_cap = room.classroom.capacity
            model.Add(
                sum(assign[(g_idx, r_idx, s_idx)]
                    for g_idx in range(num_groups)
                    for s_idx in range(3)) <= room_cap
            )

        # Constraint 4: Adjacent subject conflict (A-B and B-C cannot share subject_conflict_key)
        # For each room, for each pair of groups, if they share a subject conflict key,
        # they cannot both have students in adjacent streams (A and B, or B and C).
        for r_idx in range(num_rooms):
            for g1_idx in range(num_groups):
                for g2_idx in range(num_groups):
                    # We no longer skip g1 == g2, because a single group cannot span adjacent streams.
                    key1 = subject_conflict_key(groups[g1_idx].subject_code, groups[g1_idx].department, groups[g1_idx].subject_name)
                    key2 = subject_conflict_key(groups[g2_idx].subject_code, groups[g2_idx].department, groups[g2_idx].subject_name)

                    if key1 == key2:
                        # g1 and g2 cannot be in (A and B) or (B and C) in room r
                        # Indicator for g1 in A
                        g1_in_A = model.NewBoolVar(f"g1_{g1_idx}_r{r_idx}_in_A")
                        model.Add(assign[(g1_idx, r_idx, 0)] > 0).OnlyEnforceIf(g1_in_A)
                        model.Add(assign[(g1_idx, r_idx, 0)] == 0).OnlyEnforceIf(g1_in_A.Not())

                        # Indicator for g2 in B
                        g2_in_B = model.NewBoolVar(f"g2_{g2_idx}_r{r_idx}_in_B")
                        model.Add(assign[(g2_idx, r_idx, 1)] > 0).OnlyEnforceIf(g2_in_B)
                        model.Add(assign[(g2_idx, r_idx, 1)] == 0).OnlyEnforceIf(g2_in_B.Not())

                        # Cannot both be true (A and B conflict)
                        model.AddBoolOr([g1_in_A.Not(), g2_in_B.Not()])

                        # Indicator for g1 in B
                        g1_in_B = model.NewBoolVar(f"g1_{g1_idx}_r{r_idx}_in_B")
                        model.Add(assign[(g1_idx, r_idx, 1)] > 0).OnlyEnforceIf(g1_in_B)
                        model.Add(assign[(g1_idx, r_idx, 1)] == 0).OnlyEnforceIf(g1_in_B.Not())

                        # Indicator for g2 in C
                        g2_in_C = model.NewBoolVar(f"g2_{g2_idx}_r{r_idx}_in_C")
                        model.Add(assign[(g2_idx, r_idx, 2)] > 0).OnlyEnforceIf(g2_in_C)
                        model.Add(assign[(g2_idx, r_idx, 2)] == 0).OnlyEnforceIf(g2_in_C.Not())

                        # Cannot both be true (B and C conflict)
                        model.AddBoolOr([g1_in_B.Not(), g2_in_C.Not()])

        # Constraint 5: Room department limit (max 3 departments per room normally)
        # Modeled via department presence indicators per room
        all_departments = sorted(list({g.department for g in groups}))
        dept_room_vars = {} # (r_idx, dept) -> BoolVar
        for r_idx in range(num_rooms):
            for dept in all_departments:
                d_var = model.NewBoolVar(f"dept_{dept}_r{r_idx}")
                dept_room_vars[(r_idx, dept)] = d_var

                # Find all groups with this department
                dept_group_indices = [g_idx for g_idx, g in enumerate(groups) if g.department == dept]

                # d_var is true iff sum of students from dept in room r > 0
                dept_students_in_room = sum(assign[(g_idx, r_idx, s_idx)] for g_idx in dept_group_indices for s_idx in range(3))
                model.Add(dept_students_in_room > 0).OnlyEnforceIf(d_var)
                model.Add(dept_students_in_room == 0).OnlyEnforceIf(d_var.Not())

            # Sum of department presence vars <= max departments normal (3)
            model.Add(sum(dept_room_vars[(r_idx, dept)] for dept in all_departments) <= AllocationLimits.MAX_DEPARTMENTS_NORMAL)

        # Soft Objectives
        objective_terms = []

        # Objective 1: ABC Reward (Room has 3 distinct departments across A, B, C)
        abc_room_vars = []
        for r_idx in range(num_rooms):
            is_abc = model.NewBoolVar(f"room_{r_idx}_is_abc")
            abc_room_vars.append(is_abc)

            # For simplicity in CP-SAT, reward rooms that have high utilization and department diversity
            # We can approximate ABC reward by rewarding room utilization
            room_util = sum(assign[(g_idx, r_idx, s_idx)] for g_idx in range(num_groups) for s_idx in range(3))
            objective_terms.append(room_util * CPSolverConfig.UTILIZATION_BONUS)

        return model, assign
