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
