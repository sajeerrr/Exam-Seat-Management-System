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
from .parsers.classroom_parser import parse_classroom_excel
from .parsers.timetable_parser import parse_timetable_excel

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

    session = get_object_or_404(
        AllocationSession,
        session_id=session_id,
    )

    departments_count = session.departments.count()

    classes_count = Class.objects.filter(department__session=session).count()

    students_count = Student.objects.filter(
        student_class__department__session=session
    ).count()

    # Each exam record corresponds to one timetable row (subject + date + session).
    # We count subjects the same way so both stats are consistent and equal.
    exams_count = Exam.objects.filter(subject__session=session).count()
    subjects_count = exams_count  # one subject entry per exam slot

    rooms_count = session.rooms.count()

    registrations_count = ExamRegistration.objects.filter(
        exam__subject__session=session
    ).count()

    allocations_count = Allocation.objects.filter(
        exam__subject__session=session
    ).count()

    return render(
        request,
        "exam_allocator/session_detail.html",
        {
            "session": session,
            "departments_count": departments_count,
            "classes_count": classes_count,
            "students_count": students_count,
            "subjects_count": subjects_count,
            "exams_count": exams_count,
            "rooms_count": rooms_count,
            "registrations_count": registrations_count,
            "allocations_count": allocations_count,
        },
    )


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
        return JsonResponse(
            {
                "success": False,
                "error": "Only POST requests are allowed.",
            },
            status=405,
        )

    try:
        run_session_allocation(session)

    except SessionAllocationError as exc:
        # Allocation partially failed. Show a warning but still redirect to
        # the results page so the user can see whatever was successfully allocated.
        messages.warning(
            request,
            f"Allocation completed with warnings: {exc}",
        )

    except Exception as exc:
        messages.warning(
            request,
            f"Allocation encountered an error: {exc}",
        )

    return redirect(
        "exam_allocator:session_allocation_result",
        session_id=session.session_id,
    )


