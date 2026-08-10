from django.contrib import admin

from .models import (
    Allocation,
    Class,
    Department,
    Exam,
    ExamRegistration,
    Room,
    Student,
    Subject,
    UploadedFile,
)

# Register your models here.
admin.site.register(Department)
admin.site.register(Class)
admin.site.register(Student)
admin.site.register(Subject)
admin.site.register(Exam)
admin.site.register(Room)
admin.site.register(ExamRegistration)
admin.site.register(Allocation)


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "file_kind",
        "source_format",
        "status",
        "uploaded_at",
        "processed_at",
    )
    list_filter = ("file_kind", "source_format", "status")
    search_fields = ("original_filename",)
    readonly_fields = ("uploaded_at", "processed_at")
    ordering = ("-uploaded_at",)
