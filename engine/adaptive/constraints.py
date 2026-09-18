from engine.models.room_allocation import subject_conflict_key


from engine.config import AllocationLimits


class ConstraintValidator:
    def is_feasible(self, candidate, context) -> bool:
        room = context.room_allocations[candidate.room_index]
        groups = {g.group_id: g for g in context.groups}
        planned_by_group = {}
        stream_loads = {
            name: len(stream.students)
            for name, stream in room.streams.items()
        }
        stream_subjects = {
            name: set(stream.subject_codes)
            for name, stream in room.streams.items()
        }
        departments = set(room.departments)

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            stream = room.get_stream(assignment.stream)

            if not group or not stream or assignment.count <= 0:
                return False

            planned_by_group[group.group_id] = (
                planned_by_group.get(group.group_id, 0) + assignment.count
            )
            if planned_by_group[group.group_id] > group.remaining_count:
                return False

            stream_loads[assignment.stream] += assignment.count
            if stream_loads[assignment.stream] > stream.capacity:
                return False

            stream_departments = set(stream.departments)
            if (
                candidate.decision_level < 4
                and stream_departments
                and group.department not in stream_departments
            ):
                return False

            # Use consistent limit from config (matches RoomAllocation fallback pass)
            if group.department not in departments and len(departments) >= AllocationLimits.MAX_DEPARTMENTS_FALLBACK:
                return False
            departments.add(group.department)

            stream_subjects[assignment.stream].add(
                subject_conflict_key(
                    group.subject_code,
                    group.department,
                    group.subject_name,
                )
            )

        if stream_subjects["A"].intersection(stream_subjects["B"]):
            return False
        if stream_subjects["B"].intersection(stream_subjects["C"]):
            return False

        return True
