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



def export_seating_plan_to_excel(
    seat_plan, selected_date: str, selected_session: str
):
    """Exports:

    - Sheet 1 ('Room Summary'): Consolidates department seat ranges per room
    stream.
    - Sheet 2 ('Seating Order (ABC Interleaved)'): Lists students strictly in 1
    bench (A, B, C), 2 bench (A, B, C) physical order per room.
    """

    # ==========================================
    # 1. BUILD SHEET 1: ROOM SUMMARY
    # ==========================================
    summary_data = []

    # Get distinct room numbers in allocation order
    room_numbers = []
    for s in seat_plan.seats:
        if s.room_no not in room_numbers:
            room_numbers.append(s.room_no)

    for room_no in room_numbers:
        room_seats = [s for s in seat_plan.seats if s.room_no == room_no]
        if not room_seats:
            continue

        streams = sorted(list(set(s.stream for s in room_seats)))
        stream_summaries = {}

        for stream in streams:
            stream_seats = [s for s in room_seats if s.stream == stream]
            if not stream_seats:
                continue

            dept_ranges = []
            curr_dept = stream_seats[0].student.department
            start_bench = stream_seats[0].bench_no
            end_bench = start_bench

            for s in stream_seats:
                if s.student.department == curr_dept:
                    end_bench = s.bench_no
                else:
                    if start_bench == end_bench:
                        range_str = f"Bench {start_bench} {curr_dept}"
                    else:
                        range_str = f"{start_bench}-{end_bench} {curr_dept}"
                    dept_ranges.append(range_str)

                    curr_dept = s.student.department
                    start_bench = s.bench_no
                    end_bench = start_bench

            if start_bench == end_bench:
                range_str = f"Bench {start_bench} {curr_dept}"
            else:
                range_str = f"{start_bench}-{end_bench} {curr_dept}"
            dept_ranges.append(range_str)

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

    # ==========================================
    # 2. BUILD SHEET 2: STRICT PHYSICAL BENCH ORDER (1-A, 1-B, 1-C, 2-A, 2-B, 2-C...)
    # ==========================================
    student_data = []
    stream_map = {"A": 1, "B": 2, "C": 3}

    for seat in seat_plan.seats:
        student_data.append(
            {
                "Room No": seat.room_no,
                "Bench No": seat.bench_no,
                "Stream": seat.stream,
                "Department": seat.student.department,
                "Subject Code": seat.student.subject_code,
                "Subject Name": seat.student.subject_name,
                "Register No": seat.student.register_no,
                "Roll No": getattr(seat.student, "roll_no", ""),
                "Student Name": seat.student.name,
                "Semester": f"S{seat.student.semester}",
                "Section": seat.student.section,
                "Exam Date": seat.student.exam_date,
                "Session": seat.student.session,
                "_stream_rank": stream_map.get(seat.stream, 99),
            }
        )

    df_students = pd.DataFrame(student_data)

    # Sort STRICTLY by Room No -> Bench No -> Stream (A -> B -> C)
    df_students = df_students.sort_values(
        by=["Room No", "Bench No", "_stream_rank"]
    ).drop(columns=["_stream_rank"])

    # ==========================================
    # 3. WRITE TO EXCEL WORKBOOK
    # ==========================================
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
    print(
        "   • Sheet 2: Seating Order (ABC) [Bench 1 A-B-C, Bench 2 A-B-C, etc.]"
    )
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