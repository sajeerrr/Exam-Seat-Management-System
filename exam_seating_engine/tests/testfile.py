from exam_seating_engine.tests.sample_data import students, classrooms
from exam_seating_engine.engine.group_builder import GroupBuilder
from exam_seating_engine.engine.sorter import GroupSorter
from exam_seating_engine.engine.primary_allocator import PrimaryAllocator

# Build groups
builder = GroupBuilder()
groups = builder.build(students)

# Sort groups
sor = GroupSorter()
groups = sor.sort(groups)

# Allocate
allocator = PrimaryAllocator()
room_allocations, remaining_pool = allocator.allocate(
    groups,
    classrooms
)

# Print Results
print("\nROOM ALLOCATIONS")
print("=" * 50)

for room in room_allocations:
    print(f"\n{room.classroom.room_no}")

    for allocation in room.allocations:
        g = allocation.group

        print(
            f"{g.department}{g.semester}{g.section} "
            f"{allocation.allocated_count}"
        )

print("\nREMAINING POOL")
print("=" * 50)

for group in remaining_pool.groups:
    print(
        f"{group.department}{group.semester}{group.section} "
        f"{group.remaining_count}"
    )