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

print("=" * 80)
print("DJANGO -> ENGINE ADAPTER TEST")
print("=" * 80)


# Test classrooms

classrooms = get_engine_classrooms()

print("\nCLASSROOMS")
print("-" * 80)

print(f"Classrooms converted: {len(classrooms)}")

for classroom in classrooms[:10]:
    print(f"{classroom.room_no:<15} | " f"Capacity: {classroom.capacity:<3}")


# Test one exam

exam = (
    Exam.objects.select_related("subject")
    .filter(subject__subject_code="23CET601")
    .first()
)

if exam is None:
    raise RuntimeError("Exam 23CET601 was not found.")


students = get_engine_students(exam)


print("\nEXAM")
print("-" * 80)

print(f"Subject:  {exam.subject.subject_code}")
print(f"Name:     {exam.subject.subject_name}")
print(f"Date:     {exam.exam_date}")
print(f"Session:  {exam.session}")
print(f"Students: {len(students)}")


print("\nFIRST 10 ENGINE STUDENTS")
print("-" * 80)

for student in students[:10]:
    print(
        f"{student.roll_no:<15} | "
        f"{student.name:<30} | "
        f"{student.department:<5} | "
        f"S{student.semester} | "
        f"Section {student.section}"
    )


print("\n" + "=" * 80)
print("ADAPTER TEST PASSED")
print("=" * 80)
