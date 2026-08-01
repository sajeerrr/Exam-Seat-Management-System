# engine/builders/group_builder.py
"""
Automatically builds Groups from a list of annotated Student objects.

Grouping key: (department, semester, section, subject_code, exam_date, session)

This replaces all manual build_group("CE", 75) calls.
Students must already have subject_code/exam_date/session stamped
(done by SessionFilter before calling GroupBuilder).
"""

import logging
from collections import defaultdict

from engine.models.student import Student
from engine.models.group import Group

logger = logging.getLogger(__name__)


class GroupBuilder:
    """
    Groups students automatically by their exam slot attributes.

    Usage
    -----
    groups = GroupBuilder().build(students)
    """

    def build(self, students: list[Student]) -> list[Group]:
        if not students:
            logger.warning("GroupBuilder received an empty student list")
            return []

        # Bucket students by their grouping key
        buckets: dict[tuple, list[Student]] = defaultdict(list)

        for student in students:
            key = (
                student.department,
                student.semester,
                student.section,
                student.subject_code,
                student.exam_date,
                student.session,
            )
            buckets[key].append(student)

        groups: list[Group] = []

        for (dept, sem, section, subj_code, exam_date, session), bucket in buckets.items():
            # Build a stable group_id
            group_id = f"{dept}-S{sem}{section}-{subj_code}-{exam_date}-{session}"

            group = Group(
                group_id     = group_id,
                department   = dept,
                semester     = sem,
                section      = section,
                subject_code = subj_code,
                subject_name = bucket[0].subject_name,
                exam_date    = exam_date,
                session      = session,
                students     = bucket,
            )
            groups.append(group)
            logger.debug(
                "Group built: %s  (%d students)",
                group_id, group.strength,
            )

        # Sort largest group first (feeds well into Modified-FFD primary allocator)
        groups.sort(key=lambda g: g.strength, reverse=True)

        logger.info(
            "GroupBuilder: %d groups built from %d students",
            len(groups), len(students),
        )
        return groups
