# engine/builders/group_builder.py
"""
Automatically builds Groups from a list of annotated Student objects.

Merge strategy
--------------
Students from the same (department, semester, subject_code, exam_date, session)
but **different sections** (e.g. CE6A and CE6B both writing 23CET601) are merged
into ONE combined group.  The section field on the merged group is set to ""
and the group_id omits the section letter.

This is the correct real-world behaviour: CE students from both sections sit
in the same rolling allocation and are interleaved with other departments room
by room — not section by section.

Grouping key (after merge): (department, semester, subject_code, exam_date, session)
"""

import logging
from collections import defaultdict

from engine.models.student import Student
from engine.models.group import Group

logger = logging.getLogger(__name__)


class GroupBuilder:
    """
    Groups students by exam slot, merging sections A+B into one group.

    Usage
    -----
    groups = GroupBuilder().build(students)
    """

    def build(self, students: list[Student]) -> list[Group]:
        if not students:
            logger.warning("GroupBuilder received an empty student list")
            return []

        # Bucket by (dept, sem, subject_code, exam_date, session)
        # Section is intentionally excluded so A and B merge together.
        buckets: dict[tuple, list[Student]] = defaultdict(list)

        for student in students:
            key = (
                student.department,
                student.semester,
                student.subject_code,
                student.exam_date,
                student.session,
            )
            buckets[key].append(student)

        groups: list[Group] = []

        for (dept, sem, subj_code, exam_date, session), bucket in buckets.items():
            # Sort students within the merged group by section then roll number
            # so the allocation order is A01, A02, … A75, B01, B02, … B72
            bucket.sort(key=lambda s: (s.section, s.roll_no or s.register_no))

            # Collect the distinct sections that were merged
            sections = sorted(set(s.section for s in bucket if s.section))
            section_label = "".join(sections)   # "AB", "A", "B", etc.

            group_id = f"{dept}-S{sem}-{subj_code}-{exam_date}-{session}"

            group = Group(
                group_id     = group_id,
                department   = dept,
                semester     = sem,
                section      = section_label,
                subject_code = subj_code,
                subject_name = bucket[0].subject_name,
                exam_date    = exam_date,
                session      = session,
                students     = bucket,
            )
            groups.append(group)
            logger.debug(
                "Group built: %s  (%d students, sections=%s)",
                group_id, group.strength, section_label,
            )

        # Sort largest group first (feeds well into Modified-FFD primary allocator)
        groups.sort(key=lambda g: g.strength, reverse=True)

        logger.info(
            "GroupBuilder: %d groups built from %d students",
            len(groups), len(students),
        )
        return groups
