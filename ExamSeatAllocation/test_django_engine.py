import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.models import Exam

from exam_allocator.services.engine_adapter import (
    get_engine_students,
    get_engine_classrooms,
)

from engine.builders.group_builder import (
    GroupBuilder,
)

from engine.context.allocation_context import (
    AllocationContext,
)

from engine.models.room_allocation import (
    RoomAllocation,
)

from engine.models.remaining_pool import (
    RemainingPool,
)

from engine.services.allocation_service import (
    AllocationService,
)

print("=" * 90)
print("DJANGO -> SAJEER ENGINE INTEGRATION TEST")
print("=" * 90)


# ---------------------------------------------------------
# 1. Get one real exam from Django
# ---------------------------------------------------------

exam = (
    Exam.objects.select_related("subject")
    .filter(subject__subject_code="23CET601")
    .first()
)

if exam is None:
    raise RuntimeError("Exam 23CET601 was not found.")


print("\nEXAM")
print("-" * 90)

print(f"Subject:  {exam.subject.subject_code}")

print(f"Name:     {exam.subject.subject_name}")

print(f"Date:     {exam.exam_date}")

print(f"Session:  {exam.session}")


# ---------------------------------------------------------
# 2. Convert Django registrations
# ---------------------------------------------------------

students = get_engine_students(exam)

print("\nSTUDENTS")
print("-" * 90)

print(f"Django registrations → " f"{len(students)} Engine Students")


# ---------------------------------------------------------
# 3. Convert Django rooms
# ---------------------------------------------------------

classrooms = get_engine_classrooms()

print(f"Django rooms → " f"{len(classrooms)} Engine Classrooms")


# ---------------------------------------------------------
# 4. Build groups
# ---------------------------------------------------------

groups = GroupBuilder().build(students)

print("\nGROUPS")
print("-" * 90)

print(f"Groups created: {len(groups)}")

for group in groups:

    print(
        f"{group.group_id:<55} "
        f"| {group.strength:3} students "
        f"| Sections: {group.section}"
    )


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


print("\nCONTEXT")
print("-" * 90)

print(f"Room allocations: {len(room_allocations)}")

print(f"Remaining pool:   " f"{len(remaining_pool.groups)} groups")


# ---------------------------------------------------------
# 6. Run Sajee­r's existing engine
# ---------------------------------------------------------

print("\nRUNNING ALLOCATION ENGINE...")
print("-" * 90)

service = AllocationService()

context, seat_plan = service.execute(context)


print("ENGINE EXECUTION COMPLETED")


# ---------------------------------------------------------
# 7. Inspect result
# ---------------------------------------------------------

print("\nSEAT PLAN")
print("-" * 90)

print(f"Seat plan type: " f"{type(seat_plan).__name__}")

print(f"Seats generated: " f"{len(seat_plan.seats)}")


# ---------------------------------------------------------
# 8. Print sample seats
# ---------------------------------------------------------

print("\nFIRST 30 SEATS")
print("-" * 90)

for seat in seat_plan.seats[:30]:

    student = seat.student

    print(
        f"Room {seat.room_no:<8} | "
        f"Bench {seat.bench_no:<2} | "
        f"Stream {seat.stream} | "
        f"{student.roll_no:<15} | "
        f"{student.name}"
    )


print("\n" + "=" * 90)
print("DJANGO -> ENGINE INTEGRATION TEST PASSED")
print("=" * 90)


print("\nVALIDATING SEAT PLAN")
print("-" * 90)

# 1. Correct number of seats
assert len(seat_plan.seats) == len(students)

print(f"✓ Seat count: {len(seat_plan.seats)}")


# 2. Check students
student_rolls = [seat.student.roll_no for seat in seat_plan.seats]

assert len(student_rolls) == len(set(student_rolls))

print(f"✓ Unique students: " f"{len(set(student_rolls))}")


# 3. Check rooms
django_room_numbers = {
    room.room_number
    for room in (
        __import__("exam_allocator.models", fromlist=["Room"]).Room.objects.all()
    )
}

engine_room_numbers = {seat.room_no for seat in seat_plan.seats}

assert engine_room_numbers <= django_room_numbers

print(f"✓ Valid rooms: " f"{len(engine_room_numbers)}")


# 4. Check benches
assert all(1 <= seat.bench_no <= 15 for seat in seat_plan.seats)

print("✓ All bench numbers are 1-15")


# 5. Check streams
assert all(seat.stream in {"A", "B", "C"} for seat in seat_plan.seats)

print("✓ All streams are A/B/C")


# 6. Check physical seat uniqueness
physical_seats = [
    (
        seat.room_no,
        seat.bench_no,
        seat.stream,
    )
    for seat in seat_plan.seats
]

assert len(physical_seats) == len(set(physical_seats))

print("✓ No duplicate physical seats")


print("\nSEAT PLAN VALIDATION PASSED")
