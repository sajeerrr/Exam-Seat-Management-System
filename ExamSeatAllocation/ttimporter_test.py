from exam_allocator.parsers.timetable_parser import parse_timetable_excel

result = parse_timetable_excel(
    "/home/petercj/Documents/Dev/Mini_project/resources/sajeerfiles/Timetable.xlsx"
)

exam = result.exams[0]

print(type(exam))
print(exam)
print(vars(exam))
