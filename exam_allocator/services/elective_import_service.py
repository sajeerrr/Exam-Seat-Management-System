"""
Elective import service.

Persists parsed elective extraction results into session-scoped database models.
Groups students strictly according to their ACTUAL SUBJECT, across departments and sections.
"""

from __future__ import annotations

from django.db import transaction

from exam_allocator.models import (
    AllocationSession,
    ElectiveGroup,
    ElectiveSubject,
    ElectiveStudentRegistration,
    Student,
)
from exam_allocator.parsers.elective_parser import ElectiveExtractionResult


@transaction.atomic
def import_elective_data(session: AllocationSession, result: ElectiveExtractionResult) -> dict:
    """
    Import parsed elective records into the database for the given session.
    Safely updates or replaces existing registrations for the same source file.
    """
    if result.source_file:
        # Safely clean up prior registrations from the same source file for this session
        ElectiveStudentRegistration.objects.filter(
            elective_subject__group__session=session,
            source_file=result.source_file,
        ).delete()

    groups_created = 0
    subjects_created = 0
    registrations_created = 0
    departments_seen = set()
    groups_seen = set()
    subjects_seen = set()
    total_students_registered = 0

    for group_rec in result.groups:
        elective_label = group_rec.elective_label or "Programme Elective"
        group, g_created = ElectiveGroup.objects.update_or_create(
            session=session,
            elective_label=elective_label,
            defaults={
                "department_code": group_rec.department_code or "ELECTIVE",
                "department_name": group_rec.department_name or "Electives",
            },
        )
        if g_created:
            groups_created += 1
        groups_seen.add(group.pk)

        for subj_rec in group_rec.subjects:
            subject, s_created = ElectiveSubject.objects.update_or_create(
                group=group,
                subject_code=subj_rec.subject_code,
                defaults={
                    "subject_name": subj_rec.subject_name,
                    "original_subject_code": subj_rec.original_subject_code,
                    "elective_type": elective_label,
                },
            )
            if s_created:
                subjects_created += 1
            subjects_seen.add(subject.pk)

            for stud_rec in subj_rec.students:
                # Try to link with existing Student in this session if available
                student = Student.objects.filter(
                    student_class__department__session=session,
                    roll_number__iexact=stud_rec.roll_number,
                ).first()

                dept_code = stud_rec.department
                if not dept_code and student and student.student_class and student.student_class.department:
                    dept_code = student.student_class.department.dept_code

                class_name = stud_rec.class_name
                if not class_name and student and student.student_class:
                    class_name = student.student_class.class_name

                if dept_code:
                    departments_seen.add(dept_code)

                _, reg_created = ElectiveStudentRegistration.objects.update_or_create(
                    elective_subject=subject,
                    roll_number=stud_rec.roll_number,
                    defaults={
                        "student": student,
                        "student_name": stud_rec.student_name,
                        "department": dept_code,
                        "class_name": class_name,
                        "source_file": result.source_file,
                        "source_sheet_or_page": stud_rec.source_sheet_or_page,
                        "source_row": stud_rec.source_row,
                        "is_unresolved": stud_rec.is_unresolved,
                        "unresolved_reason": stud_rec.unresolved_reason,
                    },
                )
                if reg_created:
                    registrations_created += 1
                total_students_registered += 1

    # Remove any empty subjects that have no students registered
    empty_subjects = ElectiveSubject.objects.filter(
        group__session=session,
        student_registrations__isnull=True,
    )
    empty_subjects.delete()

    return {
        "departments_count": len(departments_seen),
        "groups_count": len(groups_seen),
        "subjects_count": len(subjects_seen),
        "students_count": total_students_registered,
        "groups_created": groups_created,
        "subjects_created": subjects_created,
        "registrations_created": registrations_created,
        "duplicates_count": result.report.total_duplicates,
        "unresolved_count": result.report.total_unresolved,
        "warnings": result.issues,
    }
