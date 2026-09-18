from exam_allocator.models import ExamRegistration, Room

from engine.models.student import Student as EngineStudent
from engine.models.classroom import Classroom as EngineClassroom


def get_section(class_name):
    parts = class_name.strip().split()

    if not parts:
        return ""

    last = parts[-1].upper()

    # B.Arch 2K22 A
    if last in {"A", "B", "C", "D", "E", "F", "T"}:
        return last

    # CE 2K23A / CS 2K23A / etc.
    if last[-1].isalpha():
        return last[-1]

    return ""


def django_registration_to_engine_student(registration):
    student = registration.student
    exam = registration.exam

    student_class = student.student_class
    department = student_class.department

    return EngineStudent(
        register_no=student.roll_number,
        name=student.student_name,
        department=department.department_code,
        semester=student_class.semester,
        section=get_section(student_class.class_name),
        subject_code=exam.subject.subject_code,
        subject_name=exam.subject.subject_name,
        exam_date=exam.exam_date.strftime("%d-%m-%Y"),
        session=exam.session,
        roll_no=student.roll_number,
    )


def get_engine_students(exam):
    registrations = (
        ExamRegistration.objects.filter(exam=exam)
        .select_related(
            "student",
            "student__student_class",
            "student__student_class__department",
            "exam",
            "exam__subject",
        )
        .order_by(
            "student__student_class__class_name",
            "student__roll_number",
        )
    )

    return [
        django_registration_to_engine_student(registration)
        for registration in registrations
    ]


def django_room_to_engine_classroom(room):
    """
    Convert a Django Room to an EngineClassroom.

    The engine needs rows, benches_per_row, and seats_per_bench.
    We derive these from the stored bench count:

        benches == rows * benches_per_row

    Standard layout is 5 rows x 3 benches/row = 15 benches.
    For rooms with a different bench count we compute the best fit
    (3 benches per row, n rows).
    """

    benches = room.benches or 15
    seats_per_bench = 3  # always 3 seats per bench in this system
    benches_per_row = 3  # always 3 benches across per row

    # Rows = ceil(total benches / benches_per_row)
    import math
    rows = math.ceil(benches / benches_per_row)

    return EngineClassroom(
        room_no=room.room_number,
        rows=rows,
        benches_per_row=benches_per_row,
        seats_per_bench=seats_per_bench,
    )



def get_engine_classrooms(session):
    """
    Convert only classrooms belonging to the allocation session.
    """

    rooms = Room.objects.filter(session=session).order_by("room_number")

    return [django_room_to_engine_classroom(room) for room in rooms]
