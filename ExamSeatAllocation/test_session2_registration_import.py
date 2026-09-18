import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.models import (
    AllocationSession,
    ExamRegistration,
)
from exam_allocator.services.registration_service import (
    create_all_exam_registrations,
)

print("=" * 100)
print("EXAM REGISTRATION DATABASE IMPORT TEST")
print("=" * 100)

session = AllocationSession.objects.get(session_id=2)

print("\nSESSION")
print("-" * 100)
print(f"ID:   {session.session_id}")
print(f"Name: {session.name}")

result = create_all_exam_registrations(session)


print("\nIMPORT RESULTS")
print("-" * 100)

print(f"Registrations created:  " f"{result['total_created']}")

print(f"Registrations existing: " f"{result['total_existing']}")

print(f"Auto-resolved exams:     " f"{result['auto_resolved_exams']}")

print(f"Mapping required:        " f"{result['mapping_required_exams']}")

print(f"Unresolved exams:        " f"{result['unresolved_exams']}")


print("\nDATABASE COUNTS")
print("-" * 100)

print(
    "Exam registrations:",
    ExamRegistration.objects.count(),
)


print("\nREGISTRATION BREAKDOWN")
print("-" * 100)

for item in result["results"]:

    if item["status"] == "AUTO_RESOLVED":

        print(
            f"{item['subject_code']:30} | "
            f"Created: "
            f"{item['registrations_created']:3} | "
            f"Existing: "
            f"{item['registrations_existing']:3}"
        )

    else:

        print(
            f"{item['subject_code']:30} | "
            f"{item['status']:20} | "
            f"{item['message']}"
        )
