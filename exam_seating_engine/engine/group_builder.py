from collections import defaultdict
from ..models.group import Group


class GroupBuilder:

    def build(self, students):

        groups = {}

        for student in students:

            key = ( #set a fixed key for group
                student.exam_date,
                student.session,
                student.subject_code,
                student.department,
                student.semester,
                student.section,
            )

            if key not in groups:

                group_id = (
                    f"{student.exam_date}_"
                    f"{student.session}_"
                    f"{student.subject_code}_"
                    f"{student.department}"
                    f"{student.semester}"
                    f"{student.section}"
                )

                groups[key] = Group(
                    group_id=group_id,
                    department=student.department,
                    semester=student.semester,
                    section=student.section,
                    subject_code=student.subject_code,
                    subject_name=student.subject_name,
                    exam_date=student.exam_date,
                    session=student.session,
                )

            groups[key].students.append(student)

        return list(groups.values())