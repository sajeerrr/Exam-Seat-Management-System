import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.parsers.classroom_parser import (
    parse_classroom_excel,
)

from exam_allocator.services.import_service import (
    import_classrooms,
)

from exam_allocator.models import AllocationSession, Room

FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Class.xlsx"


result = parse_classroom_excel(FILE)

session = AllocationSession.objects.get(session_id=1)

stats = import_classrooms(result, session)


print("=" * 80)
print("CLASSROOM DATABASE IMPORT TEST")
print("=" * 80)

print("\nIMPORT RESULTS")
print("-" * 80)

for key, value in stats.items():
    print(f"{key}: {value}")


print("\nDATABASE COUNTS")
print("-" * 80)

print(f"Rooms: {session.rooms.count()}")


print("\nROOMS")
print("-" * 80)

for room in session.rooms.all():

    print(
        f"{room.room_number:12} | "
        f"Capacity: {room.capacity:2} | "
        f"Benches: {room.benches:2} | "
        f"Building: {room.building}"
    )
