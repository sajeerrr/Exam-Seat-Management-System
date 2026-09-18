from exam_allocator.models import ExamTarget

print("Total targets:", ExamTarget.objects.count())

print("\nTARGET TYPES")
for target_type in ExamTarget.objects.values_list("target_type", flat=True).distinct():
    count = ExamTarget.objects.filter(target_type=target_type).count()

    print(target_type, ":", count)


print("\nALL TARGETS")
for target in ExamTarget.objects.select_related("exam", "exam__subject").order_by(
    "exam__exam_date",
    "exam__session",
    "exam__exam_id",
    "target_type",
    "branch_code",
    "slot",
):
    print(
        f"{target.exam.subject.subject_code:30} | "
        f"{target.exam.exam_date} | "
        f"{target.exam.session} | "
        f"{target.target_type:20} | "
        f"{target.branch_code:8} | "
        f"{target.slot}"
    )
