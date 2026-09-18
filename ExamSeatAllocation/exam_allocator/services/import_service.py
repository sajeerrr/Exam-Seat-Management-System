from django.db import transaction

from exam_allocator.models import (
    AllocationSession,
    Department,
    Class,
    Student,
    Room,
    Subject,
    Exam,
    ExamTarget,
)

# Timetable/student data may use a different abbreviation
# for the same department.
DEPARTMENT_ALIASES = {
    "EE": "EEE",
}


def normalize_department_code(code: str) -> str:
    """
    Normalize department codes before storing/matching them.
    """
    code = code.strip().upper()

    return DEPARTMENT_ALIASES.get(code, code)


def get_department_name(class_record) -> str:
    """
    Determine a department name from the parsed class.

    Some sheets contain an explicit department name.
    For others, derive it from the beginning of the class name.
    """

    if class_record.department_name:
        return class_record.department_name

    class_name = class_record.class_name.strip()

    # Examples:
    # CE 2K23A
    # CS 2K23A
    # EEE 2K23A
    parts = class_name.split()

    if parts:
        department_code = normalize_department_code(parts[0])
        return department_code

    return "UNKNOWN"


@transaction.atomic
def import_students(student_result, session):
    """
    Import parsed students into the Django database.

    Existing Department/Class/Student records are reused,
    making this operation safe to run multiple times.

    Returns statistics about the import.
    """

    departments_created = 0
    departments_existing = 0

    classes_created = 0
    classes_existing = 0

    students_created = 0
    students_existing = 0

    for class_record in student_result.classes:

        class_name = class_record.class_name.strip()

        # Determine department code.
        first_part = class_name.split()[0]

        department_code = normalize_department_code(first_part)

        department_name = get_department_name(class_record)

        department, created = Department.objects.get_or_create(
            session=session,
            department_code=department_code,
            defaults={
                "department_name": department_name,
            },
        )

        if created:
            departments_created += 1
        else:
            departments_existing += 1

            # If the existing department has no useful name,
            # fill it in.
            if not department.department_name and department_name:
                department.department_name = department_name
                department.save(update_fields=["department_name"])

        django_class, created = Class.objects.get_or_create(
            department=department,
            class_name=class_name,
            semester=class_record.semester,
            academic_year=class_record.academic_year,
        )

        if created:
            classes_created += 1
        else:
            classes_existing += 1

        for student_record in class_record.students:

            roll_number = student_record.roll_number.strip()

            if not roll_number:
                continue

            student, created = Student.objects.get_or_create(
                student_class=django_class,
                roll_number=roll_number,
                defaults={
                    "student_name": student_record.name.strip(),
                },
            )

            if created:
                students_created += 1
            else:
                students_existing += 1

                # Keep the database synchronized if the name
                # changed in a newer Excel file.
                new_name = student_record.name.strip()

                if new_name and student.student_name != new_name:
                    student.student_name = new_name
                    student.save(update_fields=["student_name"])

    return {
        "departments_created": departments_created,
        "departments_existing": departments_existing,
        "classes_created": classes_created,
        "classes_existing": classes_existing,
        "students_created": students_created,
        "students_existing": students_existing,
    }


@transaction.atomic
def import_classrooms(classroom_result, session):
    """
    Import parsed classrooms into the Django database.

    Existing rooms are reused based on room_number, so the
    operation is safe to run multiple times.
    """

    rooms_created = 0
    rooms_existing = 0

    for classroom in classroom_result.classrooms:

        room, created = Room.objects.get_or_create(
            session=session,
            room_number=classroom.room_number,
            defaults={
                "capacity": classroom.capacity,
                "benches": classroom.benches,
                "building": classroom.building,
            },
        )

        if created:
            rooms_created += 1

        else:
            rooms_existing += 1

            changed = False

            if room.capacity != classroom.capacity:
                room.capacity = classroom.capacity
                changed = True

            if room.benches != classroom.benches:
                room.benches = classroom.benches
                changed = True

            if room.building != classroom.building:
                room.building = classroom.building
                changed = True

            if changed:
                room.save(
                    update_fields=[
                        "capacity",
                        "benches",
                        "building",
                    ]
                )

    return {
        "rooms_created": rooms_created,
        "rooms_existing": rooms_existing,
    }


