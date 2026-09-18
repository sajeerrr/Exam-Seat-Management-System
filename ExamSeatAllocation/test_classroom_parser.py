from exam_allocator.parsers.classroom_parser import (
    parse_classroom_excel,
)


FILE = "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Class.xlsx"


result = parse_classroom_excel(FILE)


print("=" * 80)
print("CLASSROOM PARSER TEST")
print("=" * 80)

print(f"Source: {result.source_file}")
print(f"Classrooms: {len(result.classrooms)}")
print(f"Issues: {len(result.issues)}")

print("\nCLASSROOMS")
print("-" * 80)

for classroom in result.classrooms:
    print(
        f"Room {classroom.room_number:10} | "
        f"Capacity: {classroom.capacity:3} | "
        f"Benches: {classroom.benches:3} | "
        f"Building: {classroom.building}"
    )

if result.issues:
    print("\nISSUES")
    print("-" * 80)

    for issue in result.issues:
        print(issue)