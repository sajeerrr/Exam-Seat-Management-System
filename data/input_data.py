from datetime import datetime
from data.loader.student_loader import StudentLoader


def main():
    loader = StudentLoader(
        student_file="resources/Students.xlsx",
        timetable_file="resources/Timetable.xlsx",
    )

    all_students = loader.load()

    # Extract distinct (exam_date, session) pairs
    raw_options = []
    for s in all_students:
        opt = (s.exam_date, s.session)
        if opt not in raw_options:
            raw_options.append(opt)

    # Helper function to parse date and order FN before AN
    def sort_key(item):
        date_str, session = item
        # Extract 'DD-MM-YYYY' from '12-03-2026 (Thursday)'
        date_part = date_str.split()[0]
        parsed_date = datetime.strptime(date_part, "%d-%m-%Y")
        session_order = 0 if session == "FN" else 1
        return (parsed_date, session_order)

    # Sort chronologically
    options = sorted(raw_options, key=sort_key)

    print("\n================ Timetable Sessions ================")
    for index, (exam_date, session) in enumerate(options, 1):
        print(f"{index}. Date: {exam_date} | Session: {session}")
    print("====================================================\n")

    try:
        choice = int(input(f"Select session option (1-{len(options)}): "))
        if choice < 1 or choice > len(options):
            print("Invalid choice selected.")
            return
    except ValueError:
        print("Please enter a valid integer.")
        return

    selected_date, selected_session = options[choice - 1]

    # Filter students for the selected date and session
    filtered_students = [
        s for s in all_students
        if s.exam_date == selected_date and s.session == selected_session
    ]

    print("\n" + "=" * 65)
    print(f" Date: {selected_date} | Session: {selected_session}")
    print(f" Total Students: {len(filtered_students)}")
    print("=" * 65 + "\n")

    for student in filtered_students:
        print(
            f"{student.register_no:<15} | "
            f"{student.name:<25} | "
            f"{student.department:<6} S{student.semester:<2} {student.section:<2} | "
            f"{student.subject_code:<10}"
        )


if __name__ == "__main__":
    main()