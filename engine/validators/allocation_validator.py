from engine.config import AllocationLimits
from engine.models.validation_result import ValidationResult


class AllocationValidator:

    def validate(self, context):
        result = ValidationResult()
        self.validate_duplicates(context, result)
        self.validate_capacity(context, result)
        self.validate_streams(context, result)
        self.validate_departments(context, result)
        self.validate_adjacent_conflicts(context, result)
        self.validate_special_subject_adjacency(context, result)
        self.validate_unallocated_groups(context, result)
        self.validate_room_occupancy(context, result)
        return result

    def validate_duplicates(self, context, result):
        allocated = set()
        for room in context.room_allocations:
            for stream in room.streams.values():
                for student in stream.students:
                    if student.register_no in allocated:
                        result.duplicate_students += 1
                        result.add_error(f"Duplicate student: {student.register_no}")
                    allocated.add(student.register_no)

    def validate_capacity(self, context, result):
        for room in context.room_allocations:
            if room.used_capacity > room.classroom.capacity:
                result.capacity_violations += 1
                result.add_error(f"{room.classroom.room_no} exceeds capacity")

    def validate_streams(self, context, result):
        for room in context.room_allocations:
            for stream_name, stream in room.streams.items():
                if len(stream.students) > stream.capacity:
                    result.capacity_violations += 1
                    result.add_error(
                        f"{room.classroom.room_no}-{stream_name} exceeded stream capacity"
                    )

    def validate_departments(self, context, result):
        max_depts = 0
        for room in context.room_allocations:
            depts_count = len(room.departments)
            if depts_count > max_depts:
                max_depts = depts_count
            if depts_count > 4:
                result.add_error(
                    f"Room {room.classroom.room_no} exceeds max 4 departments: {depts_count}"
                )
        result.max_departments_per_room = max_depts

    def validate_adjacent_conflicts(self, context, result):
        for room in context.room_allocations:
            normal_subjs_by_stream = {}
            for name, stream in room.streams.items():
                normal_subjs = {
                    getattr(s, "normalized_subject_code", str(s.subject_code).strip().upper())
                    for s in stream.students
                    if not getattr(s, "is_special_subject", False)
                }
                normal_subjs_by_stream[name] = normal_subjs

            if normal_subjs_by_stream.get("A") and normal_subjs_by_stream.get("B"):
                overlap = normal_subjs_by_stream["A"].intersection(normal_subjs_by_stream["B"])
                if overlap:
                    result.normal_subject_violations += len(overlap)
                    result.add_error(
                        f"Room {room.classroom.room_no}: Adjacent streams A and B share normal subject {overlap}"
                    )

            if normal_subjs_by_stream.get("B") and normal_subjs_by_stream.get("C"):
                overlap = normal_subjs_by_stream["B"].intersection(normal_subjs_by_stream["C"])
                if overlap:
                    result.normal_subject_violations += len(overlap)
                    result.add_error(
                        f"Room {room.classroom.room_no}: Adjacent streams B and C share normal subject {overlap}"
                    )

    def validate_special_subject_adjacency(self, context, result):
        col_map = {"A": 0, "B": 1, "C": 2}
        inv_map = {0: "A", 1: "B", 2: "C"}

        for room in context.room_allocations:
            for s_name in ["A", "B", "C"]:
                stream = room.get_stream(s_name)
                if not stream:
                    continue

                for idx, student in enumerate(stream.students):
                    if not getattr(student, "is_special_subject", False):
                        continue

                    bench_no = idx + 1
                    s_code = getattr(student, "normalized_subject_code", str(student.subject_code).strip().upper())
                    s_cat = getattr(student, "subject_category", "ELECTIVE").upper()

                    c0 = col_map[s_name]

                    for dc in (-1, 0, 1):
                        c = c0 + dc
                        if c not in inv_map:
                            continue
                        adj_sname = inv_map[c]
                        adj_stream = room.get_stream(adj_sname)
                        if not adj_stream:
                            continue

                        for db in (-1, 0, 1):
                            if dc == 0 and db == 0:
                                continue
                            adj_bno = bench_no + db
                            if (c, adj_bno) <= (c0, bench_no):
                                continue

                            if 1 <= adj_bno <= len(adj_stream.students):
                                adj_student = adj_stream.students[adj_bno - 1]
                                adj_code = getattr(
                                    adj_student, "normalized_subject_code",
                                    str(adj_student.subject_code).strip().upper(),
                                )
                                if adj_code == s_code:
                                    if s_cat == "ELECTIVE":
                                        result.elective_adjacency_violations += 1
                                    elif s_cat == "MINOR":
                                        result.minor_adjacency_violations += 1
                                    elif s_cat == "HONOURS":
                                        result.honours_adjacency_violations += 1
                                    else:
                                        result.normal_subject_violations += 1

                                    result.add_error(
                                        f"SAME_SPECIAL_SUBJECT_ADJACENCY: Room {room.classroom.room_no} "
                                        f"Seat {s_name}{bench_no} ({student.register_no}) and "
                                        f"Seat {adj_sname}{adj_bno} ({adj_student.register_no}) share "
                                        f"{s_cat} subject {s_code}"
                                    )

    def validate_unallocated_groups(self, context, result):
        missing = 0
        total_capacity = sum(r.classroom.capacity for r in context.room_allocations) if context.room_allocations else 0
        total_students = sum(g.strength for g in context.groups)

        for group in context.groups:
            if group.remaining_count > 0:
                missing += group.remaining_count
                if total_capacity >= total_students:
                    result.add_error(
                        f"{group.group_id} has {group.remaining_count} unallocated student(s)"
                    )
                else:
                    result.warnings.append(
                        f"{group.group_id} has {group.remaining_count} unallocated student(s) (insufficient room capacity: {total_capacity} seats for {total_students} students)"
                    )
        result.missing_students = missing

    def validate_room_occupancy(self, context, result):
        total_students = sum(g.strength for g in context.groups)
        if total_students == 0:
            return

        min_rooms_needed = max(1, (total_students + 44) // 45)
        avg_per_room = total_students // min_rooms_needed
        dynamic_min = min(AllocationLimits.MIN_ROOM_STUDENTS, avg_per_room)

        active_rooms = [r for r in context.room_allocations if r.used_capacity > 0]
        if not active_rooms:
            return

        underfilled = [r for r in active_rooms if r.used_capacity < dynamic_min]
        if underfilled:
            result.underfilled_rooms = len(underfilled)
            for r in underfilled:
                result.add_warning(
                    f"Room {r.classroom.room_no} has only {r.used_capacity} students (dynamic target minimum is ~{dynamic_min}-30)"
                )
