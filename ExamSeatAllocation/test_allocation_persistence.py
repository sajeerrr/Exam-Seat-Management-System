import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.models import (
    Allocation,
    Exam,
)

from exam_allocator.services.engine_adapter import (
    get_engine_students,
    get_engine_classrooms,
)

from exam_allocator.services.allocation_persistence import (
    save_seat_plan,
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
print("FULL DJANGO -> ENGINE -> DJANGO ALLOCATION TEST")
print("=" * 90)


# ---------------------------------------------------------
# 1. Get exam
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

print(f"{exam.subject.subject_code} | " f"{exam.subject.subject_name}")

print(f"{exam.exam_date} | {exam.session}")


# ---------------------------------------------------------
# 2. Get Django data
# ---------------------------------------------------------

students = get_engine_students(exam)

classrooms = get_engine_classrooms()

print("\nINPUT")
print("-" * 90)

print(f"Students:    {len(students)}")
print(f"Classrooms:  {len(classrooms)}")


# ---------------------------------------------------------
# 3. Build groups
# ---------------------------------------------------------

groups = GroupBuilder().build(students)

print(f"Groups:      {len(groups)}")

for group in groups:
    print(f"  {group.group_id} | " f"{group.strength} students")


# ---------------------------------------------------------
# 4. Build engine context
# ---------------------------------------------------------

room_allocations = [RoomAllocation(classroom=room) for room in classrooms]

remaining_pool = RemainingPool()

context = AllocationContext(
    groups=groups,
    room_allocations=room_allocations,
    remaining_pool=remaining_pool,
)


# ---------------------------------------------------------
# 5. Execute engine
# ---------------------------------------------------------

print("\nRUNNING ENGINE")
print("-" * 90)

service = AllocationService()

context, seat_plan = service.execute(context)

print(f"Engine generated {len(seat_plan.seats)} seats.")


# ---------------------------------------------------------
# 6. Save to Django
# ---------------------------------------------------------

print("\nSAVING TO DJANGO")
print("-" * 90)

allocations = save_seat_plan(
    exam,
    seat_plan,
)

print(f"Saved {len(allocations)} allocations.")


# ---------------------------------------------------------
# 7. Verify database
# ---------------------------------------------------------

database_allocations = (
    Allocation.objects.filter(exam=exam)
    .select_related(
        "registration__student",
        "room",
    )
    .order_by(
        "room__room_number",
        "bench_number",
        "seat_number",
    )
)

count = database_allocations.count()

print("\nDATABASE VERIFICATION")
print("-" * 90)

print(f"Allocations in database: {count}")

assert count == len(students)

print("✓ Allocation count matches student count")


# ---------------------------------------------------------
# 8. Verify students
# ---------------------------------------------------------

student_ids = [
    allocation.registration.student_id for allocation in database_allocations
]

assert len(student_ids) == len(set(student_ids))

print("✓ Every student has exactly one allocation")


# ---------------------------------------------------------
# 9. Verify physical seats
# ---------------------------------------------------------

physical_seats = [
    (
        allocation.room_id,
        allocation.bench_number,
        allocation.seat_number,
    )
    for allocation in database_allocations
]

assert len(physical_seats) == len(set(physical_seats))

print("✓ No duplicate physical seats")


# ---------------------------------------------------------
# 10. Display first 20
# ---------------------------------------------------------

print("\nFIRST 20 DATABASE ALLOCATIONS")
print("-" * 90)

for allocation in database_allocations[:20]:

    student = allocation.registration.student

    print(
        f"{student.roll_number:<15} | "
        f"{student.student_name:<30} | "
        f"Room {allocation.room.room_number:<8} | "
        f"Bench {allocation.bench_number:<2} | "
        f"Seat {allocation.seat_number}"
    )


print("\n" + "=" * 90)
print("FULL ALLOCATION PERSISTENCE TEST PASSED")
print("=" * 90)
