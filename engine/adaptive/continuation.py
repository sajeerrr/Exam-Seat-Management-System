class ContinuationSearch:
    """Finds rooms and streams where a department is already established."""

    def department_rooms(self, context):
        rooms_by_department = {}

        for index, room in enumerate(context.room_allocations):
            for department in room.departments:
                rooms_by_department.setdefault(department, set()).add(index)

        return rooms_by_department

    def continuation_score(self, candidate, context):
        groups = {g.group_id: g for g in context.groups}
        rooms_by_department = self.department_rooms(context)
        score = 0

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if not group:
                continue

            existing_rooms = rooms_by_department.get(group.department, set())
            if candidate.room_index in existing_rooms:
                score += 1.0
            elif existing_rooms:
                score -= 0.75

        if not candidate.assignments:
            return 0

        return score / len(candidate.assignments)

    def new_fragment_count(self, candidate, context):
        groups = {g.group_id: g for g in context.groups}
        rooms_by_department = self.department_rooms(context)
        new_fragments = 0

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if not group:
                continue

            existing_rooms = rooms_by_department.get(group.department, set())
            if existing_rooms and candidate.room_index not in existing_rooms:
                new_fragments += 1

        return new_fragments

    def department_room_count_after(self, candidate, context):
        groups = {g.group_id: g for g in context.groups}
        rooms_by_department = {
            dept: set(room_indexes)
            for dept, room_indexes in self.department_rooms(context).items()
        }

        for assignment in candidate.assignments:
            group = groups.get(assignment.group_id)
            if not group:
                continue
            rooms_by_department.setdefault(group.department, set()).add(
                candidate.room_index
            )

        return {
            department: len(room_indexes)
            for department, room_indexes in rooms_by_department.items()
        }
