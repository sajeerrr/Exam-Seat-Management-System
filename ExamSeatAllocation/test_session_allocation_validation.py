import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from django.db.models import Count, F

from exam_allocator.models import (
    Allocation,
    AllocationSession,
    ExamRegistration,
)

print("=" * 100)
print("SESSION-WIDE ALLOCATION VALIDATION")
print("=" * 100)


# ---------------------------------------------------------
# SESSION
# ---------------------------------------------------------

session = AllocationSession.objects.get(session_id=2)

allocations = Allocation.objects.filter(exam__subject__session=session).select_related(
    "exam",
    "exam__subject",
    "registration",
    "registration__student",
    "room",
)


print("\nSESSION")
print("-" * 100)

print(f"ID:   {session.session_id}")

print(f"Name: {session.name}")


# ---------------------------------------------------------
# BASIC COUNTS
# ---------------------------------------------------------

registration_count = ExamRegistration.objects.filter(
    exam__subject__session=session
).count()

allocation_count = allocations.count()


print("\nBASIC COUNTS")
print("-" * 100)

print(f"Registrations: {registration_count}")

print(f"Allocations:   {allocation_count}")


# ---------------------------------------------------------
# 1. DUPLICATE SEATS
# ---------------------------------------------------------

print("\n1. DUPLICATE SEATS")
print("-" * 100)

duplicate_seats = (
    allocations.values(
        "exam",
        "room",
        "bench_number",
        "seat_number",
    )
    .annotate(count=Count("allocation_id"))
    .filter(count__gt=1)
)

duplicate_seat_count = duplicate_seats.count()

print(
    "Duplicate seat positions:",
    duplicate_seat_count,
)

if duplicate_seat_count == 0:
    print("✓ No duplicate seats")
else:
    print("✗ Duplicate seats found")

    for item in duplicate_seats[:10]:
        print(
            f"Exam {item['exam']} | "
            f"Room {item['room']} | "
            f"Bench {item['bench_number']} | "
            f"Seat {item['seat_number']} | "
            f"Count {item['count']}"
        )


# ---------------------------------------------------------
# 2. ROOM CAPACITY
# ---------------------------------------------------------

print("\n2. ROOM CAPACITY")
print("-" * 100)

room_overflows = []

room_counts = allocations.values(
    "exam",
    "room",
).annotate(count=Count("allocation_id"))

rooms = {room.room_id: room for room in session.rooms.all()}


for item in room_counts:

    room = rooms.get(item["room"])

    if room is None:
        continue

    if item["count"] > room.capacity:

        room_overflows.append(
            (
                room.room_number,
                item["exam"],
                item["count"],
                room.capacity,
            )
        )


print(
    "Room capacity violations:",
    len(room_overflows),
)

if not room_overflows:

    print("✓ No room exceeds capacity")

else:

    print("✗ Room capacity violations found")

    for item in room_overflows:

        print(f"Room {item[0]} | " f"Exam {item[1]} | " f"{item[2]}/{item[3]}")


# ---------------------------------------------------------
# 3. DUPLICATE STUDENT PER EXAM
# ---------------------------------------------------------

print("\n3. DUPLICATE STUDENTS")
print("-" * 100)

duplicate_students = (
    allocations.values(
        "exam",
        "registration__student",
    )
    .annotate(count=Count("allocation_id"))
    .filter(count__gt=1)
)

duplicate_student_count = duplicate_students.count()

print(
    "Students with multiple seats:",
    duplicate_student_count,
)

if duplicate_student_count == 0:

    print("✓ No student has multiple seats")

else:

    print("✗ Duplicate student allocations found")

    for item in duplicate_students[:10]:

        print(
            f"Exam {item['exam']} | "
            f"Student {item['registration__student']} | "
            f"Count {item['count']}"
        )


# ---------------------------------------------------------
# 4. REGISTRATION INTEGRITY
# ---------------------------------------------------------

print("\n4. REGISTRATION INTEGRITY")
print("-" * 100)

invalid_registrations = allocations.exclude(registration__exam=F("exam")).count()


print(
    "Invalid registrations:",
    invalid_registrations,
)

if invalid_registrations == 0:

    print("✓ Every allocation references " "the correct exam registration")

else:

    print("✗ Invalid registration references found")


# ---------------------------------------------------------
# 5. SESSION ISOLATION
# ---------------------------------------------------------

print("\n5. SESSION ISOLATION")
print("-" * 100)

wrong_session_exams = allocations.exclude(exam__subject__session=session).count()

wrong_session_registrations = allocations.exclude(
    registration__exam__subject__session=session
).count()

wrong_session_rooms = allocations.exclude(room__session=session).count()


print("Wrong-session exams:", wrong_session_exams)

print("Wrong-session registrations:", wrong_session_registrations)

print("Wrong-session rooms:", wrong_session_rooms)


if (
    wrong_session_exams == 0
    and wrong_session_registrations == 0
    and wrong_session_rooms == 0
):

    print("✓ Session isolation is correct")

else:

    print("✗ Session isolation violation found")


# ---------------------------------------------------------
# 6. SEAT NUMBER VALIDATION
# ---------------------------------------------------------

print("\n6. SEAT POSITION VALIDATION")
print("-" * 100)

invalid_seat_positions = allocations.filter(bench_number__lt=1).count()

invalid_seat_positions += allocations.filter(bench_number__gt=15).count()

invalid_seat_positions += allocations.filter(seat_number__lt=1).count()

invalid_seat_positions += allocations.filter(seat_number__gt=3).count()


print("Invalid seat positions:", invalid_seat_positions)

if invalid_seat_positions == 0:

    print("✓ All seats have valid " "bench/seat positions")

else:

    print("✗ Invalid seat positions found")


# ---------------------------------------------------------
# 7. ALLOCATION COMPLETENESS
# ---------------------------------------------------------

print("\n7. ALLOCATION COMPLETENESS")
print("-" * 100)

registrations_without_allocation = (
    ExamRegistration.objects.filter(exam__subject__session=session)
    .exclude(allocation__isnull=False)
    .count()
)


print("Registrations without allocation:", registrations_without_allocation)

if registrations_without_allocation == 0:

    print("✓ Every registration has an allocation")

else:

    print("⚠ Some registrations do not have " "an allocation")


# ---------------------------------------------------------
# FINAL RESULT
# ---------------------------------------------------------

print("\n" + "=" * 100)

failures = (
    duplicate_seat_count
    + len(room_overflows)
    + duplicate_student_count
    + invalid_registrations
    + wrong_session_exams
    + wrong_session_registrations
    + wrong_session_rooms
    + invalid_seat_positions
)


if failures == 0:

    print("✓ ALLOCATION VALIDATION PASSED")

    print("All structural allocation checks passed.")

else:

    print("✗ ALLOCATION VALIDATION FAILED")

    print(f"Total structural failures: {failures}")


print("=" * 100)
