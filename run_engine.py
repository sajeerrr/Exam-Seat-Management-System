import os
from datetime import datetime
import pandas as pd

from data.loader.classroom_loader import ClassroomLoader
from data.loader.student_loader import StudentLoader

from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.services.allocation_service import AllocationService
from engine.validators.allocation_validator import AllocationValidator

from engine.hyper.state_analyzer import StateAnalyzer



def export_seating_plan_to_excel(
    seat_plan, selected_date: str, selected_session: str
):
    """Exports Sheet 1 (Room Summary) and Sheet 2 (Seating Order ABC)."""

    def get_attr(obj, attr_name, default=""):
        if isinstance(obj, dict):
            return obj.get(attr_name, default)
        return getattr(obj, attr_name, default)

    # 1. Sheet 1: Room Summary
    summary_data = []
    room_numbers = []
    for s in seat_plan.seats:
        r_no = get_attr(s, "room_no") or get_attr(s, "Room No")
        if r_no and r_no not in room_numbers:
            room_numbers.append(r_no)

    for room_no in room_numbers:
        room_seats = [
            s
            for s in seat_plan.seats
            if (get_attr(s, "room_no") or get_attr(s, "Room No")) == room_no
        ]
        if not room_seats:
            continue

        stream_summaries = {}
        for stream in ["A", "B", "C"]:
            st_seats = [
                s
                for s in room_seats
                if (get_attr(s, "stream") or get_attr(s, "Stream")) == stream
            ]
            if not st_seats:
                stream_summaries[f"Stream {stream}"] = "None"
                continue

            dept_ranges = []
            curr_dept = getattr(
                get_attr(st_seats[0], "student"),
                "department",
                get_attr(st_seats[0], "Department"),
            )
            start_bench = get_attr(st_seats[0], "bench_no") or get_attr(
                st_seats[0], "Bench No"
            )
            end_bench = start_bench

            for s in st_seats:
                dept = getattr(
                    get_attr(s, "student"),
                    "department",
                    get_attr(s, "Department"),
                )
                b_no = get_attr(s, "bench_no") or get_attr(s, "Bench No")
                if dept == curr_dept:
                    end_bench = b_no
                else:
                    r_str = (
                        f"Bench {start_bench} {curr_dept}"
                        if start_bench == end_bench
                        else f"{start_bench}-{end_bench} {curr_dept}"
                    )
                    dept_ranges.append(r_str)
                    curr_dept = dept
                    start_bench = b_no
                    end_bench = b_no

            r_str = (
                f"Bench {start_bench} {curr_dept}"
                if start_bench == end_bench
                else f"{start_bench}-{end_bench} {curr_dept}"
            )
            dept_ranges.append(r_str)
            stream_summaries[f"Stream {stream}"] = ", ".join(dept_ranges)

        summary_data.append(
            {
                "Room No": room_no,
                "Total Students": len(room_seats),
                "Stream A": stream_summaries.get("Stream A", "None"),
                "Stream B": stream_summaries.get("Stream B", "None"),
                "Stream C": stream_summaries.get("Stream C", "None"),
                "Exam Date": selected_date,
                "Session": selected_session,
            }
        )

    df_summary = pd.DataFrame(summary_data)

    # 2. Sheet 2: Seating Order (ABC Interleaved)
    student_data = []
    stream_map = {"A": 1, "B": 2, "C": 3}
    for seat in seat_plan.seats:
        student = get_attr(seat, "student")
        st_stream = get_attr(seat, "stream") or get_attr(seat, "Stream")
        student_data.append(
            {
                "Room No": get_attr(seat, "room_no")
                or get_attr(seat, "Room No"),
                "Bench No": get_attr(seat, "bench_no")
                or get_attr(seat, "Bench No"),
                "Stream": st_stream,
                "Department": getattr(
                    student, "department", get_attr(seat, "Department")
                ),
                "Subject Code": getattr(
                    student, "subject_code", get_attr(seat, "Subject Code")
                ),
                "Subject Name": getattr(
                    student, "subject_name", get_attr(seat, "Subject Name")
                ),
                "Register No": getattr(
                    student, "register_no", get_attr(seat, "Register No")
                ),
                "Roll No": getattr(
                    student, "roll_no", get_attr(seat, "Roll No", "")
                ),
                "Student Name": getattr(
                    student, "name", get_attr(seat, "Student Name")
                ),
                "Semester": f"S{getattr(student, 'semester', get_attr(seat, 'Semester'))}",
                "Section": getattr(
                    student, "section", get_attr(seat, "Section")
                ),
                "Exam Date": selected_date,
                "Session": selected_session,
                "_stream_rank": stream_map.get(st_stream, 99),
            }
        )

    df_students = pd.DataFrame(student_data)
    if not df_students.empty:
        df_students = df_students.sort_values(
            by=["Room No", "Bench No", "_stream_rank"]
        ).drop(columns=["_stream_rank"])

    date_clean = selected_date.split()[0]
    output_filename = f"Seating_Plan_{date_clean}_{selected_session}.xlsx"

    with pd.ExcelWriter(output_filename, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Room Summary", index=False)
        df_students.to_excel(
            writer, sheet_name="Seating Order (ABC)", index=False
        )

    print("\n" + "=" * 65)
    print(f" SUCCESS: Seating plan exported to '{output_filename}'")
    print("   • Sheet 1: Room Summary")
    print("   • Sheet 2: Seating Order (ABC)")
    print("=" * 65 + "\n")


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

    # Analyze current allocation state
    state = StateAnalyzer().analyze(context)

    print("\n" + "=" * 65)
    print("CURRENT ALLOCATION STATE")
    print("=" * 65)
    print(f"Largest Group      : {state.largest_group}")
    print(f"Smallest Group     : {state.smallest_group}")
    print(f"Average Group Size : {state.average_group_size:.2f}")
    print(f"Active Groups      : {state.active_groups}")
    print(f"Remaining Students : {state.remaining_students}")
    print(f"Remaining Rooms    : {state.remaining_rooms}")
    print("=" * 65)


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
            if used > 0:
                print(f" Room {room_alloc.classroom.room_no:<8} | Used: {used:<3} / {cap:<3} seats")

        validation = AllocationValidator().validate(ctx)
        print("\nAllocation Validation:")
        print("-" * 65)
        if validation.success:
            print(" Validation passed.")
        else:
            print(" Validation failed:")
            for error in validation.errors:
                print(f"  - {error}")

        if validation.warnings:
            print(" Validation warnings:")
            for warning in validation.warnings:
                print(f"  - {warning}")

        # 10. Prompt User for Excel Export
        print("\n" + "-" * 65)
        export_choice = input("Do you want to generate output in Excel? (yes/no): ").strip().lower()

        if export_choice in ["yes", "y"]:
            export_seating_plan_to_excel(seat_plan, selected_date, selected_session)
        else:
            print("Excel export skipped.")

    except Exception as error:
        print("\n" + "=" * 65)
        print(f" ALLOCATION FAILED: {error}")
        print("=" * 65)


if __name__ == "__main__":
    main()
