from exam_seating_engine.tests.sample_data import groups, classrooms

from exam_seating_engine.models.room_allocation import RoomAllocation
from exam_seating_engine.models.remaining_pool import RemainingPool
from exam_seating_engine.models.allocation_context import AllocationContext

from exam_seating_engine.engine.primary_allocator import PrimaryAllocator


print("=" * 60)
print("INPUT GROUPS")
print("=" * 60)

for group in groups:
    print(
        f"{group.department}{group.semester}{group.section} "
        f"{group.subject_name} "
        f"Strength = {group.strength}"
    )

print()

print("=" * 60)
print("CLASSROOMS")
print("=" * 60)

for room in classrooms:
    print(
        f"{room.room_no} "
        f"Capacity = {room.capacity} "
        f"Stream Capacity = {room.column_capacity}"
    )

print()

# -------------------------------------
# Build Room Allocations
# -------------------------------------

room_allocations = [
    RoomAllocation(classroom=room)
    for room in classrooms
]

# -------------------------------------
# Create Allocation Context
# -------------------------------------

context = AllocationContext(
    groups=groups,
    room_allocations=room_allocations,
    remaining_pool=RemainingPool()
)

# -------------------------------------
# Execute Primary Allocation
# -------------------------------------

allocator = PrimaryAllocator()

context = allocator.execute(context)

# -------------------------------------
# Print Room Allocations
# -------------------------------------

print("=" * 60)
print("ROOM ALLOCATIONS")
print("=" * 60)

for room in context.room_allocations:

    print(f"\n{room.classroom.room_no}")

    if not room.allocations:
        print("No Allocations")
        continue

    for allocation in room.allocations:

        group = allocation.group

        print(
            f"Stream : {allocation.stream}"
        )
        print(
            f"Group  : {group.department}{group.semester}{group.section}"
        )
        print(
            f"Subject: {group.subject_name}"
        )
        print(
            f"Students Allocated : {allocation.allocated_count}"
        )
        print(
            f"Student Index : {allocation.start_index + 1}"
            f" - {allocation.end_index + 1}"
        )
        print("-" * 30)

# -------------------------------------
# Remaining Pool
# -------------------------------------

print("\n" + "=" * 60)
print("REMAINING POOL")
print("=" * 60)

if not context.remaining_pool.groups:
    print("No Remaining Groups")

else:
    for group in context.remaining_pool.groups:

        print(
            f"{group.department}{group.semester}{group.section}"
        )
        print(
            f"Subject : {group.subject_name}"
        )
        print(
            f"Remaining Students : {group.remaining_count}"
        )
        print("-" * 30)