import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()


from exam_allocator.services.registration_service import (
    preview_all_exams,
)

print("=" * 110)
print("EXAM REGISTRATION PREVIEW")
print("=" * 110)


previews = preview_all_exams()

auto_resolved = 0
requires_mapping = 0
unresolved = 0


for preview in previews:

    print("\n" + "-" * 110)

    print(f"{preview.subject_code} | " f"{preview.exam_date} | " f"{preview.session}")

    print(f"Subject: {preview.subject_name}")

    print(f"Semester: S{preview.semester}")

    print(f"Branches: " f"{preview.timetable_branches}")

    print(f"Status: {preview.status}")

    print(f"Message: {preview.message}")

    if preview.matched_classes:

        print("Classes:")

        for class_name in preview.matched_classes:

            count = sum(
                1
                for student in preview.matched_students
                if (student.student_class.class_name == class_name)
            )

            print(f"  {class_name}: " f"{count} students")

    print(f"TOTAL STUDENTS: " f"{len(preview.matched_students)}")

    if preview.status == "AUTO_RESOLVED":

        auto_resolved += 1

    elif preview.status == "REQUIRES_MAPPING":

        requires_mapping += 1

    else:

        unresolved += 1


print("\n" + "=" * 110)
print("REGISTRATION PREVIEW SUMMARY")
print("=" * 110)

print(f"Total exams:       {len(previews)}")

print(f"Auto-resolved:     {auto_resolved}")

print(f"Requires mapping:  {requires_mapping}")

print(f"Unresolved:        {unresolved}")

print("Students registered in DB: 0")
