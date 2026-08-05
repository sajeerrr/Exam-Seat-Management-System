from data.loader.student_loader import StudentLoader
# from loader.classroom_loader import load_classrooms

students = StudentLoader(
    student_file="resources/Students.xlsx",
    timetable_file="resources/Timetable.xlsx",
).load()

# classrooms = load_classrooms(
#     "Class.xlsx"
# )

print(f"Total Students: {len(students)}")

for student in students[:10]:
    print(
        student.register_no,
        student.name,
        student.department,
        student.semester,
        student.section,
        student.subject_code,
        student.session,
    )