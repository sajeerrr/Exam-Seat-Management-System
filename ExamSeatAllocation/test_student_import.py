import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.parsers.student_parser import (
    parse_student_excel,
)

from exam_allocator.services.import_service import (
    import_students,
)

from exam_allocator.models import (
    AllocationSession,
    Department,
    Class,
    Student,
)

FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Students.xlsx"


result = parse_student_excel(FILE)

session = AllocationSession.objects.get(session_id=1)

stats = import_students(result, session)


print("=" * 80)
print("STUDENT DATABASE IMPORT TEST")
print("=" * 80)

print("\nIMPORT RESULTS")
print("-" * 80)

for key, value in stats.items():
    print(f"{key}: {value}")


print("\nDATABASE COUNTS")
print("-" * 80)

print(f"Departments: {session.departments.count()}")
print(f"Classes: {Class.objects.filter(department__session=session).count()}")
print(
    f"Students: {Student.objects.filter(student_class__department__session=session).count()}"
)


print("\nSAMPLE STUDENTS")
print("-" * 80)

for student in Student.objects.filter(
    student_class__department__session=session
).select_related("student_class", "student_class__department",)[:10]:

    print(
        f"{student.roll_number:15} | "
        f"{student.student_name:30} | "
        f"{student.student_class.class_name:20} | "
        f"{student.student_class.department.department_code}"
    )
