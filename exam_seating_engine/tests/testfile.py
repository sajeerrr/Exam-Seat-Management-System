from ..tests.sample_data import students
from ..engine.group_builder import GroupBuilder

builder = GroupBuilder()
groups = builder.build(students)

print(f"Total Groups: {len(groups)}")
print()

for group in groups:
    print("------------------")
    print(group.department, end="")
    print(group.semester, end="")
    print(group.section)
    print(group.subject_name)
    print(f"Strength: {len(group.students)}")