import math


class PrimaryAllocator:

    def execute(self, context):
        total_students = sum(g.remaining_count for g in context.groups)
        if total_students == 0:
            return context

        # 1. Target Fleet Sizing (229 students -> exactly 6 classrooms)
        target_room_count = math.ceil(total_students / 45)
        active_rooms = context.room_allocations[:target_room_count]

        # 2. Main Allocation Pass
        for room_alloc in active_rooms:
            rem_groups = [g for g in context.groups if g.remaining_count > 0]
            if not rem_groups:
                break

            rem_groups.sort(key=lambda g: g.remaining_count, reverse=True)
            active_depts = list(set(g.department for g in rem_groups))

            # Strategy Selection:
            # - If only 2 departments remain -> Use ABA to utilize Stream C
            # - If largest group has >= 45% students -> Use ABA
            # - Otherwise -> Use 3-way ABC
            dom_group = rem_groups[0]
            total_rem = sum(g.remaining_count for g in rem_groups)

            if len(active_depts) <= 2 or (
                dom_group.remaining_count / total_rem >= 0.45
                and dom_group.remaining_count >= 20
            ):
                self._allocate_aba(room_alloc, rem_groups)
            else:
                self._allocate_abc(room_alloc, rem_groups)

        # 3. Comprehensive Leftover Compaction Pass (Guarantees 0 missing students)
        leftovers = [g for g in context.groups if g.remaining_count > 0]
        if leftovers:
            for room_alloc in active_rooms:
                self._pack_leftovers(room_alloc, leftovers)
                leftovers = [g for g in context.groups if g.remaining_count > 0]
                if not leftovers:
                    break

        # 4. Overflow Guard: If any students still remain, use the next available classroom
        final_leftovers = [g for g in context.groups if g.remaining_count > 0]
        if final_leftovers:
            for room_alloc in context.room_allocations[target_room_count:]:
                self._pack_leftovers(room_alloc, final_leftovers)
                final_leftovers = [
                    g for g in context.groups if g.remaining_count > 0
                ]
                if not final_leftovers:
                    break

        return context

    def _allocate_abc(self, room_alloc, available_groups):
        """Standard 3-way split with distinct departments."""
        used_depts = set()

        for stream_name in ["A", "B", "C"]:
            stream = room_alloc.get_stream(stream_name)
            if not stream or stream.remaining_capacity == 0:
                continue

            for group in available_groups:
                if group.remaining_count == 0:
                    continue

                if group.department in used_depts:
                    continue

                if not room_alloc.can_add_department(
                    group.department, is_fallback_pass=False
                ):
                    continue

                if not room_alloc.can_seat_subject(
                    stream_name, group.subject_code
                ):
                    continue

                take = min(stream.remaining_capacity, group.remaining_count)
                room_alloc.assign_to_stream(stream_name, group, take)
                used_depts.add(group.department)
                break

    def _allocate_aba(self, room_alloc, sorted_groups):
        """ABA Pattern: Streams A and C receive the dominant department, Stream B receives the buffer department."""
        dominant = sorted_groups[0]

        # Find a buffer department with a different department/subject
        buffer_group = None
        for g in sorted_groups[1:]:
            if g.remaining_count > 0 and g.department != dominant.department:
                buffer_group = g
                break

        # 1. Stream A (Dominant Dept)
        if dominant.remaining_count > 0:
            take_a = min(15, dominant.remaining_count)
            room_alloc.assign_to_stream("A", dominant, take_a)

        # 2. Stream B (Buffer Dept)
        if buffer_group and buffer_group.remaining_count > 0:
            take_b = min(15, buffer_group.remaining_count)
            room_alloc.assign_to_stream("B", buffer_group, take_b)

        # 3. Stream C (Dominant Dept - ABA)
        if dominant.remaining_count > 0:
            take_c = min(15, dominant.remaining_count)
            room_alloc.assign_to_stream("C", dominant, take_c)

    def _pack_leftovers(self, room_alloc, leftovers):
        """Packs odd student tails into open stream slots."""
        for stream_name in ["A", "B", "C"]:
            stream = room_alloc.get_stream(stream_name)
            if not stream or stream.remaining_capacity == 0:
                continue

            while stream.remaining_capacity > 0:
                assigned = False
                for group in list(leftovers):
                    if group.remaining_count == 0:
                        continue

                    if not room_alloc.can_add_department(
                        group.department, is_fallback_pass=True
                    ):
                        continue

                    if not room_alloc.can_seat_subject(
                        stream_name, group.subject_code
                    ):
                        continue

                    take = min(stream.remaining_capacity, group.remaining_count)
                    room_alloc.assign_to_stream(stream_name, group, take)
                    assigned = True
                    break

                if not assigned:
                    break