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

    def execute(self, context: AllocationContext) -> AllocationContext:
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        room_allocations = context.room_allocations
        has_special_groups = any(g.is_special_subject for g in context.groups)

        for room_idx, room in enumerate(room_allocations):
            if all(g.remaining_count == 0 for g in context.groups):
                break

            room_active = True
            while room_active and room.used_capacity < room.classroom.capacity:
                available_normal = [
                    g for g in context.groups
                    if not g.is_special_subject and g.remaining_count > 0
                ]
                if not available_normal:
                    break

                current_room_depts = room.departments

                def group_sort_key(g):
                    has_dept_match = 0 if (g.department in current_room_depts or not current_room_depts) else 1
                    return (has_dept_match, -g.remaining_count, g.department, g.subject_code)

                available_normal.sort(key=group_sort_key)

                best_group = None
                best_stream_name = None
                best_take = 0

                for group in available_normal:
                    if not room.can_add_department(group.department, is_fallback_pass=True):
                        continue

                    for stream_name in ["A", "B", "C"]:
                        stream = room.get_stream(stream_name)
                        if not stream or stream.remaining_capacity <= 0:
                            continue

                        if not room.can_seat_subject(
                            stream_name,
                            group.subject_code,
                            group.department,
                            group.subject_name,
                            is_special_subject=False,
                        ):
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
                else:
                    room_active = False

            if any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
                self._allocate_special_in_room(room, context)

        if any(g.is_special_subject and g.remaining_count > 0 for g in context.groups):
            for room in room_allocations:
                if room.used_capacity < room.classroom.capacity:
                    self._allocate_special_in_room(room, context)

        context.remaining_pool = RemainingPool(context.groups)

        unallocated_sum = sum(g.remaining_count for g in context.groups)
        if unallocated_sum > 0 and not has_special_groups:
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

        if not has_special_groups:
            snapshot_before_balance = context.snapshot()
            try:
                context = self.local_optimizer.optimize(context)
                bal_result = self.validator.validate(context)
                if not bal_result.success or sum(g.remaining_count for g in context.groups) > 0:
                    context.restore(snapshot_before_balance)
            except Exception:
                context.restore(snapshot_before_balance)

        final_validation = self.validator.validate(context)
        if not final_validation.success or sum(g.remaining_count for g in context.groups) > 0:
            if not has_special_groups:
                context.restore(snapshot_before_balance)
                final_validation = self.validator.validate(context)
            if not final_validation.success or sum(g.remaining_count for g in context.groups) > 0:
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
                    if not room.can_add_department(g.department, is_fallback_pass=True):
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

                    dept_bonus = 1 if g.department in room.departments else 0
                    return (-c_pair_bonus, -g.remaining_count, -dept_bonus, -min_d, g.subject_code)

                valid_candidates.sort(key=candidate_score)
                best_group = valid_candidates[0]
                allocated_student = best_group.allocate_students(1)[0]
                stream.students.append(allocated_student)
