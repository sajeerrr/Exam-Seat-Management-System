import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from exam_allocator.models import AllocationSession, Department, Class, Student
from exam_allocator.parsers.student_parser import parse_student_excel
from exam_allocator.services.import_service import import_students

FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Students.xlsx"

session = AllocationSession.objects.get(session_id=2)

result = parse_student_excel(FILE)
stats = import_students(result, session)

print("=" * 80)
print("SESSION 2 STUDENT IMPORT TEST")
print("=" * 80)

print("\nSESSION")
print("-" * 80)
print(session.session_id, "|", session.name)

print("\nIMPORT RESULTS")
print("-" * 80)

for key, value in stats.items():
    print(f"{key}: {value}")

print("\nSESSION 2 COUNTS")
print("-" * 80)
print("Departments:", Department.objects.filter(session=session).count())
print("Classes:", Class.objects.filter(department__session=session).count())
print(
    "Students:",
    Student.objects.filter(student_class__department__session=session).count(),
)
