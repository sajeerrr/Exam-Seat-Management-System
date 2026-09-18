import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.parsers.timetable_parser import (
    parse_timetable_excel,
)

from exam_allocator.services.import_service import (
    import_timetable,
)

from exam_allocator.models import AllocationSession, Subject, Exam, ExamTarget

FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Timetable.xlsx"


result = parse_timetable_excel(FILE)
session = AllocationSession.objects.get(session_id=2)
stats = import_timetable(result, session)


print("=" * 100)
print("TIMETABLE DATABASE IMPORT TEST")
print("=" * 100)

print("\nIMPORT RESULTS")
print("-" * 100)

for key, value in stats.items():
    print(f"{key}: {value}")


print("\nDATABASE COUNTS")
print("-" * 100)

print("Subjects:", Subject.objects.filter(session=session).count())

print("Exams:", Exam.objects.filter(subject__session=session).count())

print("Targets:", ExamTarget.objects.filter(exam__subject__session=session).count())


print("\nEXAMS")
print("-" * 100)

for exam in (
    Exam.objects.filter(subject__session=session)
    .select_related("subject")
    .order_by(
        "exam_date",
        "session",
        "exam_id",
    )
):
    print(
        f"{exam.exam_date} | "
        f"{exam.session} | "
        f"S{exam.subject.semester:<2} | "
        f"{exam.subject.subject_code:<30} | "
        f"{exam.subject.subject_name}"
    )
