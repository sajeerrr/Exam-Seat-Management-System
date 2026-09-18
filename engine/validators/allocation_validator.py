from engine.models.validation_result import ValidationResult


class AllocationValidator:

    def validate(self, context):
        result = ValidationResult()
        self.validate_duplicates(context, result)
        self.validate_capacity(context, result)
        self.validate_streams(context, result)
        self.validate_adjacent_conflicts(context, result)
        self.validate_unallocated_groups(context, result)
        return result

    def validate_duplicates(self, context, result):
        allocated = set()
        for room in context.room_allocations:
            for stream in room.streams.values():
                for student in stream.students:
                    if student.register_no in allocated:
                        result.add_error(f"Duplicate student: {student.register_no}")
                    allocated.add(student.register_no)

    def validate_capacity(self, context, result):
        for room in context.room_allocations:
            if room.used_capacity > room.classroom.capacity:
                result.add_error(f"{room.classroom.room_no} exceeds capacity")

    def validate_streams(self, context, result):
        for room in context.room_allocations:
            for stream_name, stream in room.streams.items():
                if len(stream.students) > stream.capacity:
                    result.add_error(
                        f"{room.classroom.room_no}-{stream_name} exceeded stream capacity"
                    )

    def validate_adjacent_conflicts(self, context, result):
        """Ensures adjacent streams A-B and B-C never share subjects."""
        for room in context.room_allocations:
            subjs_by_stream = {
                name: stream.subject_codes
                for name, stream in room.streams.items()
            }

            if subjs_by_stream.get("A") and subjs_by_stream.get("B"):
                overlap = subjs_by_stream["A"].intersection(subjs_by_stream["B"])
                if overlap:
                    result.add_error(f"Room {room.classroom.room_no}: Adjacent streams A and B share subject {overlap}")

            if subjs_by_stream.get("B") and subjs_by_stream.get("C"):
                overlap = subjs_by_stream["B"].intersection(subjs_by_stream["C"])
                if overlap:
                    result.add_error(f"Room {room.classroom.room_no}: Adjacent streams B and C share subject {overlap}")

    def validate_unallocated_groups(self, context, result):
        for group in context.groups:
            if group.remaining_count > 0:
                result.add_error(
                    f"{group.group_id} has {group.remaining_count} unallocated student(s)"
                )
