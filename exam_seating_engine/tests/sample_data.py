from exam_seating_engine.models.student import Student
from exam_seating_engine.models.classroom import Classroom

# -------------------------
# ME - 90 Students
# -------------------------

students = []

for i in range(1, 91):
    students.append(
        Student(
            register_no=f"23ME{i:03}",
            name=f"ME Student {i}",
            department="ME",
            semester=6,
            section="A",
            subject_code="ME601",
            subject_name="QUALITY",
            exam_date="2026-07-10",
            session="FN",
        )
    )

# -------------------------
# CE - 75 Students
# -------------------------

for i in range(1, 76):
    students.append(
        Student(
            register_no=f"23CE{i:03}",
            name=f"CE Student {i}",
            department="CE",
            semester=6,
            section="A",
            subject_code="CE601",
            subject_name="MATHS",
            exam_date="2026-07-10",
            session="FN",
        )
    )

# -------------------------
# AR - 44 Students
# -------------------------

for i in range(1, 45):
    students.append(
        Student(
            register_no=f"23AR{i:03}",
            name=f"AR Student {i}",
            department="AR",
            semester=4,
            section="A",
            subject_code="AR401",
            subject_name="DRAWING",
            exam_date="2026-07-10",
            session="FN",
        )
    )

# -------------------------
# Classrooms
# -------------------------

classrooms = [
    Classroom(
        room_no="Room101",
        rows=5,
        benches_per_row=3,
    ),
    Classroom(
        room_no="Room102",
        rows=5,
        benches_per_row=3,
    ),
    Classroom(
        room_no="Room103",
        rows=5,
        benches_per_row=3,
    ),
]