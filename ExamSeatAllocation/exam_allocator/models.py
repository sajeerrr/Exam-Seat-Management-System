from django.db import models


class Department(models.Model):
    department_id = models.AutoField(primary_key=True)
    department_code = models.CharField(max_length=20, unique=True)
    department_name = models.CharField(max_length=100)

    def __str__(self):
        return self.department_code


class Class(models.Model):
    class_id = models.AutoField(primary_key=True)

    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="classes"
    )

    class_name = models.CharField(max_length=100)
    semester = models.PositiveIntegerField()
    academic_year = models.CharField(max_length=20)

    def __str__(self):
        return self.class_name


class Student(models.Model):
    student_id = models.AutoField(primary_key=True)

    student_class = models.ForeignKey(
        Class, on_delete=models.PROTECT, related_name="students"
    )
    roll_number = models.CharField(max_length=50)
    student_name = models.CharField(max_length=150)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student_class", "roll_number"],
                name="unique_roll_number_per_class",
            )
        ]

    def __str__(self):
        return f"{self.roll_number} - {self.student_name}"


class Subject(models.Model):
    subject_id = models.AutoField(primary_key=True)

    subject_code = models.CharField(max_length=30, unique=True)
    subject_name = models.CharField(max_length=150)
    semester = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.subject_code} - {self.subject_name}"


class Exam(models.Model):
    SESSION_CHOICES = [
        ("FN", "Forenoon"),
        ("AN", "Afternoon"),
    ]

    exam_id = models.AutoField(primary_key=True)

    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="exams")

    exam_date = models.DateField()
    session = models.CharField(max_length=2, choices=SESSION_CHOICES)
    duration = models.PositiveIntegerField(help_text="Duration in minutes")

    def __str__(self):
        return f"{self.subject.subject_code} - {self.exam_date} - {self.session}"


class Room(models.Model):
    room_id = models.AutoField(primary_key=True)

    room_number = models.CharField(max_length=50, unique=True)

    capacity = models.PositiveIntegerField()
    benches = models.PositiveIntegerField()
    building = models.CharField(max_length=100)

    def __str__(self):
        return self.room_number


class ExamRegistration(models.Model):
    registration_id = models.AutoField(primary_key=True)

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="exam_registrations"
    )

    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name="registrations"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "exam"], name="unique_student_exam_registration"
            )
        ]

    def __str__(self):
        return f"{self.student.roll_number} - {self.exam.subject.subject_code}"


class Allocation(models.Model):
    allocation_id = models.AutoField(primary_key=True)

    registration = models.OneToOneField(
        ExamRegistration, on_delete=models.CASCADE, related_name="allocation"
    )

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="allocations")

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="allocations")

    bench_number = models.PositiveIntegerField()
    seat_number = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exam", "room", "bench_number", "seat_number"],
                name="unique_exam_room_bench_seat",
            )
        ]

    def __str__(self):
        return (
            f"{self.registration.student.roll_number} -> "
            f"Room {self.room.room_number}, "
            f"Bench {self.bench_number}, "
            f"Seat {self.seat_number}"
        )



class UploadedFile(models.Model):
    class FileKind(models.TextChoices):
        STUDENT_LIST = "STUDENT", "Student List"
        CLASSROOM_LIST = "CLASSROOM", "Classroom List"
        TIMETABLE = "TIMETABLE", "Exam Timetable"

    class SourceFormat(models.TextChoices):
        PDF = "PDF", "PDF"
        XLSX = "XLSX", "Excel"
        IMAGE = "IMAGE", "Image"

    class Status(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploaded"
        PROCESSING = "PROCESSING", "Processing"
        VALIDATED = "VALIDATED", "Validated"
        FAILED = "FAILED", "Failed"

    upload_id = models.AutoField(primary_key=True)
    file = models.FileField(upload_to="uploads/%Y/%m/%d/")
    original_filename = models.CharField(max_length=255)
    file_kind = models.CharField(max_length=20, choices=FileKind.choices)
    source_format = models.CharField(max_length=10, choices=SourceFormat.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(blank=True)

    def __str__(self):
        return f"{self.original_filename} ({self.get_status_display()})"
# Create your models here.