def _make_subject_code(subject_code: str, subject_name: str) -> str:
    """
    Return a database-safe subject code.

    Normal timetable subject codes are kept unchanged.

    If the parser generated a fallback from the subject name and
    that value is longer than the Subject model's 30-character
    limit, create a deterministic shortened code.
    """

    code = (subject_code or "").strip()
    name = (subject_name or "").strip()

    if not code:
        code = name

    if len(code) <= 30:
        return code

    # Build a readable code from the subject name.
    words = [
        word.strip(" ,/&()-") for word in name.upper().split() if word.strip(" ,/&()-")
    ]

    if words:
        generated = "_".join(words)

        if len(generated) <= 30:
            return generated

        # Try initials.
        initials = "".join(word[0] for word in words if word)

        if initials:
            generated = initials[:30]

            if generated:
                return generated

    # Final deterministic fallback.
    import hashlib

    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]

    return f"SUBJ_{digest}"[:30]


@transaction.atomic
def import_timetable(timetable_result, session):
    """
    Import timetable data into the database.

    Creates/reuses:
        Subject
        Exam
        ExamTarget

    Student registrations are NOT created here.
    """

    subjects_created = 0
    subjects_existing = 0

    exams_created = 0
    exams_existing = 0

    targets_created = 0
    targets_existing = 0

    for exam_record in timetable_result.exams:

        subject_code = _make_subject_code(
            exam_record.subject_code,
            exam_record.subject_name,
        )

        subject, created = Subject.objects.get_or_create(
            session=session,
            subject_code=subject_code,
            defaults={
                "subject_name": exam_record.subject_name,
                "semester": exam_record.semester,
            },
        )

        if created:
            subjects_created += 1
        else:
            subjects_existing += 1

            changed = False

            if subject.subject_name != exam_record.subject_name:
                subject.subject_name = exam_record.subject_name
                changed = True

            if subject.semester != exam_record.semester:
                subject.semester = exam_record.semester
                changed = True

            if changed:
                subject.save(
                    update_fields=[
                        "subject_name",
                        "semester",
                    ]
                )

        exam, created = Exam.objects.get_or_create(
            subject=subject,
            exam_date=exam_record.exam_date,
            session=exam_record.session,
            defaults={
                "duration": exam_record.duration_minutes,
            },
        )

        if created:
            exams_created += 1
        else:
            exams_existing += 1

            if exam.duration != exam_record.duration_minutes:
                exam.duration = exam_record.duration_minutes
                exam.save(update_fields=["duration"])

        # --------------------------------------------------
        # Create ExamTarget records
        # --------------------------------------------------

        branches = [
            branch.strip()
            for branch in exam_record.branches
            if branch and branch.strip()
        ]

        # ALL BRANCHES
        if len(branches) == 1 and branches[0].upper() == "ALL BRANCHES":

            _, created = ExamTarget.objects.get_or_create(
                exam=exam,
                target_type="ALL_BRANCHES",
                branch_code="",
                slot="",
            )

            if created:
                targets_created += 1
            else:
                targets_existing += 1

        # ARCHITECTURE SLOT
        elif len(branches) == 1 and branches[0].upper().startswith("SLOT "):

            slot = branches[0][5:].strip().upper()

            _, created = ExamTarget.objects.get_or_create(
                exam=exam,
                target_type="ARCHITECTURE_SLOT",
                branch_code="B.ARCH",
                slot=slot,
            )

            if created:
                targets_created += 1
            else:
                targets_existing += 1

        # NORMAL / MULTI-BRANCH EXAM
        else:

            for branch in branches:

                branch_code = branch.upper()

                _, created = ExamTarget.objects.get_or_create(
                    exam=exam,
                    target_type="BRANCH",
                    branch_code=branch_code,
                    slot="",
                )

                if created:
                    targets_created += 1
                else:
                    targets_existing += 1

    return {
        "subjects_created": subjects_created,
        "subjects_existing": subjects_existing,
        "exams_created": exams_created,
        "exams_existing": exams_existing,
        "targets_created": targets_created,
        "targets_existing": targets_existing,
    }
