from exam_seating_engine.models.group import Group
from exam_seating_engine.models.student import Student
from exam_seating_engine.models.classroom import Classroom


def create_students(department, semester, section,
                    subject_code, subject_name, count):

    students = []

    for i in range(1, count + 1):
        students.append(
            Student(
                register_no=f"{department}{i:03}",
                name=f"{department} Student {i}",
                department=department,
                semester=semester,
                section=section,
                subject_code=subject_code,
                subject_name=subject_name,
                exam_date="2026-07-10",
                session="FN"
            )
        )

    return students




groups = [

    Group(
        group_id="G001",
        department="ME",
        semester=6,
        section="A",
        subject_code="ME601",
        subject_name="QUALITY",
        exam_date="2026-07-10",
        session="FN",
        students=create_students(
            "ME",
            6,
            "A",
            "ME601",
            "QUALITY",
            90
        )
    ),

    Group(
        group_id="G002",
        department="CE",
        semester=6,
        section="A",
        subject_code="CE601",
        subject_name="MATHS",
        exam_date="2026-07-10",
        session="FN",
        students=create_students(
            "CE",
            6,
            "A",
            "CE601",
            "MATHS",
            75
        )
    ),

    Group(
        group_id="G003",
        department="AR",
        semester=4,
        section="A",
        subject_code="AR401",
        subject_name="DRAWING",
        exam_date="2026-07-10",
        session="FN",
        students=create_students(
            "AR",
            4,
            "A",
            "AR401",
            "DRAWING",
            44
        )
    )
]

classrooms = [

    Classroom(
        room_no="Room101",
        rows=5,
        benches_per_row=3
    ),

    Classroom(
        room_no="Room102",
        rows=5,
        benches_per_row=3
    ),

    Classroom(
        room_no="Room103",
        rows=5,
        benches_per_row=3
    ),

    Classroom(
        room_no="Room104",
        rows=5,
        benches_per_row=3
    ),

    Classroom(
        room_no="Room105",
        rows=5,
        benches_per_row=3
    ),
]