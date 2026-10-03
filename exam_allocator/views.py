from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from collections import defaultdict


from .models import (
    Allocation,
    AllocationSession,
    Class,
    Department,
    Exam,
    ExamRegistration,
    ExamTarget,
    Room,
    Student,
    Subject,
    UploadedFile,
)
from .services.allocation_workflow import (
    AllocationWorkflowError,
    run_allocation,
)

from .services.session_allocation_service import (
    SessionAllocationError,
    run_session_allocation,
)

from .parsers.student_parser import parse_student_excel
from .parsers.student_pdf_parser import parse_student_pdf
from .parsers.classroom_parser import parse_classroom_excel
from .parsers.timetable_parser import parse_timetable_excel
from .parsers.timetable_pdf_parser import parse_timetable_pdf

from .services.import_service import (
    import_students,
    import_classrooms,
    import_timetable,
)
from .services.registration_service import (
    create_all_exam_registrations,
)





@ensure_csrf_cookie
def session_list(request):

    sessions = AllocationSession.objects.order_by(
        "-updated_at",
        "-session_id",
    )

    return render(
        request,
        "exam_allocator/session_list.html",
        {
            "sessions": sessions,
        },
    )



@require_POST
def delete_session(request, session_id):
    """
    Permanently delete a session and ALL its associated data.

    Deletion order matters because of on_delete=PROTECT constraints:
      Allocation      ← PROTECT from Room
      ExamRegistration← CASCADE from Student/Exam (but explicit for safety)
      ExamTarget      ← CASCADE from Exam       (but explicit for safety)
      Exam            ← PROTECT from Subject
      Student         ← PROTECT from Class
      Class           ← PROTECT from Department
      AllocationSession.delete() → cascades Department, Subject, Room, UploadedFile
    """
    session = get_object_or_404(AllocationSession, pk=session_id)
    session_name = session.name

    try:
        with transaction.atomic():
            # Pre-fetch IDs before any deletes so queries remain valid.
            dept_ids  = list(Department.objects.filter(session=session)
                             .values_list("department_id", flat=True))
            class_ids = list(Class.objects.filter(department_id__in=dept_ids)
                             .values_list("class_id", flat=True))
            subj_ids  = list(Subject.objects.filter(session=session)
                             .values_list("subject_id", flat=True))
            exam_ids  = list(Exam.objects.filter(subject_id__in=subj_ids)
                             .values_list("exam_id", flat=True))

            # 1. Allocations — must go before Rooms are deleted
            Allocation.objects.filter(exam_id__in=exam_ids).delete()

            # 2. ExamRegistrations
            ExamRegistration.objects.filter(exam_id__in=exam_ids).delete()

            # 3. ExamTargets
            ExamTarget.objects.filter(exam_id__in=exam_ids).delete()

            # 4. Exams — PROTECT on Subject, safe now
            Exam.objects.filter(pk__in=exam_ids).delete()

            # 5. Students — PROTECT on Class, safe now (registrations gone)
            Student.objects.filter(student_class_id__in=class_ids).delete()

            # 6. Classes — PROTECT on Department, safe now
            Class.objects.filter(pk__in=class_ids).delete()

            # 7. Session itself — cascades Department, Subject, Room, UploadedFile
            session.delete()

        messages.success(
            request,
            f'“{session_name}” and all its data have been permanently deleted.',
        )

    except Exception as exc:
        messages.error(
            request,
            f'Could not delete “{session_name}”: {exc}',
        )

    return redirect("exam_allocator:session_list")


def create_session(request):

    if request.method == "POST":

        name = request.POST.get("name", "").strip()

        if not name:
            return render(
                request,
                "exam_allocator/create_session.html",
                {
                    "error": "Please enter a session name.",
                },
            )

        session = AllocationSession.objects.create(
            name=name,
        )

        return redirect(
            "exam_allocator:session_detail",
            session_id=session.session_id,
        )

    return render(
        request,
        "exam_allocator/create_session.html",
    )


def session_detail(request, session_id):
    # The intermediate session dashboard is no longer needed; 
    # redirect directly to the review dashboard instead.
    return redirect("exam_allocator:review_session", session_id=session_id)


