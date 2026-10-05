"""
Exam registration resolution service.

This module determines which students can be automatically
matched to each exam based on semester and exam targets,
supporting flexible semester formats (S8, 8 SEM, 2K22, etc.)
and elective/minor/honours subject-code mapping.
"""

import logging
import re
from dataclasses import dataclass, field
from django.db import transaction

from exam_allocator.models import (
    Exam,
    Student,
    Class,
    ExamRegistration,
    ElectiveGroup,
    ElectiveSubject,
    ElectiveStudentRegistration,
)

logger = logging.getLogger("exam_allocator.matching")

BRANCH_CANONICAL = {
    "EC": "ECE", "ECE": "ECE",
    "CS": "CSE", "CSE": "CSE",
    "CH": "CHE", "CHE": "CHE",
    "EE": "EEE", "EEE": "EEE",
    "CE": "CE",
    "ME": "ME",
    "EL": "EL",
    "B.ARCH": "B.ARCH", "ARCH": "B.ARCH", "AR": "B.ARCH", "BARCH": "B.ARCH",
    "AI": "AI", "AIDS": "AI",
    "CT": "CT",
    "MCA": "MCA",
    "EV": "EV", "IIC": "IIC", "IRCE": "IRCE", "ISE": "ISE",
    "MT_CSE": "MT_CSE", "MT_EC-CS": "MT_EC-CS", "SECM": "SECM",
    "TE": "TE", "UP": "UP",
}

SEMESTER_BATCH_MAP = {
    8: "2K22",
    6: "2K23",
    4: "2K24",
    2: "2K25",
    10: "2K21",
}

BATCH_SEMESTER_MAP = {
    "2K22": 8, "2022": 8, "22": 8,
    "2K23": 6, "2023": 6, "23": 6,
    "2K24": 4, "2024": 4, "24": 4,
    "2K25": 2, "2025": 2, "25": 2,
    "2K21": 10, "2021": 10, "21": 10,
}

ROMAN_TO_INT = {
    "X": 10, "IX": 9, "VIII": 8, "VII": 7, "VI": 6, "V": 5, "IV": 4, "III": 3, "II": 2, "I": 1,
}


def parse_semester_flexible(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)

    text = str(value).strip().upper()
    if not text:
        return None

    if text.isdigit():
        return int(text)

    for b_code, s_val in BATCH_SEMESTER_MAP.items():
        if b_code in text:
            return s_val

    m = re.search(r"\bS(?:EM(?:ESTER)?)?[\s\.\-_]*(\d+)\b", text)
    if m:
        return int(m.group(1))

    m2 = re.search(r"\b(\d+)\s*(?:ST|ND|RD|TH)?[\s\.\-_]*(?:SEM(?:ESTER)?|S)\b", text)
    if m2:
        return int(m2.group(1))

    for rom, val in ROMAN_TO_INT.items():
        if re.search(rf"\b(?:SEM(?:ESTER)?[\s\.\-_]*)?{rom}(?:[\s\.\-_]*SEM(?:ESTER)?)?\b", text):
            return val

    m3 = re.search(r"(\d+)", text)
    if m3:
        return int(m3.group(1))

    return None


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
    cleaned = branch.strip().upper()
    return BRANCH_CANONICAL.get(cleaned, cleaned)


def get_class_branch(class_name: str) -> str:
    parts = class_name.strip().split()
    if not parts:
        return ""
    p0 = parts[0].upper()
    if p0 in ("B.ARCH", "BARCH"):
        return "B.ARCH"
    return normalize_branch(p0)


def get_class_branch_and_sem(class_name: str, db_sem: int, db_dept: str) -> tuple[str, int]:
    parts = class_name.strip().split()
    dept = ""
    if parts:
        p0 = parts[0].upper()
        if p0 in ("B.ARCH", "BARCH"):
            dept = "B.ARCH"
        else:
            dept = normalize_branch(p0)
    if not dept or dept == "UNKNOWN":
        dept = normalize_branch(db_dept)
    sem = db_sem
    if not sem or sem == 0:
        sem = parse_semester_flexible(class_name) or 0
    return dept, sem


def resolve_exam_branches(exam: Exam) -> list[str]:
    targets = exam.targets.all()
    branches = []
    for target in targets:
        if target.target_type == "ARCHITECTURE_SLOT":
            b = "B.ARCH"
        elif target.target_type == "BRANCH" and target.branch_code:
            b = normalize_branch(target.branch_code)
        elif target.target_type == "ALL_BRANCHES":
            b = "ALL_BRANCHES"
        else:
            continue
        if b not in branches:
            branches.append(b)
    return branches


