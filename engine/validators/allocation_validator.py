from engine.models.validation_result import ValidationResult


class AllocationValidator:

    def validate(self, context):
        result = ValidationResult()
        self.validate_duplicates(context, result)
        self.validate_capacity(context, result)
        self.validate_streams(context, result)
        self.validate_remaining_pool(context, result)
        return result
    

    def validate_duplicates(self, context, result):
        allocated = set()
        for room in context.room_allocations:
            for allocation in room.allocations:
                for student in allocation.students:
                    if student.register_no in allocated:
                        result.add_error(
                            f"Duplicate student: {student.register_no}"
                        )

                    allocated.add(student.register_no)
    

    def validate_capacity(self, context, result):
        for room in context.room_allocations:
            if room.used_capacity > room.classroom.capacity:
                result.add_error(
                    f"{room.classroom.room_no} exceeds capacity"
                )
    

    def validate_streams(self, context, result):
        for room in context.room_allocations:
            for stream in ("A", "B", "C"):
                allocation = room.streams[stream]
                if allocation is None:
                    continue
                if allocation.allocated_count > room.stream_capacity:
                    result.add_error(
                        f"{room.classroom.room_no}-{stream} exceeded stream capacity"
                    )


    def validate_remaining_pool(self, context, result):
        for group in context.remaining_pool.groups:
            if group.remaining_count == 0:
                result.add_warning(
                    f"{group.group_id} unnecessarily remained in pool"
                )