def exam_list(request, session_id=None):

    if session_id is not None:
        session = get_object_or_404(
            AllocationSession,
            session_id=session_id,
        )

        exams = (
            Exam.objects.select_related("subject")
            .filter(subject__session=session)
            .order_by(
                "exam_date",
                "session",
                "exam_id",
            )
        )

    else:
        session = None

        exams = Exam.objects.select_related("subject").order_by(
            "exam_date",
            "session",
            "exam_id",
        )

    return render(
        request,
        "exam_allocator/exam_list.html",
        {
            "exams": exams,
            "session": session,
        },
    )


def generate_registrations(request, session_id):

    session = get_object_or_404(
        AllocationSession,
        session_id=session_id,
    )

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "error": "Only POST requests are allowed.",
            },
            status=405,
        )

    try:
        # ---------------------------------------------------------
        # STEP 1: GENERATE / VERIFY EXAM REGISTRATIONS
        # ---------------------------------------------------------

        registration_result = create_all_exam_registrations(session)

        # ---------------------------------------------------------
        # STEP 2: RUN COMPLETE SESSION-WIDE ALLOCATION
        # ---------------------------------------------------------

        allocation_result = run_session_allocation(session)

    except SessionAllocationError as exc:

        return render(
            request,
            "exam_allocator/registration_result.html",
            {
                "session": session,
                "result": (
                    registration_result if "registration_result" in locals() else None
                ),
                "allocation_error": str(exc),
            },
            status=400,
        )

    except Exception as exc:

        return render(
            request,
            "exam_allocator/registration_result.html",
            {
                "session": session,
                "result": (
                    registration_result if "registration_result" in locals() else None
                ),
                "allocation_error": str(exc),
            },
            status=400,
        )

    # ---------------------------------------------------------
    # STEP 3: ALLOCATION IS COMPLETE
    #
    # Send the user directly to the final allocation page.
    # ---------------------------------------------------------

    return redirect(
        "exam_allocator:session_allocation_result",
        session_id=session.session_id,
    )


def generate_session_allocation(request, session_id):
    session = get_object_or_404(
        AllocationSession,
        session_id=session_id,
    )
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Only POST requests are allowed."}, status=405)

    try:
        from exam_allocator.services.registration_service import create_all_exam_registrations
        from exam_allocator.services.session_allocation_service import run_session_allocation
        create_all_exam_registrations(session)
        run_session_allocation(session)
    except Exception as exc:
        messages.warning(request, f"Allocation encountered an error: {exc}")

    return redirect(
        "exam_allocator:session_allocation_result",
        session_id=session.session_id,
    )


