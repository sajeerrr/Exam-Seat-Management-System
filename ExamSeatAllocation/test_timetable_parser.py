from exam_allocator.parsers.timetable_parser import (
    parse_timetable_excel,
)


FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Timetable.xlsx"


result = parse_timetable_excel(FILE)


print("=" * 100)
print("TIMETABLE PARSER TEST")
print("=" * 100)

print(f"Source: {result.source_file}")
print(f"Exams: {len(result.exams)}")
print(f"Issues: {len(result.issues)}")

print("\nEXAMS")
print("-" * 100)

for index, exam in enumerate(
    result.exams,
    start=1,
):
    print(
        f"{index:3}. "
        f"{exam.exam_date} | "
        f"{exam.session} | "
        f"S{exam.semester:<2} | "
        f"{exam.branch:<15} | "
        f"{exam.subject_code:<15} | "
        f"{exam.subject_name}"
    )

print("\nFIRST EXAM DETAILS")
print("-" * 100)

if result.exams:

    exam = result.exams[0]

    print(f"Program:       {exam.program}")
    print(f"Semester:      S{exam.semester}")
    print(f"Date:          {exam.exam_date}")
    print(f"Session:       {exam.session}")
    print(f"Time:          {exam.time}")
    print(f"Branch:        {exam.branch}")
    print(f"Branches:      {exam.branches}")
    print(f"Subject Name:  {exam.subject_name}")
    print(f"Subject Code:  {exam.subject_code}")
    print(f"Duration:      {exam.duration_minutes} minutes")

if result.issues:

    print("\nISSUES")
    print("-" * 100)

    for issue in result.issues:
        print(issue)