def _resolve_elective_students(exam: Exam) -> list[Student]:
    session = exam.subject.session
    code = exam.subject.subject_code.strip()
    elective_regs = list(
        ElectiveStudentRegistration.objects.filter(
            elective_subject__group__session=session,
            elective_subject__subject_code__iexact=code
        ).select_related("student", "elective_subject")
    )
    if not elective_regs:
        norm_exam_name = exam.subject.subject_name.upper().replace("PROGRAMME", "PROGRAM")
        norm_exam_code = exam.subject.subject_code.upper().replace("PROGRAMME", "PROGRAM")
        target_branches = set(resolve_exam_branches(exam))
        for eg in ElectiveGroup.objects.filter(session=session):
            eg_clean = eg.elective_label.upper().replace("PROGRAMME", "PROGRAM")
            if (eg_clean in norm_exam_name or eg_clean in norm_exam_code or
                norm_exam_name in eg_clean or norm_exam_code in eg_clean):
                cand_regs = ElectiveStudentRegistration.objects.filter(
                    elective_subject__group=eg
                ).select_related("student", "elective_subject")
                if target_branches and "ALL_BRANCHES" not in target_branches:
                    cand_regs = [r for r in cand_regs if normalize_branch(r.department) in target_branches]
                elective_regs = list(cand_regs)
                if elective_regs:
                    break

    students = []
    seen_ids = set()
    for reg in elective_regs:
        st = reg.student
        if st is None:
            st = Student.objects.filter(
                student_class__department__session=session,
                roll_number__iexact=reg.roll_number
            ).first()
        if st and st.student_id not in seen_ids:
            seen_ids.add(st.student_id)
            students.append(st)
    return students


def preview_exam_registration(exam: Exam) -> RegistrationPreview:
    session = exam.subject.session
    timetable_branches = resolve_exam_branches(exam)
    exam_semester = parse_semester_flexible(exam.subject.semester) or 0
    batch_name = SEMESTER_BATCH_MAP.get(exam_semester, "Unknown")
    target_branches = set(timetable_branches)

    # 1. Elective / Minor / Honours student resolution by subject code / group
    elective_students = _resolve_elective_students(exam)
    if elective_students:
        matched_classes = sorted({st.student_class.class_name for st in elective_students if st.student_class})
        logger.info(
            f"[MATCHING - ELECTIVE] exam date/session: {exam.exam_date} {exam.session} | "
            f"exam target: {timetable_branches} | "
            f"department: {[t.branch_code for t in exam.targets.all()]} | "
            f"semester: {exam_semester} | "
            f"batch: {batch_name} | "
            f"matched classes: {matched_classes} | "
            f"matched student count: {len(elective_students)}"
        )
        return RegistrationPreview(
            exam_id=exam.exam_id,
            subject_code=exam.subject.subject_code,
            subject_name=exam.subject.subject_name,
            exam_date=str(exam.exam_date),
            session=exam.session,
            semester=exam_semester,
            timetable_branches=timetable_branches,
            matched_students=elective_students,
            matched_classes=matched_classes,
            status="AUTO_RESOLVED",
            message=f"Elective students resolved by subject code/group ({len(elective_students)} students).",
        )

    # 2. Normal Department & Semester matching
    matched_students = []
    matched_classes = set()

    all_students = (
        Student.objects.filter(student_class__department__session=session)
        .select_related("student_class", "student_class__department")
        .order_by("student_class__class_name", "roll_number")
    )

    for student in all_students:
        c_dept, c_sem = get_class_branch_and_sem(
            student.student_class.class_name,
            student.student_class.semester,
            student.student_class.department.department_code,
        )
        if c_sem == exam_semester and ("ALL_BRANCHES" in target_branches or c_dept in target_branches):
            matched_students.append(student)
            matched_classes.add(student.student_class.class_name)

    matched_classes_list = sorted(matched_classes)

    logger.info(
        f"[MATCHING - NORMAL] exam date/session: {exam.exam_date} {exam.session} | "
        f"exam target: {timetable_branches} | "
        f"department: {[t.branch_code for t in exam.targets.all()]} | "
        f"semester: {exam_semester} | "
        f"batch: {batch_name} | "
        f"matched classes: {matched_classes_list} | "
        f"matched student count: {len(matched_students)}"
    )

    if not matched_students:
        return RegistrationPreview(
            exam_id=exam.exam_id,
            subject_code=exam.subject.subject_code,
            subject_name=exam.subject.subject_name,
            exam_date=str(exam.exam_date),
            session=exam.session,
            semester=exam_semester,
            timetable_branches=timetable_branches,
            matched_students=[],
            matched_classes=[],
            status="UNRESOLVED",
            message=f"No students matched exam semester {exam_semester} (batch {batch_name}) and branch targets {timetable_branches}.",
        )

    return RegistrationPreview(
        exam_id=exam.exam_id,
        subject_code=exam.subject.subject_code,
        subject_name=exam.subject.subject_name,
        exam_date=str(exam.exam_date),
        session=exam.session,
        semester=exam_semester,
        timetable_branches=timetable_branches,
        matched_students=matched_students,
        matched_classes=matched_classes_list,
        status="AUTO_RESOLVED",
        message="Students matched by semester and branch.",
    )


def preview_all_exams():
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
    unresolved_exams = 0
    results = []

    for exam in exams:
        result = create_exam_registrations(exam)
        results.append(result)
        total_created += result["registrations_created"]
        total_existing += result["registrations_existing"]

        if result["status"] == "AUTO_RESOLVED":
            auto_resolved_exams += 1
        else:
            unresolved_exams += 1

    return {
        "total_created": total_created,
        "total_existing": total_existing,
        "auto_resolved_exams": auto_resolved_exams,
        "unresolved_exams": unresolved_exams,
        "results": results,
    }