def session_allocation_result(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    
    # Fetch available Date-Session slots globally
    from exam_allocator.models import Exam, Allocation
    exam_slots = Exam.objects.filter(subject__session=session).order_by('exam_date', 'session').values('exam_date', 'session').distinct()
    
    slots = []
    for slot in exam_slots:
        slots.append({
            'date': slot['exam_date'],
            'shift': slot['session']
        })
        
    date_filter = request.GET.get('date')
    shift_filter = request.GET.get('shift')
    
    selected_slot = None
    if date_filter and shift_filter:
        for s in slots:
            if str(s['date']) == date_filter and s['shift'] == shift_filter:
                selected_slot = s
                break
                
    if not selected_slot and slots:
        selected_slot = slots[0]
        
    rooms_data = {}
    
    missing_data_reason = ""
    if selected_slot:
        from exam_allocator.models import ExamRegistration
        exams_in_slot = Exam.objects.filter(
            subject__session=session,
            exam_date=selected_slot['date'],
            session=selected_slot['shift']
        )
        total_regs = ExamRegistration.objects.filter(exam__in=exams_in_slot).count()
        if total_regs == 0:
            missing_data_reason = "No students are currently registered for the exams during this specific slot. This typically happens because the student list Excel files for the matching classes (like Semester 8) were not uploaded in the Import Data step!"
        
        # Fetch ALL allocations in this slot
        allocations = (
            Allocation.objects.filter(
                exam__subject__session=session,
                exam__exam_date=selected_slot['date'],
                exam__session=selected_slot['shift']
            )
            .select_related(
                "registration__student",
                "registration__student__student_class",
                "registration__student__student_class__department",
                "room",
            )
            .order_by("room__room_number", "bench_number", "seat_number")
        )
        
        # Group by room
        from collections import defaultdict
        room_allocs = defaultdict(list)
        for a in allocations:
            room_allocs[a.room].append(a)
            
        def get_stream_summary(allocs, seat_num):
            seat_allocs = [a for a in allocs if a.seat_number == seat_num]
            if not seat_allocs:
                return "None"
            
            seat_allocs.sort(key=lambda x: x.bench_number)
            summary = []
            
            # The excel has abbreviations like ME, CS. Usually it's department_code
            current_dept = seat_allocs[0].registration.student.student_class.department.department_code
            start_bench = seat_allocs[0].bench_number
            prev_bench = start_bench
            
            for a in seat_allocs[1:]:
                dept = a.registration.student.student_class.department.department_code
                current_num = a.bench_number
                
                if dept != current_dept or current_num != prev_bench + 1:
                    if start_bench == prev_bench:
                        summary.append(f"{start_bench} {current_dept}")
                    else:
                        summary.append(f"{start_bench}-{prev_bench} {current_dept}")
                    current_dept = dept
                    start_bench = current_num
                prev_bench = current_num
                
            if start_bench == prev_bench:
                summary.append(f"{start_bench} {current_dept}")
            else:
                summary.append(f"{start_bench}-{prev_bench} {current_dept}")
                
            return ", ".join(summary)
            
        for room, allocs in room_allocs.items():
            rooms_data[room.room_number] = {
                'room_number': room.room_number,
                'total_students': len(allocs),
                'stream_a': get_stream_summary(allocs, 1),
                'stream_b': get_stream_summary(allocs, 2),
                'stream_c': get_stream_summary(allocs, 3),
                'exam_date': selected_slot['date'],
                'session': selected_slot['shift'],
            }

    # sort rooms numerically
    def try_int(val):
        try:
            return (0, int(val))
        except ValueError:
            return (1, val)

    sorted_rooms = [rooms_data[k] for k in sorted(rooms_data.keys(), key=try_int)]

    return render(
        request,
        "exam_allocator/session_allocation_result.html",
        {
            "session": session,
            "slots": slots,
            "selected_slot": selected_slot,
            "rooms": sorted_rooms,
            "missing_data_reason": missing_data_reason,
        },
    )

def generate_allocation(request, exam_id):

    if request.method != "POST":
        return JsonResponse(
            {"error": "Only POST requests are allowed."},
            status=405,
        )

    try:
        result = run_allocation(exam_id)

    except AllocationWorkflowError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "exam_id": result["exam"].exam_id,
            "subject_code": result["exam"].subject.subject_code,
            "subject_name": result["exam"].subject.subject_name,
            "students": len(result["students"]),
            "classrooms": len(result["classrooms"]),
            "groups": len(result["groups"]),
            "allocations": len(result["allocations"]),
        }
    )


def allocation_list(request, exam_id):

    exam = get_object_or_404(
        Exam.objects.select_related("subject"),
        exam_id=exam_id,
    )

    allocations = (
        Allocation.objects.filter(exam=exam)
        .select_related(
            "registration__student",
            "room",
        )
        .order_by(
            "room__room_number",
            "bench_number",
            "seat_number",
        )
    )

    return render(
        request,
        "exam_allocator/allocation_list.html",
        {
            "exam": exam,
            "allocations": allocations,
        },
    )


