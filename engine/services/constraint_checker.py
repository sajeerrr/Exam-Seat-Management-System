class ConstraintChecker:

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def can_add_department_to_room(
        room_alloc, incoming_dept: str, is_fallback_pass: bool = False
    ) -> bool:
        if hasattr(room_alloc, "can_add_department"):
            return room_alloc.can_add_department(
                incoming_dept, is_fallback_pass
            )
        return True