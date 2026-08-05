from datetime import datetime
from data.loader.classroom_loader import ClassroomLoader
from data.loader.student_loader import StudentLoader

from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.services.allocation_service import AllocationService


def main():
    print("\n" + "=" * 65)
    print("         EXAM SEATING ALLOCATION ENGINE RUNNER")
    print("=" * 65)

    # 1. Load Classrooms
    classroom_file = "resources/Class.xlsx"
    classrooms = ClassroomLoader(classroom_file).load()
    print(f"Loaded {len(classrooms)} classrooms from {classroom_file}")

    # 2. Load Students and Timetable
    student_file = "resources/Students.xlsx"
    timetable_file = "resources/Timetable.xlsx"
    all_students = StudentLoader(
        student_file=student_file,
        timetable_file=timetable_file,
    ).load()
    print(f"Loaded {len(all_students)} student-exam records.")

    # 3. Extract Distinct Timetable Sessions & Sort Chronologically
    raw_options = []
    for s in all_students:
        opt = (s.exam_date, s.session)
        if opt not in raw_options:
            raw_options.append(opt)

    def sort_key(item):
        date_str, session = item
        parsed_date = datetime.strptime(date_str.split()[0], "%d-%m-%Y")
        session_order = 0 if session == "FN" else 1
        return (parsed_date, session_order)

    options = sorted(raw_options, key=sort_key)

    # 4. Display Session Selection Menu
    print("\n================ Select Exam Session ================")
    for index, (exam_date, session) in enumerate(options, 1):
        print(f"{index}. Date: {exam_date} | Session: {session}")
    print("=====================================================\n")

    try:
        choice = int(input(f"Select session option (1-{len(options)}): "))
        if choice < 1 or choice > len(options):
            print("Invalid session choice.")
            return
    except ValueError:
        print("Please enter a valid integer choice.")
        return

    selected_date, selected_session = options[choice - 1]

    # 5. Filter Students for Selected Session
    filtered_students = [
        s for s in all_students
        if s.exam_date == selected_date and s.session == selected_session
    ]

    print("\n" + "=" * 65)
    print(f" Target Date: {selected_date} | Session: {selected_session}")
    print(f" Total Target Students: {len(filtered_students)}")
    print("=" * 65)

    # 6. Build Department/Subject Groups
    groups = GroupBuilder().build(filtered_students)
    print(f"\nBuilt {len(groups)} merged exam group(s):")
    for group in groups:
        print(f"  • {group.group_id:<35} ({group.strength} students)")

    # 7. Prepare Allocation Engine Context
    room_allocations = [RoomAllocation(classroom=room) for room in classrooms]
    remaining_pool = RemainingPool()

    context = AllocationContext(
        groups=groups,
        room_allocations=room_allocations,
        remaining_pool=remaining_pool,
    )

    # 8. Execute Allocation Service Engine
    print("\nExecuting Seating Allocation Engine...")
    service = AllocationService()

    try:
        ctx, seat_plan = service.execute(context)
        print("\n" + "=" * 65)
        print(" SUCCESS: Seating Allocation completed successfully!")
        print("=" * 65)

        # 9. Summary Display of Room Allocations
        print("\nRoom Allocation Summary:")
        print("-" * 65)
        for room_alloc in ctx.room_allocations:
            used = room_alloc.used_capacity
            cap = room_alloc.classroom.capacity
            print(f" Room {room_alloc.classroom.room_no:<8} | Used: {used:<3} / {cap:<3} seats")

    except Exception as error:
        print("\n" + "=" * 65)
        print(f" ALLOCATION FAILED: {error}")
        print("=" * 65)


if __name__ == "__main__":
    main()