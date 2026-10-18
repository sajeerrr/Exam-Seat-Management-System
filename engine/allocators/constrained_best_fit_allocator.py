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
        stream_cap = room_allocations[0].classroom.column_capacity if room_allocations else 15
        distinct_all_depts = set(g.department for g in context.groups)
        use_block_allocation = (
            len(distinct_all_depts) >= 2 or
            any(g.strength >= stream_cap for g in context.groups) or
            not has_special_groups
        )
        prev_stream_depts = {"A": None, "B": None, "C": None}
        prev_special_code = None

        total_students = sum(g.remaining_count for g in context.groups)
        min_rooms = max(1, (total_students + 44) // 45)
        remainder = total_students % 45
        effective_caps = {}
        if min_rooms > 1 and 0 < remainder < 25 and use_block_allocation:
            total_streams = min_rooms * 3
            base_cap = total_students // total_streams
            extra = total_students % total_streams
            extras_distributed = 0
            for r_i in range(min_rooms):
                for s_name in ["A", "B", "C"]:
                    if extras_distributed < extra and s_name == "A":
                        effective_caps[(r_i, s_name)] = base_cap + 1
                        extras_distributed += 1
                    else:
                        effective_caps[(r_i, s_name)] = base_cap

        for room_idx, room in enumerate(room_allocations):
            if all(g.remaining_count == 0 for g in context.groups):
                break

            # Pre-plan room stream department targets
            if use_block_allocation:
                available_for_plan = [g for g in context.groups if g.remaining_count > 0]
            else:
                available_for_plan = [
                    g for g in context.groups
                    if not g.is_special_subject and g.remaining_count > 0
                ]
            room_plan_depts = {"A": None, "B": None, "C": None}

            if available_for_plan:
                dept_totals = {}
                for g in available_for_plan:
                    dept_totals[g.department] = dept_totals.get(g.department, 0) + g.remaining_count

                distinct_depts = sorted(dept_totals.keys(), key=lambda d: (-dept_totals[d], d))

                if len(distinct_depts) >= 3:
                    # ABC Room: 3 distinct departments for Streams A, B, C
                    # Always draw from the top 3 departments with largest remaining counts
                    # to prevent department starvation and ensure Stream B is always occupied
                    d1, d2, d3 = distinct_depts[0], distinct_depts[1], distinct_depts[2]
                    top3 = {d1, d2, d3}
                    d_a = prev_stream_depts.get("A") if prev_stream_depts.get("A") in top3 else d1
                    rem_b = [d for d in (d1, d2, d3) if d != d_a]
                    d_b = prev_stream_depts.get("B") if prev_stream_depts.get("B") in rem_b else rem_b[0]
                    rem_c = [d for d in rem_b if d != d_b]
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
                    room_plan_depts["B"] = d_only
                    room_plan_depts["C"] = d_only

            # Stream allocation passes
            fill_modes = ("empty_only", "same_dept_partial") if use_block_allocation else ("empty_only",)
            for fill_mode in fill_modes:
                room_active = True
                while room_active and room.used_capacity < room.classroom.capacity:
                    if use_block_allocation:
                        available_candidates = [
                            g for g in context.groups
                            if g.remaining_count > 0
                        ]
                    else:
                        available_candidates = [
                            g for g in context.groups
                            if not g.is_special_subject and g.remaining_count > 0
                        ]
                    if not available_candidates:
                        break

                    if fill_mode == "empty_only":
                        target_streams = [
                            s_name for s_name in ["A", "B", "C"]
                            if room.get_stream(s_name)
                            and len(room.get_stream(s_name).students) == 0
                        ]
                        if not use_block_allocation:
                            # If special groups remain, reserve Stream A for them so Streams B & C buffer them
                            if any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
                                target_streams = [s for s in target_streams if s != "A"]
                    else:
                        target_streams = [
                            s_name for s_name in ["A", "B", "C"]
                            if room.get_stream(s_name)
                            and len(room.get_stream(s_name).students) < (13 if use_block_allocation else stream_cap)
                        ]

                    if not target_streams:
                        break

                    best_assignment = None

                    for stream_name in target_streams:
                        stream = room.get_stream(stream_name)
                        rem_in_stream = stream.capacity - len(stream.students)
                        if rem_in_stream <= 0:
                            continue

                        st_a_depts = room.get_stream("A").departments
                        st_b_depts = room.get_stream("B").departments
                        st_c_depts = room.get_stream("C").departments

                        st_a_norm = {
                            getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                            for s in room.get_stream("A").students
                        }
                        st_b_norm = {
                            getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                            for s in room.get_stream("B").students
                        }
                        st_c_norm = {
                            getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                            for s in room.get_stream("C").students
                        }

                        for group in available_candidates:
                            if not room.can_add_department(group.department, is_fallback_pass=False):
                                if not room.can_add_department(group.department, is_fallback_pass=True):
                                    continue

                            if fill_mode == "same_dept_partial" and group.department not in stream.departments:
                                continue

                            g_norm = group.normalized_subject_code

                            # Subject clash checks
                            if not group.is_special_subject:
                                if not room.can_seat_subject(
                                    stream_name,
                                    group.subject_code,
                                    group.department,
                                    group.subject_name,
                                    is_special_subject=False,
                                ):
                                    continue
                            else:
                                # Horizontal subject clash check for special subjects
                                if stream_name == "A" and (group.subject_code in room.get_stream("B").subject_codes or g_norm in st_b_norm):
                                    continue
                                if stream_name == "B":
                                    if group.subject_code in room.get_stream("A").subject_codes or g_norm in st_a_norm:
                                        continue
                                    if group.subject_code in room.get_stream("C").subject_codes or g_norm in st_c_norm:
                                        continue
                                if stream_name == "C" and (group.subject_code in room.get_stream("B").subject_codes or g_norm in st_b_norm):
                                    continue

                            # Adjacent stream department checks
                            avail_other_depts = any(g.department != group.department for g in available_candidates)
                            if stream_name == "A" and group.department in st_b_depts:
                                if avail_other_depts or not use_block_allocation:
                                    continue
                            if stream_name == "B":
                                if (group.department in st_a_depts or group.department in st_c_depts) and (avail_other_depts or not use_block_allocation):
                                    continue
                                if not use_block_allocation and any(sg.department == group.department for sg in context.groups if sg.is_special_subject and sg.remaining_count > 0):
                                    continue
                            if stream_name == "C" and group.department in st_b_depts:
                                if avail_other_depts or not use_block_allocation:
                                    continue

                            # Calculate take count
                            if use_block_allocation:
                                if len(stream.students) == 0:
                                    if group.remaining_count <= rem_in_stream:
                                        take = group.remaining_count
                                    elif (group.remaining_count - rem_in_stream) in (1, 2):
                                        take = group.remaining_count - 3
                                        if take < 3:
                                            continue
                                    else:
                                        take = rem_in_stream
                                else:
                                    take = min(rem_in_stream, group.remaining_count)
                                    if take <= 2 and group.remaining_count > take:
                                        continue  # Guard: Never peel 1 or 2 students from a larger group
                                    leftover = group.remaining_count - take
                                    if leftover in (1, 2):
                                        needed = 3 - leftover
                                        if take - needed >= 3:
                                            take -= needed
                                        else:
                                            continue  # Guard: Don't split group if it leaves 1 or 2 students
                            else:
                                take = min(rem_in_stream, group.remaining_count)

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
                                        g.department for g in available_candidates
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

                            same_stream_dept_bonus = 3 if group.department in stream.departments else 0

                            stream_order = {"A": 0, "B": 1, "C": 2}.get(stream_name, 0)
                            candidate_key = (
                                is_target_dept,
                                -same_stream_dept_bonus,
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

        if use_block_allocation and any(g.remaining_count > 0 for g in context.groups):
            for room_idx, room in enumerate(room_allocations):
                for s_name in ["A", "B", "C"]:
                    st = room.get_stream(s_name)
                    if not st:
                        continue
                    # Guard: Never stuff additional students into streams that already have >= 13 students
                    if len(st.students) >= 13:
                        continue
                    rem = st.capacity - len(st.students)
                    if rem <= 0:
                        continue
                    st_b_subjs = room.get_stream("B").subject_codes
                    st_b_norm = {
                        getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                        for s in room.get_stream("B").students
                    }
                    for g in [grp for grp in context.groups if grp.remaining_count > 0]:
                        if not room.can_add_department(g.department, is_fallback_pass=True):
                            continue
                        g_norm = g.normalized_subject_code
                        if s_name in ("A", "C") and (g.subject_code in st_b_subjs or g_norm in st_b_norm):
                            continue
                        if s_name == "B":
                            st_a_subjs = room.get_stream("A").subject_codes
                            st_c_subjs = room.get_stream("C").subject_codes
                            st_a_norm = {getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper()) for s in room.get_stream("A").students}
                            st_c_norm = {getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper()) for s in room.get_stream("C").students}
                            if g.subject_code in st_a_subjs or g_norm in st_a_norm or g.subject_code in st_c_subjs or g_norm in st_c_norm:
                                continue
                        take = min(rem, g.remaining_count)
                        if take <= 2 and g.remaining_count > take:
                            continue  # Guard: Do not peel 1 or 2 students from a larger group
                        room.assign_to_stream(s_name, g, take)
                        rem -= take
                        if rem <= 0:
                            break

            if not use_block_allocation:
                # If special groups remain, try to allocate Stream A as a dedicated pure elective stream
                # ONLY when buffered horizontally by an occupied Stream B
                stream_a = room.get_stream("A")
                stream_b = room.get_stream("B")
                if stream_a and len(stream_a.students) == 0 and stream_b and len(stream_b.students) > 0:
                    avail_special = [
                        g for g in context.groups
                        if g.is_special_subject and g.remaining_count > 0
                    ]
                    st_b_subjs = room.get_stream("B").subject_codes
                    st_b_norm_subjs = {
                        getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                        for s in room.get_stream("B").students
                    }

                    valid_spec = []
                    for g in avail_special:
                        if not room.can_add_department(g.department, is_fallback_pass=True):
                            continue
                        if (
                            g.subject_code in st_b_subjs
                            or g.normalized_subject_code in st_b_subjs
                            or g.normalized_subject_code in st_b_norm_subjs
                        ):
                            continue

                        cont_bonus = 2 if g.subject_code == prev_special_code else 0
                        dept_bonus = 1 if prev_stream_depts.get("A") == g.department else 0
                        key = (-cont_bonus, -dept_bonus, -g.remaining_count, g.subject_code)
                        valid_spec.append((key, g))

                    if valid_spec:
                        valid_spec.sort(key=lambda x: x[0])
                        best_spec = valid_spec[0][1]
                        take = min(stream_a.capacity, best_spec.remaining_count)
                        room.assign_to_stream("A", best_spec, take)
                        prev_stream_depts["A"] = best_spec.department
                        prev_special_code = best_spec.subject_code

            if not use_block_allocation and any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
                self._allocate_special_in_room(room, context)

        if not use_block_allocation and any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
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

        snapshot_before_balance = context.snapshot()
        if use_block_allocation:
            try:
                context = self.local_optimizer.optimize(context)
                bal_result = self.validator.validate(context)
                if allow_unallocated:
                    bal_result.errors = [e for e in bal_result.errors if "unallocated student(s)" not in e]
                    bal_result.success = (len(bal_result.errors) == 0)
                if not bal_result.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
                    context.restore(snapshot_before_balance)
            except Exception:
                context.restore(snapshot_before_balance)

            # Maximize pure ABC rooms and convert ABA pairs
            from engine.adaptive.aba_to_abc_optimizer import ABAToABCOptimizer
            snapshot_before_aba = context.snapshot()
            try:
                context = ABAToABCOptimizer().optimize(context)
                aba_val = self.validator.validate(context)
                if allow_unallocated:
                    aba_val.errors = [e for e in aba_val.errors if "unallocated student(s)" not in e]
                    aba_val.success = (len(aba_val.errors) == 0)
                if not aba_val.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
                    context.restore(snapshot_before_aba)
            except Exception:
                context.restore(snapshot_before_aba)

        # Consolidate underfilled tail rooms to eliminate threshold violations
        self._absorb_underfilled_tail_rooms(context)

        # Balance streams within rooms (Option A: Cohorts-Intact)
        self._balance_room_streams(context)

        final_validation = self.validator.validate(context)
        if allow_unallocated:
            final_validation.errors = [
                e for e in final_validation.errors if "unallocated student(s)" not in e
            ]
            final_validation.success = (len(final_validation.errors) == 0)

        if not final_validation.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
            if not has_special_groups:
                context.restore(snapshot_before_balance)
                final_validation = self.validator.validate(context)
                if allow_unallocated:
                    final_validation.errors = [
                        e for e in final_validation.errors if "unallocated student(s)" not in e
                    ]
                    final_validation.success = (len(final_validation.errors) == 0)
            if not final_validation.success or (must_have_zero_unallocated and sum(g.remaining_count for g in context.groups) > 0):
                raise ValueError(f"ALLOCATION FAILED VALIDATION: {final_validation.errors}")

        return context

    def _allocate_special_in_room(self, room, context):
        col_map = {"A": 0, "B": 1, "C": 2}
        benches = getattr(room.classroom, "column_capacity", 15) or 15

        has_normal = any(not g.is_special_subject for g in context.groups)
        for bench in range(1, benches + 1):
            if all(g.remaining_count == 0 for g in context.groups if g.is_special_subject):
                break

            for s_name in ["A", "B", "C"]:
                stream = room.get_stream(s_name)
                if not stream or len(stream.students) >= stream.capacity:
                    continue

                # Never mix special students into a stream that contains normal students
                if any(not getattr(s, "is_special_subject", False) for s in stream.students):
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

    def _absorb_underfilled_tail_rooms(self, context, min_threshold: int = 15) -> bool:
        """
        Consolidates underfilled tail rooms (< min_threshold students) by absorbing
        their students into earlier rooms that have spare capacity in compatible streams,
        eliminating wasteful single-digit or tiny fragment rooms.
        """
        active_rooms = [r for r in context.room_allocations if r.used_capacity > 0]
        if len(active_rooms) < 2:
            return False

        total_students = sum(g.strength for g in context.groups)
        min_rooms_needed = max(1, (total_students + 44) // 45)
        dynamic_min = min(min_threshold, total_students // min_rooms_needed if min_rooms_needed > 0 else min_threshold)

        underfilled = [r for r in active_rooms if 0 < r.used_capacity < dynamic_min]
        if not underfilled:
            return False

        modified = False
        for ur in reversed(underfilled):
            cohort_map = {}
            for s_name in ["A", "B", "C"]:
                for stu in ur.get_stream(s_name).students:
                    s_code = getattr(stu, "normalized_subject_code", str(stu.subject_code).strip().upper())
                    key = (stu.department, s_code)
                    cohort_map.setdefault(key, []).append(stu)

            if not cohort_map:
                continue

            plan = []
            possible = True

            ur_idx = active_rooms.index(ur)
            candidate_rooms = [r for r in active_rooms if active_rooms.index(r) < ur_idx]

            for (dept, s_code), cohort in cohort_map.items():
                k = len(cohort)
                placed = False
                for r in reversed(candidate_rooms):
                    extra_for_r = sum(len(p[0]) for p in plan if p[1] == r)
                    if r.used_capacity + extra_for_r + k > r.classroom.capacity:
                        continue
                    if not r.can_add_department(dept, is_fallback_pass=True):
                        continue

                    for s_name in ["A", "B", "C"]:
                        stream = r.get_stream(s_name)
                        if not stream:
                            continue
                        extra_for_st = sum(len(p[0]) for p in plan if p[1] == r and p[2] == s_name)
                        curr_count = len(stream.students) + extra_for_st
                        if curr_count + k > stream.capacity:
                            continue

                        stream_subjs = {getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper()) for s in stream.students}
                        if stream_subjs and s_code not in stream_subjs:
                            continue

                        st_a_depts = set(r.get_stream("A").departments) | {p[0][0].department for p in plan if p[1] == r and p[2] == "A"}
                        st_b_depts = set(r.get_stream("B").departments) | {p[0][0].department for p in plan if p[1] == r and p[2] == "B"}
                        st_c_depts = set(r.get_stream("C").departments) | {p[0][0].department for p in plan if p[1] == r and p[2] == "C"}

                        if s_name == "A" and dept in st_b_depts:
                            continue
                        if s_name == "B" and (dept in st_a_depts or dept in st_c_depts):
                            continue
                        if s_name == "C" and dept in st_b_depts:
                            continue

                        has_clash = False
                        col_map = {"A": 0, "B": 1, "C": 2}
                        inv_map = {0: "A", 1: "B", 2: "C"}
                        c0 = col_map[s_name]
                        for dc in (-1, 1):
                            c = c0 + dc
                            if c in inv_map:
                                adj_st = r.get_stream(inv_map[c])
                                if adj_st:
                                    adj_subjs = {
                                        getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                                        for s in adj_st.students
                                    }
                                    if s_code in adj_subjs:
                                        has_clash = True
                                        break
                        if has_clash:
                            continue

                        plan.append((cohort, r, s_name))
                        placed = True
                        break
                    if placed:
                        break
                if not placed:
                    possible = False
                    break

            if possible and len(plan) == len(cohort_map):
                # Save snapshot of modified rooms
                affected_rooms = {target_room for _, target_room, _ in plan} | {ur}
                snapshot = {
                    r_obj: {s: list(r_obj.get_stream(s).students) for s in ["A", "B", "C"]}
                    for r_obj in affected_rooms
                }

                for cohort, target_room, target_sname in plan:
                    target_room.get_stream(target_sname).students.extend(cohort)
                for s_name in ["A", "B", "C"]:
                    ur.get_stream(s_name).students.clear()

                from engine.validators.allocation_validator import AllocationValidator
                val_errs, _ = AllocationValidator().validate(context, active_rooms)
                if val_errs:
                    # Rollback changes if validation fails
                    for r_obj, s_dict in snapshot.items():
                        for s_name, stus in s_dict.items():
                            r_obj.get_stream(s_name).students = list(stus)
                else:
                    modified = True

        return modified

    def _balance_room_streams(self, context) -> bool:
        """
        Balances student counts across streams (A, B, C) within rooms (Option A: Cohorts-Intact).
        Reduces large discrepancies (e.g. 14 vs 2) between streams by moving entire intact
        department/subject cohorts to underfilled streams without splitting any cohort,
        ensuring zero capacity, department limit, or horizontal adjacency violations.
        """
        from engine.adaptive.stream_balancer import RoomStreamBalancer
        return RoomStreamBalancer().balance(context)

