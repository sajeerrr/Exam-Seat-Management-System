"""
Exam registration resolution service.

This module determines which students can be automatically
matched to each exam based on semester and exam targets.

It does NOT create ExamRegistration records yet.

It only produces a preview.
"""

from dataclasses import dataclass, field

from exam_allocator.models import (
    Exam,
    Student,
    ExamRegistration,
)

from django.db import transaction

from exam_allocator.models import ExamRegistration

# Timetable and student data sometimes use different
# department abbreviations for the same department.
BRANCH_ALIASES = {
    "EE": "EEE",
}


# These subjects require individual student-selection data.
# We cannot safely assume that every student in the targeted
# branch is taking the subject.
MANUAL_MAPPING_KEYWORDS = (
    "ELECTIVE",
    "MINOR",
    "HONS",
)


@dataclass
class RegistrationPreview:
    exam_id: int
    subject_code: str
    subject_name: str
    exam_date: str
    session: str
    semester: int
    timetable_branches: list[str]

    matched_students: list[Student] = field(default_factory=list)

    matched_classes: list[str] = field(default_factory=list)

    status: str = "UNRESOLVED"

    message: str = ""


def normalize_branch(branch: str) -> str:
    """
    Convert a timetable branch code into the corresponding
    student-data branch code.
    """

    branch = branch.strip().upper()

    return BRANCH_ALIASES.get(
        branch,
        branch,
    )


def get_class_branch(class_name: str) -> str:
    """
    Extract the branch from a class name.

    Examples:

        CE 2K23A      -> CE
        CS 2K23A      -> CS
        EEE 2K23A     -> EEE
        B.Arch 2K24   -> B.ARCH
    """

    parts = class_name.strip().split()

    if not parts:
        return ""

    branch = parts[0].upper()

    if branch == "B.ARCH":
        return "B.ARCH"

    return normalize_branch(branch)


def resolve_exam_branches(exam: Exam) -> list[str]:
    """
    Read branch targets associated with an exam.

    Returns normalized branch codes.

    Examples:

        CE
        ['CE']

        CE / ME / CH
        ['CE', 'ME', 'CH']

    ALL_BRANCHES and architecture slots are deliberately
    not returned as normal branches.
    """

    targets = exam.targets.all()

    branches = []

    for target in targets:

        if target.target_type != "BRANCH":
            continue

        if not target.branch_code:
            continue

        branch = normalize_branch(target.branch_code)

        if branch not in branches:
            branches.append(branch)

    return branches


def is_manual_mapping_required(exam: Exam) -> tuple[bool, str]:
    """
    Determine whether an exam requires individual student
    registration information.

    We cannot safely auto-register students for:

        - ALL_BRANCHES exams
        - Architecture slot exams
        - Elective / Minor / Hons subjects

    because the supplied student list does not contain the
    individual selections for these cases.
    """

    targets = list(exam.targets.all())

    if not targets:
        return (
            True,
            "Exam has no targeting information.",
        )

    # Architecture slots require the student's architecture
    # slot selection, which is not present in Students.xlsx.
    if any(target.target_type == "ARCHITECTURE_SLOT" for target in targets):
        return (
            True,
            "Architecture slot requires student slot-selection data.",
        )

    # ALL_BRANCHES is used by several elective-type exams.
    if any(target.target_type == "ALL_BRANCHES" for target in targets):
        return (
            True,
            "All-branch exam requires individual student registration data.",
        )

    # A branch target does not necessarily mean that every
    # student in that branch takes the subject. This matters
    # particularly for Program Elective III.
    subject_text = (
        f"{exam.subject.subject_code} " f"{exam.subject.subject_name}"
    ).upper()

    if any(keyword in subject_text for keyword in MANUAL_MAPPING_KEYWORDS):
        return (
            True,
            "Elective/minor subject requires individual student selection data.",
        )

    return False, ""


