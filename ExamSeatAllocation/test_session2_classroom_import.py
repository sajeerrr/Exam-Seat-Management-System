import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.models import AllocationSession, Room
from exam_allocator.parsers.classroom_parser import parse_classroom_excel
from exam_allocator.services.import_service import import_classrooms

FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Class.xlsx"

session = AllocationSession.objects.get(session_id=2)

result = parse_classroom_excel(FILE)
stats = import_classrooms(result, session)

print("=" * 80)
print("SESSION 2 CLASSROOM IMPORT TEST")
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
print("Rooms:", Room.objects.filter(session=session).count())

print("\nROOMS")
print("-" * 80)

for room in Room.objects.filter(session=session):
    print(
        f"{room.room_number:12} | "
        f"Capacity: {room.capacity:2} | "
        f"Benches: {room.benches:2} | "
        f"Building: {room.building}"
    )
