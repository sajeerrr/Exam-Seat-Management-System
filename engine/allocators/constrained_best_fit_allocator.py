from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.validators.allocation_validator import AllocationValidator
from engine.adaptive.local_optimizer import LocalOptimizer
from engine.cp.cp_solver import CPSolver

class ConstrainedBestFitAllocator:

    def __init__(self):
        self.validator = AllocationValidator()
        self.local_optimizer = LocalOptimizer()
        self.cp_solver = CPSolver()

    def execute(self, context: AllocationContext, allow_unallocated: bool = False) -> AllocationContext:
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        initial_snapshot = context.snapshot()
        room_allocations = context.room_allocations
        has_special_groups = any(g.is_special_subject for g in context.groups)
        prev_stream_depts = {"A": None, "B": None, "C": None}

        for room_idx, room in enumerate(room_allocations):
            if all(g.remaining_count == 0 for g in context.groups):
                break

            # Pre-plan room stream department targets for normal subjects
            available_normal = [
                g for g in context.groups
                if not g.is_special_subject and g.remaining_count > 0
            ]
            room_plan_depts = {"A": None, "B": None, "C": None}

            if available_normal:
                dept_totals = {}
                for g in available_normal:
                    dept_totals[g.department] = dept_totals.get(g.department, 0) + g.remaining_count

                distinct_depts = sorted(dept_totals.keys(), key=lambda d: (-dept_totals[d], d))

                if len(distinct_depts) >= 3:
                    # ABC Room: 3 distinct departments for Streams A, B, C
                    d_a = prev_stream_depts.get("A") if prev_stream_depts.get("A") in dept_totals else None
                    if not d_a:
                        d_a = distinct_depts[0]

                    rem_b = [d for d in distinct_depts if d != d_a]
                    d_b = prev_stream_depts.get("B") if prev_stream_depts.get("B") in rem_b else None
                    if not d_b:
                        d_b = rem_b[0]

                    rem_c = [d for d in distinct_depts if d != d_a and d != d_b]
                    d_c = prev_stream_depts.get("C") if prev_stream_depts.get("C") in rem_c else None
                    if not d_c:
                        d_c = rem_c[0]

                    room_plan_depts["A"] = d_a
                    room_plan_depts["B"] = d_b
                    room_plan_depts["C"] = d_c

                elif len(distinct_depts) == 2:
                    # ABA Room: Department with >= 2 stream slots goes to A and C
                    # Other department goes to buffer Stream B
                    d_large = distinct_depts[0]
                    d_small = distinct_depts[1]
                    room_plan_depts["A"] = d_large
                    room_plan_depts["B"] = d_small
                    room_plan_depts["C"] = d_large

                elif len(distinct_depts) == 1:
                    d_only = distinct_depts[0]
                    room_plan_depts["A"] = d_only
                    room_plan_depts["C"] = d_only

            room_active = True
            while room_active and room.used_capacity < room.classroom.capacity:
                available_normal = [
                    g for g in context.groups
                    if not g.is_special_subject and g.remaining_count > 0
                ]
                if not available_normal:
                    break

                target_streams = [
                    s_name for s_name in ["A", "B", "C"]
                    if room.get_stream(s_name) and room.get_stream(s_name).remaining_capacity > 0
                ]
                if not target_streams:
                    break

                best_assignment = None

                for stream_name in target_streams:
                    stream = room.get_stream(stream_name)
                    st_a_depts = room.get_stream("A").departments
                    st_b_depts = room.get_stream("B").departments
                    st_c_depts = room.get_stream("C").departments

                    for group in available_normal:
                        if not room.can_add_department(group.department, is_fallback_pass=False):
                            if not room.can_add_department(group.department, is_fallback_pass=True):
                                continue

                        if not room.can_seat_subject(
                            stream_name,
                            group.subject_code,
                            group.department,
                            group.subject_name,
                            is_special_subject=False,
                        ):
                            continue

                        # Adjacent stream department checks
                        if stream_name == "A" and group.department in st_b_depts:
                            continue
                        if stream_name == "B" and (group.department in st_a_depts or group.department in st_c_depts):
                            continue
                        if stream_name == "C" and group.department in st_b_depts:
                            continue

                        take = min(stream.remaining_capacity, group.remaining_count)
                        if take <= 0:
                            continue

                        # Match with pre-planned room stream targets
                        is_target_dept = 0 if room_plan_depts.get(stream_name) == group.department else 1

                        # Pattern priority calculation:
                        # 1: ABC Pattern (3 distinct departments across A, B, C)
                        # 2: ABA Pattern (Stream A & C share department, B is different)
                        # 3: Fallback / other
                        pattern_prio = 3
                        if stream_name == "C":
                            if st_a_depts and st_b_depts:
                                if group.department not in st_a_depts and group.department not in st_b_depts:
                                    pattern_prio = 1  # ABC
                                elif group.department in st_a_depts:
                                    pattern_prio = 2  # ABA
                        elif stream_name == "B":
                            if st_a_depts and st_c_depts:
                                if group.department not in st_a_depts and group.department not in st_c_depts:
                                    pattern_prio = 1  # ABC
                            elif st_a_depts and not st_c_depts:
                                other_depts = {
                                    g.department for g in available_normal
                                    if g.department not in st_a_depts and g.department != group.department
                                }
                                pattern_prio = 1 if other_depts else 2
                        elif stream_name == "A":
                            if st_b_depts and st_c_depts:
                                if group.department not in st_b_depts and group.department not in st_c_depts:
                                    pattern_prio = 1  # ABC
                                elif group.department in st_c_depts:
                                    pattern_prio = 2  # ABA
                            else:
                                pattern_prio = 1

                        consolidation_bonus = 0
                        if prev_stream_depts.get(stream_name) == group.department:
                            consolidation_bonus = 2
                        elif group.department in stream.departments:
                            consolidation_bonus = 1

                        stream_order = {"A": 0, "B": 1, "C": 2}.get(stream_name, 0)
                        candidate_key = (
                            is_target_dept,
                            pattern_prio,
                            stream_order,
                            -consolidation_bonus,
                            -group.remaining_count,
                            group.department,
                            group.subject_code,
                        )

                        if best_assignment is None or candidate_key < best_assignment[0]:
                            best_assignment = (candidate_key, stream_name, group, take)

                if best_assignment:
                    _, b_stream_name, b_group, b_take = best_assignment
                    room.assign_to_stream(b_stream_name, b_group, b_take)
                    prev_stream_depts[b_stream_name] = b_group.department
                else:
                    room_active = False

            if any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
                self._allocate_special_in_room(room, context)

        if any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
            for room in room_allocations:
                if room.used_capacity < room.classroom.capacity:
                    self._allocate_special_in_room(room, context)

        context.remaining_pool = RemainingPool(context.groups)

        total_capacity = sum(r.classroom.capacity for r in context.room_allocations)
        total_students = sum(g.strength for g in context.groups)
        unallocated_sum = sum(g.remaining_count for g in context.groups)
        must_have_zero_unallocated = (total_capacity >= total_students) and not allow_unallocated

        if unallocated_sum > 0 and not has_special_groups:
            snapshot = context.snapshot()
            context.restore(initial_snapshot)
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

        if not has_special_groups:
            snapshot_before_balance = context.snapshot()
            try:
                context = self.local_optimizer.optimize(context)
                bal_result = self.validator.validate(context)
                if not bal_result.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
                    context.restore(snapshot_before_balance)
            except Exception:
                context.restore(snapshot_before_balance)

        final_validation = self.validator.validate(context)
        if allow_unallocated:
            final_validation.errors = [
                e for e in final_validation.errors if "unallocated student(s)" not in e
            ]

        if not final_validation.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
            if not has_special_groups:
                context.restore(snapshot_before_balance)
                final_validation = self.validator.validate(context)
                if allow_unallocated:
                    final_validation.errors = [
                        e for e in final_validation.errors if "unallocated student(s)" not in e
                    ]
            if not final_validation.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
                raise ValueError(f"ALLOCATION FAILED VALIDATION: {final_validation.errors}")

        return context

    def _allocate_special_in_room(self, room, context):
        col_map = {"A": 0, "B": 1, "C": 2}
        benches = getattr(room.classroom, "column_capacity", 15) or 15

        for bench in range(1, benches + 1):
            if all(g.remaining_count == 0 for g in context.groups if g.is_special_subject):
                break

            for s_name in ["A", "B", "C"]:
                stream = room.get_stream(s_name)
                if not stream or len(stream.students) >= stream.capacity:
                    continue

                b_no = len(stream.students) + 1
                c0 = col_map[s_name]

                special_groups = [
                    g for g in context.groups
                    if g.is_special_subject and g.remaining_count > 0
                ]
                if not special_groups:
                    break

                valid_candidates = []
                for g in special_groups:
                    nxt = g.allocated_count
                    cand_dept = g.students[nxt].department if nxt < len(g.students) else g.department
                    if not room.can_add_department(cand_dept, is_fallback_pass=True):
                        continue

                    if not room.can_seat_special_subject(s_name, b_no, g.subject_code):
                        continue

                    adj_students = room.get_adjacent_students(s_name, b_no)
                    has_normal_clash = any(
                        not getattr(a, "is_special_subject", False) and
                        getattr(a, "normalized_subject_code", str(a.subject_code).strip().upper()) == g.normalized_subject_code
                        for a in adj_students
                    )
                    if has_normal_clash:
                        continue

                    valid_candidates.append(g)

                if not valid_candidates:
                    continue

                st_a = room.get_stream("A")
                a_code = (
                    st_a.students[b_no - 1].normalized_subject_code
                    if st_a and len(st_a.students) >= b_no else None
                )

                def candidate_score(g):
                    c_pair_bonus = 1 if (s_name == "C" and a_code and g.normalized_subject_code == a_code) else 0
                    min_d = 999
                    for sn in ["A", "B", "C"]:
                        st = room.get_stream(sn)
                        if not st:
                            continue
                        for idx, seated_stud in enumerate(st.students):
                            seated_code = getattr(
                                seated_stud, "normalized_subject_code",
                                str(seated_stud.subject_code).strip().upper()
                            )
                            if seated_code == g.normalized_subject_code:
                                d = max(abs(c0 - col_map[sn]), abs(b_no - (idx + 1)))
                                if d < min_d:
                                    min_d = d

                    nxt = g.allocated_count
                    cand_d = g.students[nxt].department if nxt < len(g.students) else g.department
                    dept_bonus = 1 if cand_d in room.departments else 0
                    return (-c_pair_bonus, -g.remaining_count, -dept_bonus, -min_d, g.subject_code)

                valid_candidates.sort(key=candidate_score)
                best_group = valid_candidates[0]
                allocated_student = best_group.allocate_students(1)[0]
                stream.students.append(allocated_student)