def session_allocation_result(request, session_id):

    session = get_object_or_404(
        AllocationSession,
        session_id=session_id,
    )

    allocations = list(
        Allocation.objects.filter(exam__subject__session=session)
        .select_related(
            "exam",
            "exam__subject",
            "registration__student",
            "room",
        )
        .order_by(
            "exam__exam_date",
            "exam__session",
            "room__room_number",
            "bench_number",
            "seat_number",
        )
    )

    # ---------------------------------------------------------
    # GROUP ALLOCATIONS BY EXAMINATION SLOT
    # ---------------------------------------------------------

    slot_map = {}

    for allocation in allocations:

        slot_key = (
            allocation.exam.exam_date,
            allocation.exam.session,
        )

        if slot_key not in slot_map:
            slot_map[slot_key] = {
                "date": allocation.exam.exam_date,
                "session": allocation.exam.session,
                "rooms": {},
            }

        room_number = allocation.room.room_number

        if room_number not in slot_map[slot_key]["rooms"]:
            slot_map[slot_key]["rooms"][room_number] = {
                "room": allocation.room,
                "benches": {},
            }

        bench_number = allocation.bench_number

        if bench_number not in slot_map[slot_key]["rooms"][room_number]["benches"]:
            slot_map[slot_key]["rooms"][room_number]["benches"][bench_number] = {
                1: None,
                2: None,
                3: None,
            }

        slot_map[slot_key]["rooms"][room_number]["benches"][bench_number][
            allocation.seat_number
        ] = allocation

    # ---------------------------------------------------------
    # BUILD TEMPLATE DATA
    #
    # Classroom structure:
    #
    # SET 1 | SET 2 | SET 3 | SET 4 | SET 5
    #   1       4       7      10      13
    #   2       5       8      11      14
    #   3       6       9      12      15
    #
    # Each set therefore contains 3 benches.
    # ---------------------------------------------------------

    slot_views = []

    for slot_key in sorted(slot_map.keys()):

        slot_data = slot_map[slot_key]

        room_views = []

        for room_number in sorted(
            slot_data["rooms"].keys(),
            key=lambda value: str(value),
        ):

            room_data = slot_data["rooms"][room_number]
            room = room_data["room"]

            # -------------------------------------------------
            # ALWAYS DISPLAY THE STANDARD 15-BENCH STRUCTURE
            # -------------------------------------------------

            highest_allocated_bench = max(
                room_data["benches"].keys(),
                default=0,
            )

            total_benches = max(
                15,
                room.benches,
                highest_allocated_bench,
            )

            bench_views = []

            for bench_number in range(1, total_benches + 1):

                seat_map = room_data["benches"].get(
                    bench_number,
                    {
                        1: None,
                        2: None,
                        3: None,
                    },
                )

                seats = []

                for seat_number in [1, 2, 3]:

                    seats.append(
                        {
                            "number": seat_number,
                            "allocation": seat_map.get(seat_number),
                        }
                    )

                bench_views.append(
                    {
                        "number": bench_number,
                        "seats": seats,
                    }
                )

                # -------------------------------------------------
            # BUILD CLASSROOM ROWS
            #
            # Three benches across each row.
            #
            # Row 1:  Bench 1   Bench 2   Bench 3
            # Row 2:  Bench 4   Bench 5   Bench 6
            # Row 3:  Bench 7   Bench 8   Bench 9
            # Row 4:  Bench 10  Bench 11  Bench 12
            # Row 5:  Bench 13  Bench 14  Bench 15
            #
            # Numbering runs LEFT -> RIGHT,
            # then TOP -> BOTTOM.
            # -------------------------------------------------

            rows = []

            for row_start in range(0, total_benches, 3):

                rows.append(
                    {
                        "benches": bench_views[row_start : row_start + 3],
                    }
                )

            room_views.append(
                {
                    "room": room,
                    "capacity": room.capacity,
                    "benches": total_benches,
                    "rows": rows,
                    "students": sum(
                        1
                        for bench in bench_views
                        for seat in bench["seats"]
                        if seat["allocation"] is not None
                    ),
                }
            )

        slot_views.append(
            {
                "date": slot_data["date"],
                "session": slot_data["session"],
                "rooms": room_views,
                "classrooms_used": len(room_views),
                "students": sum(room_view["students"] for room_view in room_views),
            }
        )

        # ---------------------------------------------------------
    # BUILD ONE FLAT CLASSROOM LIST
    #
    # The screen viewer will navigate through these classrooms
    # without changing pages.
    # ---------------------------------------------------------

    classroom_views = []

    for slot in slot_views:

        for room_view in slot["rooms"]:

            classroom_views.append(
                {
                    "date": slot["date"],
                    "session": slot["session"],
                    "room": room_view["room"],
                    "capacity": room_view["capacity"],
                    "benches": room_view["benches"],
                    "rows": room_view["rows"],
                    "students": room_view["students"],
                }
            )

    seating_arrangements_count = len(classroom_views)
    # ---------------------------------------------------------
    # PROGRESS INFORMATION
    # ---------------------------------------------------------

    registrations_count = ExamRegistration.objects.filter(
        exam__subject__session=session
    ).count()

    exams_count = Exam.objects.filter(subject__session=session).count()

    rooms_count = Room.objects.filter(session=session).count()

    students_allocated = len(allocations)

    return render(
        request,
        "exam_allocator/session_allocation_result.html",
        {
            "session": session,
            "allocations": allocations,
            "allocations_count": len(allocations),
            "slot_views": slot_views,
            "classroom_views": classroom_views,
            "registrations_count": registrations_count,
            "exams_count": exams_count,
            "rooms_count": rooms_count,
            "students_allocated": students_allocated,
            "seating_arrangements_count": seating_arrangements_count,
            "classroom_views": classroom_views,
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

    uploaded = request.FILES.get("file")
    file_kind = request.POST.get("file_kind", "").strip().upper()

    if not uploaded:
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
            "Unsupported file format.",
        )

        return redirect(
            "exam_allocator:session_detail",
            session_id=session.session_id,
        )

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

            if source_format != UploadedFile.SourceFormat.XLSX:
                raise ValueError(
                    "Student List currently supports Excel (.xlsx) files only."
                )

            result = parse_student_excel(record.file.path)

            stats = import_students(
                result,
                session,
            )

            message = (
                f"Student list imported successfully: "
                f"{stats['students_created']} students, "
                f"{stats['classes_created']} classes, "
                f"{stats['departments_created']} departments created."
            )

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

            message = (
                f"Classroom list imported successfully: "
                f"{stats['rooms_created']} rooms created."
            )

        # -----------------------------------------------------
        # Timetable
        # -----------------------------------------------------

        elif file_kind == UploadedFile.FileKind.TIMETABLE:

            if source_format != UploadedFile.SourceFormat.XLSX:
                raise ValueError(
                    "Exam Timetable currently supports Excel (.xlsx) files only."
                )

            result = parse_timetable_excel(record.file.path)

            stats = import_timetable(
                result,
                session,
            )

            message = (
                f"Timetable imported successfully: "
                f"{stats['subjects_created']} subjects, "
                f"{stats['exams_created']} exams, "
                f"{stats['targets_created']} targets created."
            )

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

        messages.success(
            request,
            message,
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
            f"Import failed: {exc}",
        )

    return redirect(
        "exam_allocator:session_detail",
        session_id=session.session_id,
    )
