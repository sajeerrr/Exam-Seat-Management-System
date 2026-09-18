from exam_allocator.parsers.student_parser import (
    parse_student_excel,
)


FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Students.xlsx"


result = parse_student_excel(FILE)


print("=" * 80)
print("STUDENT PARSER TEST")
print("=" * 80)

print(f"Source: {result.source_file}")
print(f"Classes: {len(result.classes)}")
print(f"Students: {len(result.students)}")
print(f"Issues: {len(result.issues)}")

print("\nCLASSES")
print("-" * 80)

for class_record in result.classes:
    print(
        f"{class_record.class_name:25} "
        f"S{class_record.semester:<3} "
        f"{len(class_record.students):3} students | "
        f"{class_record.department_name}"
    )

print("\nFIRST 10 STUDENTS")
print("-" * 80)

for student in result.students[:10]:
    print(
        f"{student.roll_number:15} "
        f"{student.name:30} "
        f"{student.class_name}"
    )

if result.issues:
    print("\nISSUES")
    print("-" * 80)

    for issue in result.issues:
        print(issue)