def upload_file(request, session_id):

    session = get_object_or_404(
        AllocationSession,
        session_id=session_id,
    )

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "error": "Only POST requests are allowed.",
            },
            status=405,
        )

    uploaded_files = request.FILES.getlist("file")
    file_kind = request.POST.get("file_kind", "").strip().upper()

    if not uploaded_files:
        messages.error(request, "No file was uploaded.")

        return redirect(
            "exam_allocator:session_detail",
            session_id=session.session_id,
        )

    valid_kinds = {
        UploadedFile.FileKind.STUDENT_LIST,
        UploadedFile.FileKind.CLASSROOM_LIST,
        UploadedFile.FileKind.TIMETABLE,
    }

    if file_kind not in valid_kinds:
        messages.error(request, "Invalid file type.")

        return redirect(
            "exam_allocator:session_detail",
            session_id=session.session_id,
        )

    # Accumulators for aggregate statistics
    total_stats = {
        "students_created": 0,
        "classes_created": 0,
        "departments_created": 0,
        "rooms_created": 0,
        "exams_created": 0,
        "subjects_created": 0,
        "targets_created": 0,
    }
    
    error_occurred = False

    try:
        for uploaded in uploaded_files:
            filename = uploaded.name.lower()

            if filename.endswith(".xlsx"):
                source_format = UploadedFile.SourceFormat.XLSX

            elif filename.endswith(".pdf"):
                source_format = UploadedFile.SourceFormat.PDF

            elif filename.endswith((".png", ".jpg", ".jpeg")):
                source_format = UploadedFile.SourceFormat.IMAGE

            else:
                messages.error(
                    request,
                    f"Unsupported file format for {uploaded.name}.",
                )
                continue

            # ---------------------------------------------------------
            # Create UploadedFile record
            # ---------------------------------------------------------

            record = UploadedFile.objects.create(
                session=session,
                file=uploaded,
                original_filename=uploaded.name,
                file_kind=file_kind,
                source_format=source_format,
                status=UploadedFile.Status.PROCESSING,
            )

            try:
                # -----------------------------------------------------
                # Student List
                # -----------------------------------------------------
                if file_kind == UploadedFile.FileKind.STUDENT_LIST:
                    if source_format == UploadedFile.SourceFormat.XLSX:
                        result = parse_student_excel(record.file.path)
                    elif source_format == UploadedFile.SourceFormat.PDF:
                        result = parse_student_pdf(record.file.path)
                    else:
                        raise ValueError(
                            "Student List currently supports Excel (.xlsx) and PDF files only."
                        )

                    stats = import_students(
                        result,
                        session,
                    )
                    total_stats["students_created"] += stats.get("students_created", 0)
                    total_stats["classes_created"] += stats.get("classes_created", 0)
                    total_stats["departments_created"] += stats.get("departments_created", 0)

                # -----------------------------------------------------
                # Classroom List
                # -----------------------------------------------------
                elif file_kind == UploadedFile.FileKind.CLASSROOM_LIST:
                    if source_format != UploadedFile.SourceFormat.XLSX:
                        raise ValueError(
                            "Classroom List currently supports Excel (.xlsx) files only."
                        )

                    result = parse_classroom_excel(record.file.path)
                    stats = import_classrooms(
                        result,
                        session,
                    )
                    total_stats["rooms_created"] += stats.get("rooms_created", 0)

                # -----------------------------------------------------
                # Timetable
                # -----------------------------------------------------
                elif file_kind == UploadedFile.FileKind.TIMETABLE:
                    if source_format == UploadedFile.SourceFormat.XLSX:
                        result = parse_timetable_excel(record.file.path)
                    elif source_format == UploadedFile.SourceFormat.PDF:
                        result = parse_timetable_pdf(record.file.path)
                    else:
                        raise ValueError(
                            "Exam Timetable currently supports Excel (.xlsx) and PDF files only."
                        )

                    stats = import_timetable(
                        result,
                        session,
                    )
                    total_stats["exams_created"] += stats.get("exams_created", 0)
                    total_stats["subjects_created"] += stats.get("subjects_created", 0)
                    total_stats["targets_created"] += stats.get("targets_created", 0)

                # -----------------------------------------------------
                # Mark upload as successfully processed
                # -----------------------------------------------------
                record.status = UploadedFile.Status.VALIDATED
                record.processed_at = timezone.now()
                record.error_log = ""
                record.save(
                    update_fields=[
                        "status",
                        "processed_at",
                        "error_log",
                    ]
                )

            except Exception as exc:
                record.status = UploadedFile.Status.FAILED
                record.processed_at = timezone.now()
                record.error_log = str(exc)
                record.save(
                    update_fields=[
                        "status",
                        "processed_at",
                        "error_log",
                    ]
                )
                messages.error(
                    request,
                    f"Import failed for {uploaded.name}: {exc}",
                )
                error_occurred = True

        if not error_occurred or len(uploaded_files) > 1:
            if file_kind == UploadedFile.FileKind.STUDENT_LIST:
                message = (
                    f"Student list imported: "
                    f"{total_stats['students_created']} students, "
                    f"{total_stats['classes_created']} classes, "
                    f"{total_stats['departments_created']} departments created."
                )
            elif file_kind == UploadedFile.FileKind.CLASSROOM_LIST:
                message = (
                    f"Classroom list imported: "
                    f"{total_stats['rooms_created']} rooms created."
                )
            elif file_kind == UploadedFile.FileKind.TIMETABLE:
                message = (
                    f"Timetable imported: "
                    f"{total_stats['subjects_created']} subjects, "
                    f"{total_stats['exams_created']} exams, "
                    f"{total_stats['targets_created']} targets created."
                )
            if not error_occurred or total_stats["students_created"] > 0 or total_stats["rooms_created"] > 0 or total_stats["exams_created"] > 0:
                messages.success(request, message)

    except Exception as exc:
        messages.error(
            request,
            f"An unexpected error occurred during upload: {exc}",
        )

    return redirect(
        "exam_allocator:import_data",
        session_id=session.session_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT DATA PAGE
# ─────────────────────────────────────────────────────────────────────────────

def import_data(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    uploaded_files = (
        session.uploaded_files.all().order_by("-uploaded_at")
    )
    return render(
        request,
        "exam_allocator/import_data.html",
        {
            "session": session,
            "uploaded_files": uploaded_files,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW SESSION PAGE
# ─────────────────────────────────────────────────────────────────────────────

def review_session(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)

    # Departments (prefetch classes)
    departments = (
        Department.objects.filter(session=session)
        .prefetch_related("classes__students")
        .order_by("department_code")
    )

    departments_count = departments.count()
    students_count = Student.objects.filter(
        student_class__department__session=session
    ).count()
    rooms = Room.objects.filter(session=session).order_by("room_number")
    rooms_count = rooms.count()

    # Build timetable structure grouped by date → FN/AN
    exams_qs = (
        Exam.objects.filter(subject__session=session)
        .select_related("subject")
        .prefetch_related("targets")
        .order_by("exam_date", "session", "subject__subject_code")
    )

    date_map = defaultdict(lambda: {"FN": [], "AN": []})
    for exam in exams_qs:
        date_map[exam.exam_date][exam.session].append(exam)

    timetable_days = []
    for date in sorted(date_map.keys()):
        slots = []
        for sess_label in ["FN", "AN"]:
            if date_map[date][sess_label]:
                slots.append({
                    "session": sess_label,
                    "exams": date_map[date][sess_label],
                })
        timetable_days.append({"date": date, "slots": slots})

    exam_days_count = len(timetable_days)

    return render(
        request,
        "exam_allocator/review_session.html",
        {
            "session": session,
            "departments": departments,
            "departments_count": departments_count,
            "students_count": students_count,
            "rooms": rooms,
            "rooms_count": rooms_count,
            "timetable_days": timetable_days,
            "exam_days_count": exam_days_count,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# API: GET STUDENTS FOR A CLASS
# ─────────────────────────────────────────────────────────────────────────────

def api_class_students(request, class_id):
    cls = get_object_or_404(Class, class_id=class_id)
    students = list(
        cls.students.all().order_by("roll_number").values(
            "student_id", "roll_number", "student_name", "admission_no", "uni_reg_no", "gender"
        )
    )
    data = [
        {
            "id": s["student_id"],
            "roll_number": s["roll_number"],
            "student_name": s["student_name"],
            "admission_no": s["admission_no"],
            "uni_reg_no": s["uni_reg_no"],
            "gender": s["gender"],
        }
        for s in students
    ]
    return JsonResponse(data, safe=False)


# ─────────────────────────────────────────────────────────────────────────────
# API: EDIT STUDENT
# ─────────────────────────────────────────────────────────────────────────────

import json

@require_POST
def api_edit_student(request, student_id):
    student = get_object_or_404(Student, student_id=student_id)
    try:
        body = json.loads(request.body)
        roll = body.get("roll_number", "").strip()
        name = body.get("student_name", "").strip()
        adm = body.get("admission_no", "").strip()
        reg = body.get("uni_reg_no", "").strip()
        gender = body.get("gender", "").strip()
        
        if not roll or not name:
            return JsonResponse({"success": False, "error": "Roll number and name are required."}, status=400)

        # Check uniqueness within class (excluding self)
        if (
            Student.objects.filter(student_class=student.student_class, roll_number=roll)
            .exclude(pk=student_id)
            .exists()
        ):
            return JsonResponse({"success": False, "error": f"Roll number '{roll}' already exists in this class."}, status=400)

        student.roll_number = roll
        student.student_name = name
        student.admission_no = adm
        student.uni_reg_no = reg
        student.gender = gender
        student.save(update_fields=["roll_number", "student_name", "admission_no", "uni_reg_no", "gender"])
        return JsonResponse({
            "success": True, 
            "roll_number": student.roll_number, 
            "student_name": student.student_name,
            "admission_no": student.admission_no,
            "uni_reg_no": student.uni_reg_no,
            "gender": student.gender
        })
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# API: ADD ROOM
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_add_room(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    try:
        body = json.loads(request.body)
        room_number = body.get("room_number", "").strip()
        building = body.get("building", "").strip()
        capacity = int(body.get("capacity", 0))
        benches = int(body.get("benches", 0))
        if not room_number or not building or capacity < 1 or benches < 1:
            return JsonResponse({"success": False, "error": "All fields are required and must be valid."}, status=400)

        if Room.objects.filter(session=session, room_number=room_number).exists():
            return JsonResponse({"success": False, "error": f"Room '{room_number}' already exists in this session."}, status=400)

        room = Room.objects.create(
            session=session,
            room_number=room_number,
            building=building,
            capacity=capacity,
            benches=benches,
        )
        return JsonResponse({"success": True, "room_id": room.room_id})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# API: EDIT ROOM
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_edit_room(request, room_id):
    room = get_object_or_404(Room, room_id=room_id)
    try:
        body = json.loads(request.body)
        room_number = body.get("room_number", "").strip()
        building = body.get("building", "").strip()
        capacity = int(body.get("capacity", 0))
        benches = int(body.get("benches", 0))
        if not room_number or not building or capacity < 1 or benches < 1:
            return JsonResponse({"success": False, "error": "All fields are required and must be valid."}, status=400)

        # Check uniqueness within session (excluding self)
        if (
            Room.objects.filter(session=room.session, room_number=room_number)
            .exclude(pk=room_id)
            .exists()
        ):
            return JsonResponse({"success": False, "error": f"Room '{room_number}' already exists in this session."}, status=400)

        room.room_number = room_number
        room.building = building
        room.capacity = capacity
        room.benches = benches
        room.save(update_fields=["room_number", "building", "capacity", "benches"])
        return JsonResponse({"success": True})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# API: DELETE ROOM
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_delete_room(request, room_id):
    room = get_object_or_404(Room, room_id=room_id)
    try:
        # Cannot delete if it has allocations
        if room.allocations.exists():
            return JsonResponse(
                {"success": False, "error": "Cannot delete a room that has existing seat allocations."},
                status=400,
            )
        room.delete()
        return JsonResponse({"success": True})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# API: TARGET STUDENTS FOR TIMETABLE DRILL-DOWN
# ─────────────────────────────────────────────────────────────────────────────

def api_exam_target_students(request, exam_id):
    exam = get_object_or_404(Exam, exam_id=exam_id)
    branch = request.GET.get("branch", "").strip()
    slot = request.GET.get("slot", "").strip()

    # Find matching classes: department_code matches branch_code, semester matches subject semester
    students_qs = Student.objects.filter(
        student_class__department__session=exam.subject.session,
        student_class__department__department_code=branch,
        student_class__semester=exam.subject.semester,
    ).select_related("student_class__department").order_by("roll_number")

    data = [
        {
            "roll_number": s.roll_number,
            "student_name": s.student_name,
            "class_name": s.student_class.class_name,
        }
        for s in students_qs
    ]
    return JsonResponse(data, safe=False)
