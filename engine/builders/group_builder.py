import logging
from collections import defaultdict

from engine.models.student import Student
from engine.models.group import Group

logger = logging.getLogger(__name__)


class GroupBuilder:

    def build(self, students: list[Student]) -> list[Group]:
        if not students:
            logger.warning("GroupBuilder received an empty student list")
            return []

        buckets: dict[tuple, list[Student]] = defaultdict(list)

        for student in students:
            if student.is_special_subject:
                key = (
                    student.subject_category,
                    student.normalized_subject_code,
                    student.semester,
                    student.exam_date,
                    student.session,
                )
            else:
                key = (
                    "NORMAL",
                    student.department,
                    student.semester,
                    student.normalized_subject_code,
                    student.exam_date,
                    student.session,
                )
            buckets[key].append(student)

        groups: list[Group] = []

        for key, bucket in buckets.items():
            cat = key[0]
            if cat in {"ELECTIVE", "MINOR", "HONOURS"}:
                _, norm_subj, sem, exam_date, session = key
                dept = bucket[0].department
                subj_code = bucket[0].subject_code
                group_id = f"{cat}-{norm_subj}-{exam_date}-{session}"
                sections = sorted(set(s.section for s in bucket if s.section))
                section_label = "".join(sections)
            else:
                _, dept, sem, norm_subj, exam_date, session = key
                subj_code = bucket[0].subject_code
                group_id = f"{dept}-S{sem}-{subj_code}-{exam_date}-{session}"
                sections = sorted(set(s.section for s in bucket if s.section))
                section_label = "".join(sections)

            bucket.sort(key=lambda s: (s.section, s.roll_no or s.register_no))

            group = Group(
                group_id=group_id,
                department=dept,
                semester=sem,
                section=section_label,
                subject_code=subj_code,
                subject_name=bucket[0].subject_name,
                exam_date=exam_date,
                session=session,
                students=bucket,
                subject_category=cat,
            )
            groups.append(group)

        groups.sort(key=lambda g: g.strength, reverse=True)
        return groups
