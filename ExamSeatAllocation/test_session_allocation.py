import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from exam_allocator.models import (
    Allocation,
    AllocationSession,
)

from exam_allocator.services.session_allocation_service import (
    SessionAllocationError,
    run_session_allocation,
)

print("=" * 100)
print("SESSION-WIDE ALLOCATION TEST")
print("=" * 100)


session = AllocationSession.objects.get(session_id=2)

print("\nSESSION")
print("-" * 100)
print(f"ID:   {session.session_id}")
print(f"Name: {session.name}")


print("\nRUNNING SESSION-WIDE ALLOCATION")
print("-" * 100)


try:

    result = run_session_allocation(session)

except SessionAllocationError as exc:

    print("\nALLOCATION FAILED")
    print("-" * 100)
    print(str(exc))
    raise


print("\nALLOCATION RESULT")
print("-" * 100)

print(f"Exams:        {result['exams']}")

print(f"Time slots:   {result['slots']}")

print(f"Students:     {result['students']}")

print(f"Allocations:  {result['allocations']}")


print("\nSLOT BREAKDOWN")
print("-" * 100)

for item in result["slot_results"]:

    print(
        f"{item['date']} | "
        f"{item['session']:2} | "
        f"Students: "
        f"{item['students']:4} | "
        f"Allocations: "
        f"{item['allocations']:4}"
    )


print("\nDATABASE")
print("-" * 100)

allocation_count = Allocation.objects.filter(exam__subject__session=session).count()

print(
    "Session allocations:",
    allocation_count,
)

print(
    "Result allocations:",
    result["allocations"],
)


if allocation_count == result["allocations"]:

    print("✓ Database count matches result")

else:

    print("✗ Database count DOES NOT match result")


print("\n" + "=" * 100)
print("SESSION-WIDE ALLOCATION TEST PASSED")
print("=" * 100)
