from collections import defaultdict

from django.db import transaction

from exam_allocator.models import (
    Allocation,
    Exam,
    ExamRegistration,
    Room,
)

from exam_allocator.services.engine_adapter import (
    django_room_to_engine_classroom,
    get_engine_students,
)

from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.room_allocation import RoomAllocation
from engine.models.remaining_pool import RemainingPool
from engine.services.allocation_service import AllocationService


class SessionAllocationError(Exception):
    """Raised when a session-wide allocation cannot be completed."""


def _exam_key(exam):
    """
    Create the identifier used to match an engine student
    back to its Django Exam.
    """

    return (
        exam.subject.subject_code,
        exam.exam_date.strftime("%d-%m-%Y"),
        exam.session,
    )


def _build_exam_lookup(exams):
    """
    Build:

        (subject_code, date, session) -> Django Exam
    """

    return {_exam_key(exam): exam for exam in exams}


def _get_session_exams(session):
    return list(
        Exam.objects.select_related("subject")
        .prefetch_related("targets")
        .filter(subject__session=session)
        .order_by(
            "exam_date",
            "session",
            "exam_id",
        )
    )


def _get_session_rooms(session):
    rooms = Room.objects.filter(session=session).order_by("room_number")

    return list(rooms)


def _get_slot_students(exams):
    """
    Return all registered engine students grouped by:

        (exam_date, session)

    Every exam in the same date/session therefore participates
    in the same allocation problem.
    """

    slot_students = defaultdict(list)

    for exam in exams:

        students = get_engine_students(exam)

        key = (
            exam.exam_date,
            exam.session,
        )

        slot_students[key].extend(students)

    return slot_students


def _allocate_slot(
    session,
    slot,
    engine_students,
    rooms,
):
    """
    Run the allocation engine once for one examination slot.

    Example:

        2026-03-12 + FN

    All exams taking place during that slot are allocated
    together.
    """

    if not engine_students:
        return None

    groups = GroupBuilder().build(engine_students)

    if not groups:
        raise SessionAllocationError(
            f"No allocation groups could be created for {slot}."
        )

    room_allocations = [
        RoomAllocation(classroom=django_room_to_engine_classroom(room))
        for room in rooms
    ]

    if not room_allocations:
        raise SessionAllocationError(f"No classrooms are available for {slot}.")

    context = AllocationContext(
        groups=groups,
        room_allocations=room_allocations,
        remaining_pool=RemainingPool(),
    )

    try:
        service = AllocationService()

        context, seat_plan = service.execute(context)

    except Exception as exc:
        raise SessionAllocationError(
            f"Allocation engine failed for {slot}: {exc}"
        ) from exc

    if seat_plan is None:
        raise SessionAllocationError(
            f"Allocation engine returned no seat plan for {slot}."
        )

    generated_seats = len(seat_plan.seats)

    if generated_seats != len(engine_students):
        raise SessionAllocationError(
            f"{slot}: engine generated "
            f"{generated_seats} seats for "
            f"{len(engine_students)} students."
        )

    return seat_plan