def preview_exam_registration(
    exam: Exam,
) -> RegistrationPreview:
    """
    Determine which students can be automatically matched
    to an exam.

    No ExamRegistration records are created.
    """

    targets = list(exam.targets.all())

    timetable_branches = [
        normalize_branch(target.branch_code)
        for target in targets
        if (target.target_type == "BRANCH" and target.branch_code)
    ]

    # Remove duplicates while preserving order.
    timetable_branches = list(dict.fromkeys(timetable_branches))

    manual_mapping, manual_message = is_manual_mapping_required(exam)

    if manual_mapping:
        return RegistrationPreview(
            exam_id=exam.exam_id,
            subject_code=exam.subject.subject_code,
            subject_name=exam.subject.subject_name,
            exam_date=str(exam.exam_date),
            session=exam.session,
            semester=exam.subject.semester,
            timetable_branches=timetable_branches,
            status="REQUIRES_MAPPING",
            message=manual_message,
        )

    if not timetable_branches:
        return RegistrationPreview(
            exam_id=exam.exam_id,
            subject_code=exam.subject.subject_code,
            subject_name=exam.subject.subject_name,
            exam_date=str(exam.exam_date),
            session=exam.session,
            semester=exam.subject.semester,
            timetable_branches=[],
            status="UNRESOLVED",
            message="No resolvable branch targets.",
        )

    # Get all students belonging to the same semester.
    students = (
        Student.objects.select_related(
            "student_class",
            "student_class__department",
        )
        .filter(
            student_class__semester=exam.subject.semester,
            student_class__department__session=exam.subject.session,
        )
        .order_by(
            "student_class__class_name",
            "roll_number",
        )
    )

    matched_students = []
    matched_classes = set()

    target_branches = set(timetable_branches)

    for student in students:

        class_name = student.student_class.class_name

        class_branch = get_class_branch(class_name)

        if class_branch in target_branches:

            matched_students.append(student)

            matched_classes.add(class_name)

    if not matched_students:
        return RegistrationPreview(
            exam_id=exam.exam_id,
            subject_code=exam.subject.subject_code,
            subject_name=exam.subject.subject_name,
            exam_date=str(exam.exam_date),
            session=exam.session,
            semester=exam.subject.semester,
            timetable_branches=timetable_branches,
            matched_students=[],
            matched_classes=[],
            status="UNRESOLVED",
            message=("No students matched the exam semester " "and branch targets."),
        )

    return RegistrationPreview(
        exam_id=exam.exam_id,
        subject_code=exam.subject.subject_code,
        subject_name=exam.subject.subject_name,
        exam_date=str(exam.exam_date),
        session=exam.session,
        semester=exam.subject.semester,
        timetable_branches=timetable_branches,
        matched_students=matched_students,
        matched_classes=sorted(matched_classes),
        status="AUTO_RESOLVED",
        message=("Students matched by semester and branch."),
    )


def preview_all_exams():
    """
    Generate registration previews for all exams.
    """

    exams = (
        Exam.objects.select_related("subject")
        .prefetch_related("targets")
        .order_by(
            "exam_date",
            "session",
            "exam_id",
        )
    )

    return [preview_exam_registration(exam) for exam in exams]


@transaction.atomic
def create_exam_registrations(exam: Exam) -> dict:
    """
    Create ExamRegistration records for an automatically
    resolvable exam.

    Existing registrations are reused, making this operation
    safe to run multiple times.

    Exams that require manual mapping or cannot be resolved
    will not create registrations.
    """

    preview = preview_exam_registration(exam)

    if preview.status != "AUTO_RESOLVED":
        return {
            "exam_id": exam.exam_id,
            "subject_code": exam.subject.subject_code,
            "status": preview.status,
            "registrations_created": 0,
            "registrations_existing": 0,
            "message": preview.message,
        }

    created_count = 0
    existing_count = 0

    for student in preview.matched_students:

        registration, created = ExamRegistration.objects.get_or_create(
            student=student,
            exam=exam,
        )

        if created:
            created_count += 1
        else:
            existing_count += 1

    return {
        "exam_id": exam.exam_id,
        "subject_code": exam.subject.subject_code,
        "status": "AUTO_RESOLVED",
        "registrations_created": created_count,
        "registrations_existing": existing_count,
        "message": "Registrations created successfully.",
    }


@transaction.atomic
def create_all_exam_registrations(session) -> dict:
    """
    Create registrations for all automatically resolvable exams.

    Exams requiring manual mapping are deliberately skipped.
    """

    exams = (
        Exam.objects.select_related("subject")
        .prefetch_related("targets")
        .filter(subject__session=session)
        .order_by(
            "exam_date",
            "session",
            "exam_id",
        )
    )

    total_created = 0
    total_existing = 0

    auto_resolved_exams = 0
    mapping_required_exams = 0
    unresolved_exams = 0

    results = []

    for exam in exams:

        result = create_exam_registrations(exam)

        results.append(result)

        total_created += result["registrations_created"]

        total_existing += result["registrations_existing"]

        if result["status"] == "AUTO_RESOLVED":
            auto_resolved_exams += 1

        elif result["status"] == "REQUIRES_MAPPING":
            mapping_required_exams += 1

        else:
            unresolved_exams += 1

    return {
        "total_created": total_created,
        "total_existing": total_existing,
        "auto_resolved_exams": auto_resolved_exams,
        "mapping_required_exams": mapping_required_exams,
        "unresolved_exams": unresolved_exams,
        "results": results,
    }
