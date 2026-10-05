import math

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


def _is_matching_elective_exam(exam, el_subj) -> bool:
    if not el_subj:
        return False
    if el_subj.subject_code.strip().upper() == exam.subject.subject_code.strip().upper():
        return True
    exam_text = f"{exam.subject.subject_code} {exam.subject.subject_name}".upper().replace("PROGRAMME", "PROGRAM")
    group_label = getattr(el_subj.group, "elective_label", "") if hasattr(el_subj, "group") and el_subj.group else ""
    el_type = getattr(el_subj, "elective_type", "") or ""
    group_text = f"{group_label} {el_type}".upper().replace("PROGRAMME", "PROGRAM")
    
    # Specific elective group matching
    tokens_3 = ["ELECTIVE III", "ELECTIVE-III", "ELECTIVE 3", "ELECTIVE-3"]
    tokens_4 = ["ELECTIVE IV", "ELECTIVE-IV", "ELECTIVE 4", "ELECTIVE-4"]
    tokens_5 = ["ELECTIVE V", "ELECTIVE-V", "ELECTIVE 5", "ELECTIVE-5"]
    
    if any(t in exam_text for t in tokens_3) and any(t in group_text for t in tokens_3):
        return True
    if any(t in exam_text for t in tokens_4) and any(t in group_text for t in tokens_4):
        return True
    if any(t in exam_text for t in tokens_5) and any(t in group_text for t in tokens_5):
        return True
    if ("ARCHITECTURE" in exam_text or "B.ARCH" in exam_text) and ("ARCHITECTURE" in group_text or "B.ARCH" in group_text):
        return True
    if el_subj.subject_code.strip().upper() in exam_text:
        return True
    return False


def django_registration_to_engine_student(registration):
    student = registration.student
    exam = registration.exam

    student_class = student.student_class
    department = student_class.department

    reg_no = student.roll_number or student.uni_reg_no or student.admission_no or str(student.student_id)

    subj_code = exam.subject.subject_code
    subj_name = exam.subject.subject_name
    category = "NORMAL"

    el_regs = list(
        student.elective_registrations
        .filter(elective_subject__group__session=exam.subject.session)
        .select_related("elective_subject", "elective_subject__group")
    )
    matching_el = None
    for r in el_regs:
        if _is_matching_elective_exam(exam, r.elective_subject):
            matching_el = r
            break

    if matching_el:
        subj_code = matching_el.elective_subject.subject_code
        subj_name = matching_el.elective_subject.subject_name
        category = matching_el.elective_subject.elective_type or "ELECTIVE"
    elif hasattr(registration, "category") and registration.category:
        category = registration.category
    elif hasattr(registration, "subject_category") and registration.subject_category:
        category = registration.subject_category
    elif hasattr(exam, "subject_category") and exam.subject_category:
        category = exam.subject_category
    elif hasattr(exam.subject, "elective_type") and exam.subject.elective_type:
        category = exam.subject.elective_type
    elif hasattr(exam.subject, "subject_category") and exam.subject.subject_category:
        category = exam.subject.subject_category

    return EngineStudent(
        register_no=reg_no,
        name=student.student_name,
        department=department.department_code,
        semester=student_class.semester,
        section=get_section(student_class.class_name),
        subject_code=subj_code,
        subject_name=subj_name,
        exam_date=exam.exam_date.strftime("%d-%m-%Y"),
        session=exam.session,
        roll_no=student.roll_number,
        subject_category=category,
    )


def elective_registration_to_engine_student(reg, exam_date="01-01-2025", session="FN"):
    dept = reg.department
    if not dept and reg.student and reg.student.student_class:
        dept = reg.student.student_class.department.department_code
    sem = 0
    if reg.student and reg.student.student_class:
        sem = reg.student.student_class.semester
    sec = get_section(reg.class_name) if reg.class_name else ""
    return EngineStudent(
        register_no=reg.roll_number,
        name=reg.student_name,
        department=dept or "GEN",
        semester=sem,
        section=sec,
        subject_code=reg.elective_subject.subject_code,
        subject_name=reg.elective_subject.subject_name,
        exam_date=exam_date,
        session=session,
        roll_no=reg.roll_number,
        subject_category=reg.elective_subject.elective_type or "ELECTIVE",
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
