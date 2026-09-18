from exam_allocator.parsers.classroom_parser import parse_classroom_excel

result = parse_classroom_excel("/home/petercj/Documents/Dev/Mini_project/resources/inputfilestimetablestudentlistrolllistandclassroom/Classroom_List.xlsx")

if (not result):
    print("No result returned from parsing.")
else:
    print("Success")

print("Rooms parsed:", len(result.rooms))
print("Issues found:", len(result.issues))

for issue in result.issues:
    print(issue)

for room in result.rooms[:5]:
    print(room)