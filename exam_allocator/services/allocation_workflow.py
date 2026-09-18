from exam_allocator.models import Exam

from exam_allocator.services.engine_adapter import (
    get_engine_students,
    get_engine_classrooms,
)

from exam_allocator.services.allocation_persistence import (
    save_seat_plan,
)

from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.room_allocation import RoomAllocation
from engine.models.remaining_pool import RemainingPool
from engine.services.allocation_service import AllocationService


class AllocationWorkflowError(Exception):
    """Raised when an exam allocation cannot be completed."""


def run_allocation(exam_id):
    """
    Generate and save the seat allocation for one Django Exam.

    Pipeline:

        Django Exam
            ↓
        ExamRegistration
            ↓
        Engine Students
            ↓
        GroupBuilder
            ↓
        AllocationContext
            ↓
        Sajeer AllocationService
            ↓
        SeatPlan
            ↓
        Django Allocation
    """

    # ---------------------------------------------------------
    # 1. Load exam
    # ---------------------------------------------------------

    try:
        exam = Exam.objects.select_related(
            "subject",
            "subject__session",
        ).get(exam_id=exam_id)

    except Exam.DoesNotExist as exc:

        raise AllocationWorkflowError(f"Exam {exam_id} does not exist.") from exc

    session = exam.subject.session

    # ---------------------------------------------------------
    # 2. Convert Django registrations to engine students
    # ---------------------------------------------------------

    students = get_engine_students(exam)

    if not students:

        raise AllocationWorkflowError(
            f"No exam registrations found for " f"{exam.subject.subject_code}."
        )

    # ---------------------------------------------------------
    # 3. Convert ONLY this session's rooms
    # ---------------------------------------------------------

    classrooms = get_engine_classrooms(session)

    if not classrooms:

        raise AllocationWorkflowError(
            f"No classrooms are available for " f"session '{session.name}'."
        )

    # ---------------------------------------------------------
    # 4. Build merged groups
    # ---------------------------------------------------------

    groups = GroupBuilder().build(students)

    if not groups:

        raise AllocationWorkflowError("No allocation groups could be created.")

    # ---------------------------------------------------------
    # 5. Build engine context
    # ---------------------------------------------------------

    room_allocations = [RoomAllocation(classroom=room) for room in classrooms]

    remaining_pool = RemainingPool()

    context = AllocationContext(
        groups=groups,
        room_allocations=room_allocations,
        remaining_pool=remaining_pool,
    )

    # ---------------------------------------------------------
    # 6. Execute Sajeer's engine
    # ---------------------------------------------------------

    try:

        engine_service = AllocationService()

        context, seat_plan = engine_service.execute(context)

    except Exception as exc:

        raise AllocationWorkflowError(
            f"Allocation engine failed for " f"{exam.subject.subject_code}: {exc}"
        ) from exc

    if seat_plan is None:

        raise AllocationWorkflowError("Allocation engine returned no seat plan.")

    # ---------------------------------------------------------
    # 7. Validate basic result
    # ---------------------------------------------------------

    generated_seats = len(seat_plan.seats)

    if generated_seats != len(students):

        raise AllocationWorkflowError(
            f"Engine generated {generated_seats} seats "
            f"for {len(students)} registered students."
        )

    # ---------------------------------------------------------
    # 8. Save SeatPlan into Django
    # ---------------------------------------------------------

    try:

        allocations = save_seat_plan(
            exam,
            seat_plan,
        )

    except Exception as exc:

        raise AllocationWorkflowError(
            f"Could not save allocation for " f"{exam.subject.subject_code}: {exc}"
        ) from exc

    return {
        "exam": exam,
        "students": students,
        "classrooms": classrooms,
        "groups": groups,
        "seat_plan": seat_plan,
        "allocations": allocations,
    }