@transaction.atomic
def save_session_seat_plan(
    session,
    seat_plan,
    exams,
    expected_students=None,
):
    """
    Save allocations for one examination time slot.

    Only the exams represented by this SeatPlan are replaced.
    Allocations belonging to other time slots remain untouched.
    """

    exam_lookup = _build_exam_lookup(exams)

    rooms = {room.room_number: room for room in Room.objects.filter(session=session)}

    registrations = {}
    reg_by_roll = {}

    for registration in ExamRegistration.objects.filter(
        exam__in=exams
    ).select_related(
        "student",
        "exam",
        "exam__subject",
    ):
        key = (
            registration.exam.subject.subject_code,
            registration.exam.exam_date.strftime("%d-%m-%Y"),
            registration.exam.session,
            registration.student.roll_number,
        )
        registrations[key] = registration
        reg_by_roll[(
            registration.exam.exam_date.strftime("%d-%m-%Y"),
            registration.exam.session,
            registration.student.roll_number,
        )] = registration

    allocations = []
    exams_in_this_slot = set()

    stream_to_seat_number = {
        "A": 1,
        "B": 2,
        "C": 3,
    }

    for seat in seat_plan.seats:

        room_no = seat.classroom.room_no

        if room_no not in rooms:
            raise SessionAllocationError(f"Engine generated unknown room: {room_no}")

        student = seat.student

        exam_key = (
            student.subject_code,
            student.exam_date,
            student.session,
        )

        exam = exam_lookup.get(exam_key)

        registration_key = (
            student.subject_code,
            student.exam_date,
            student.session,
            student.register_no,
        )

        registration = registrations.get(registration_key)
        if registration is None:
            registration = reg_by_roll.get((student.exam_date, student.session, student.register_no))

        if registration is None:
            raise SessionAllocationError(
                "Student is not registered for the expected exam: "
                f"{student.register_no} / "
                f"{student.subject_code}"
            )

        if exam is None:
            exam = registration.exam

        if seat.stream not in stream_to_seat_number:
            raise SessionAllocationError(f"Unknown engine stream: {seat.stream}")

        exams_in_this_slot.add(exam.exam_id)

        allocations.append(
            Allocation(
                registration=registration,
                exam=exam,
                room=rooms[room_no],
                bench_number=seat.bench_no,
                seat_number=stream_to_seat_number[seat.stream],
            )
        )

    # ── VALIDATION BEFORE SAVING ─────────────────────────────────
    from collections import defaultdict

    # 1. Check expected student count
    if expected_students is not None and len(allocations) < expected_students:
        raise SessionAllocationError(
            f"Under-allocation: only {len(allocations)} of {expected_students} expected students allocated."
        )

    # 2. No student allocated twice
    seen_regs = set()
    for a in allocations:
        if a.registration_id in seen_regs:
            raise SessionAllocationError(
                f"Duplicate student allocation: Registration ID {a.registration_id} ({a.registration.student.roll_number}) allocated more than once."
            )
        seen_regs.add(a.registration_id)

    # 3. Seat conflicts must be zero
    seen_positions = set()
    for a in allocations:
        pos = (a.room_id, a.bench_number, a.seat_number)
        if pos in seen_positions:
            raise SessionAllocationError(
                f"Seat conflict: Room {a.room.room_number}, Bench {a.bench_number}, Seat {a.seat_number} allocated multiple times."
            )
        seen_positions.add(pos)

    # 4. Room capacities must not be exceeded
    room_counts = defaultdict(int)
    for a in allocations:
        room_counts[a.room] += 1
    for r_obj, cnt in room_counts.items():
        if cnt > r_obj.capacity:
            raise SessionAllocationError(
                f"Room capacity exceeded in Room {r_obj.room_number}: {cnt} allocated > capacity {r_obj.capacity}."
            )

    # 5. Special subject rules: No same-subject students adjacent horizontally
    bench_grid = defaultdict(dict)
    for seat in seat_plan.seats:
        s_num = stream_to_seat_number.get(seat.stream, 0)
        bench_grid[(seat.classroom.room_no, seat.bench_no)][s_num] = seat.student

    for (r_no, b_no), seats_map in bench_grid.items():
        for s_idx in (1, 2):
            if s_idx in seats_map and (s_idx + 1) in seats_map:
                st1 = seats_map[s_idx]
                st2 = seats_map[s_idx + 1]
                if (st1.subject_category in ("ELECTIVE", "MINOR", "HONOURS") or
                    st2.subject_category in ("ELECTIVE", "MINOR", "HONOURS")):
                    if st1.subject_code.strip().upper() == st2.subject_code.strip().upper():
                        raise SessionAllocationError(
                            f"Special subject adjacency conflict in Room {r_no}, Bench {b_no}: "
                            f"Seat {s_idx} and Seat {s_idx + 1} both have same subject {st1.subject_code}."
                        )

    # Replace allocations ONLY for exams in this time slot.
    if exams_in_this_slot:
        Allocation.objects.filter(exam_id__in=exams_in_this_slot).delete()

    Allocation.objects.bulk_create(allocations)

    return allocations


@transaction.atomic
def run_session_allocation(session):
    """
    Generate allocations for every automatically registered
    student in an entire session.

    Exams are grouped by:

        exam date + exam session

    so all examinations taking place at the same time compete
    for the same classrooms.

    Each time slot is committed independently — a failure in
    one slot does not roll back allocations for other slots.
    """

    exams = _get_session_exams(session)

    if not exams:
        raise SessionAllocationError("This session contains no examinations.")

    rooms = _get_session_rooms(session)

    if not rooms:
        raise SessionAllocationError("This session contains no classrooms.")

    slot_students = _get_slot_students(exams)

    all_allocations = []

    slot_results = []
    slot_errors = []

    for slot in sorted(slot_students.keys()):

        students = slot_students[slot]

        slot_date, slot_session = slot

        slot_exams = [
            exam
            for exam in exams
            if (exam.exam_date == slot_date and exam.session == slot_session)
        ]

        try:
            seat_plan = _allocate_slot(
                session=session,
                slot=slot,
                engine_students=students,
                rooms=rooms,
            )

            if seat_plan is None:
                continue

            # Commit each slot in its own nested savepoint so a single
            # slot failure cannot roll back other successfully saved slots.
            with transaction.atomic():
                allocations = save_session_seat_plan(
                    session=session,
                    seat_plan=seat_plan,
                    exams=slot_exams,
                    expected_students=len(students),
                )

            all_allocations.extend(allocations)

            slot_results.append(
                {
                    "date": slot_date,
                    "session": slot_session,
                    "students": len(students),
                    "allocations": len(allocations),
                }
            )

        except (SessionAllocationError, Exception) as exc:
            slot_errors.append(f"{slot_date} {slot_session}: {exc}")
            continue

    if slot_errors and not all_allocations:
        raise SessionAllocationError(
            "All slots failed to allocate. Errors: " + "; ".join(slot_errors)
        )

    return {
        "session": session,
        "exams": len(exams),
        "slots": len(slot_results),
        "students": sum(result["students"] for result in slot_results),
        "allocations": len(all_allocations),
        "slot_results": slot_results,
        "slot_errors": slot_errors,
    }
