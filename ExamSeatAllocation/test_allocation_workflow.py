import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.models import Allocation
from exam_allocator.services.allocation_workflow import (
    run_allocation,
)

print("=" * 90)
print("UNIFIED ALLOCATION WORKFLOW TEST")
print("=" * 90)


# ---------------------------------------------------------
# Find the exam
# ---------------------------------------------------------

from exam_allocator.models import Exam

exam = (
    Exam.objects.select_related("subject")
    .filter(subject__subject_code="23CET601")
    .first()
)

if exam is None:
    raise RuntimeError("Exam 23CET601 was not found.")


print("\nEXAM")
print("-" * 90)

print(f"ID:       {exam.exam_id}")

print(f"Subject:  {exam.subject.subject_code}")

print(f"Name:     {exam.subject.subject_name}")

print(f"Date:     {exam.exam_date}")

print(f"Session:  {exam.session}")


# ---------------------------------------------------------
# Run entire workflow
# ---------------------------------------------------------

print("\nRUNNING UNIFIED WORKFLOW")
print("-" * 90)

result = run_allocation(exam.exam_id)


# ---------------------------------------------------------
# Display result
# ---------------------------------------------------------

print("\nWORKFLOW RESULT")
print("-" * 90)

print(f"Students:       {len(result['students'])}")

print(f"Classrooms:     {len(result['classrooms'])}")

print(f"Groups:          {len(result['groups'])}")

print(f"Engine seats:   {len(result['seat_plan'].seats)}")

print(f"Django records: {len(result['allocations'])}")


# ---------------------------------------------------------
# Verify database
# ---------------------------------------------------------

database_count = Allocation.objects.filter(exam=exam).count()

print("\nDATABASE")
print("-" * 90)

print(f"Allocation records: {database_count}")

assert database_count == len(result["students"])

print("✓ Database count matches students")


# ---------------------------------------------------------
# Show sample allocations
# ---------------------------------------------------------

print("\nSAMPLE ALLOCATIONS")
print("-" * 90)

allocations = (
    Allocation.objects.filter(exam=exam)
    .select_related(
        "registration__student",
        "room",
    )
    .order_by(
        "room__room_number",
        "bench_number",
        "seat_number",
    )[:10]
)

for allocation in allocations:

    student = allocation.registration.student

    print(
        f"{student.roll_number:<15} | "
        f"{student.student_name:<30} | "
        f"Room {allocation.room.room_number:<8} | "
        f"Bench {allocation.bench_number:<2} | "
        f"Seat {allocation.seat_number}"
    )


print("\n" + "=" * 90)
print("UNIFIED ALLOCATION WORKFLOW PASSED")
print("=" * 90)
