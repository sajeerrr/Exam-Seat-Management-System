from exam_allocator.models import Class

for c in Class.objects.order_by("semester", "class_name"):
    print(
        f"S{c.semester:<3} | "
        f"{c.class_name:<20} | "
        f"{c.students.count():>3} students"
    )

from exam_allocator.models import Department

for d in Department.objects.all():
    print(d.department_code, "|", d.department_name, "| classes:", d.classes.count())
