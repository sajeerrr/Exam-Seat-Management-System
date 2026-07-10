from ..models.student import Student
from ..models.group import Group
from ..models.classroom import Classroom
from ..models.room_allocation import RoomAllocation
from ..models.remaining_pool import RemainingPool
from ..context.allocation_context import AllocationContext
from ..engine.primary_allocator import PrimaryAllocator


def build_group(name, count):

    students = []

    for i in range(count):
        students.append(
            Student(
                register_no=f"{name}{i+1:03}",
                name=f"Student{i+1}",
                department=name,
                semester=6,
                section="A",
                subject_code="SUB101",
                subject_name="Subject",
                exam_date="2026-01-01",
                session="FN",
            )
        )

    group = Group(
        group_id=name,
        department=name,
        semester=6,
        section="A",
        subject_code="SUB101",
        subject_name="Subject",
        exam_date="2026-01-01",
        session="FN",
    )

    group.students = students
    return group


rooms = [
    Classroom("101", 5, 3),
    Classroom("102", 5, 3),
    Classroom("103", 5, 3),
]

room_allocations = [
    RoomAllocation(classroom=r)
    for r in rooms
]

groups = [
    build_group("CSE", 72),
    build_group("AIDS", 68),
    build_group("ECE", 60),
    build_group("EEE", 54),
    build_group("MECH", 48),
    build_group("CIVIL", 36),
    build_group("IT", 42),
    build_group("CHEM", 30),
]

groups.sort(
    key=lambda g: g.strength,
    reverse=True
)

context = AllocationContext(
    groups=groups,
    room_allocations=room_allocations,
    remaining_pool=RemainingPool(),
)

PrimaryAllocator().execute(context)

for room in context.room_allocations:
    print("=" * 40)
    print(room.classroom.room_no)

    for allocation in room.allocations:
        print(
            allocation.stream,
            allocation.group.group_id,
            allocation.allocated_count,
        )

print("\nRemaining Pool")

for group in context.remaining_pool.groups:
    print(
        group.group_id,
        group.remaining_count,
    )