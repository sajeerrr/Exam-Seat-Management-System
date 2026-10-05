from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
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
    ElectiveGroup,
    ElectiveSubject,
    ElectiveStudentRegistration,
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
from .parsers.elective_parser import parse_elective_file

from .services.import_service import (
    import_students,
    import_classrooms,
    import_timetable,
)
from .services.elective_import_service import import_elective_data
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
            from exam_allocator.services.registration_service import create_exam_registrations
            for ex in exams_in_slot:
                create_exam_registrations(ex)
            total_regs = ExamRegistration.objects.filter(exam__in=exams_in_slot).count()

        if total_regs == 0:
            missing_data_reason = "No students are currently registered for the exams during this specific slot. This typically happens because the student list Excel files for the matching classes (like Semester 8) were not uploaded in the Import Data step!"
        else:
            # If registrations exist but allocations do not yet exist for this slot, run allocation on the fly
            existing_allocs = Allocation.objects.filter(
                exam__subject__session=session,
                exam__exam_date=selected_slot['date'],
                exam__session=selected_slot['shift']
            ).count()
            if existing_allocs == 0:
                try:
                    from exam_allocator.services.session_allocation_service import (
                        _get_session_rooms, _allocate_slot, save_session_seat_plan
                    )
                    from exam_allocator.services.engine_adapter import get_engine_students
                    slot_students = []
                    for ex in exams_in_slot:
                        slot_students.extend(get_engine_students(ex))
                    rooms = _get_session_rooms(session)
                    slot_tuple = (selected_slot['date'], selected_slot['shift'])
                    seat_plan = _allocate_slot(session, slot_tuple, slot_students, rooms)
                    if seat_plan:
                        save_session_seat_plan(session, seat_plan, list(exams_in_slot))
                except Exception as exc:
                    pass

        # Pre-cache elective registrations for fast in-memory resolution
        from exam_allocator.models import ElectiveStudentRegistration
        from exam_allocator.services.engine_adapter import _is_matching_elective_exam
        from collections import defaultdict

        elec_regs = ElectiveStudentRegistration.objects.filter(
            elective_subject__group__session=session
        ).select_related('elective_subject', 'elective_subject__group')
        elec_map = defaultdict(list)
        for r in elec_regs:
            elec_map[r.student_id].append(r)

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
                "exam",
                "exam__subject",
                "room",
            )
            .order_by("room__room_number", "bench_number", "seat_number")
        )

        all_slot_students = []
        room_allocs = defaultdict(list)

        for a in allocations:
            st = a.registration.student
            ex = a.exam
            dept_code = st.student_class.department.department_code if (st.student_class and st.student_class.department) else "GEN"
            class_name = st.student_class.class_name if st.student_class else ""
            subj_code = ex.subject.subject_code
            subj_name = ex.subject.subject_name
            cat = "NORMAL"

            st_elecs = elec_map.get(st.student_id, [])
            for r in st_elecs:
                if _is_matching_elective_exam(ex, r.elective_subject):
                    subj_code = r.elective_subject.subject_code
                    subj_name = r.elective_subject.subject_name
                    cat = r.elective_subject.elective_type or "ELECTIVE"
                    break

            is_special = cat in ("ELECTIVE", "MINOR", "HONOURS") or any(
                kw in ex.subject.subject_name.upper()
                for kw in ("ELECTIVE", "MINOR", "HONOURS", "HONS")
            )
            # Label for stream summary:
            # For Elective / Minor / Honours: ALWAYS display the actual subject code
            # For normal exams: display department code
            summary_label = subj_code if is_special else dept_code

            stream_letter = chr(64 + a.seat_number) if 1 <= a.seat_number <= 3 else str(a.seat_number)
            record = {
                'allocation_id': a.allocation_id,
                'room_number': a.room.room_number,
                'bench_number': a.bench_number,
                'seat_number': a.seat_number,
                'stream_letter': stream_letter,
                'stream_name': f"Stream {stream_letter} (Seat {a.seat_number})",
                'roll_number': st.roll_number,
                'student_name': st.student_name,
                'department': dept_code,
                'class_name': class_name,
                'subject_code': subj_code,
                'subject_name': subj_name,
                'category': cat,
                'is_special': is_special,
                'summary_label': summary_label,
                'exam_date': selected_slot['date'],
                'session': selected_slot['shift'],
            }
            room_allocs[a.room].append(record)
            all_slot_students.append(record)

        def get_stream_summary(records, seat_num):
            seat_records = [r for r in records if r['seat_number'] == seat_num]
            if not seat_records:
                return "None"

            seat_records.sort(key=lambda x: x['bench_number'])
            summary = []

            current_label = seat_records[0]['summary_label']
            start_bench = seat_records[0]['bench_number']
            prev_bench = start_bench

            for r in seat_records[1:]:
                lbl = r['summary_label']
                current_num = r['bench_number']

                if lbl != current_label or current_num != prev_bench + 1:
                    if start_bench == prev_bench:
                        summary.append(f"{start_bench} {current_label}")
                    else:
                        summary.append(f"{start_bench}-{prev_bench} {current_label}")
                    current_label = lbl
                    start_bench = current_num
                prev_bench = current_num

            if start_bench == prev_bench:
                summary.append(f"{start_bench} {current_label}")
            else:
                summary.append(f"{start_bench}-{prev_bench} {current_label}")

            return ", ".join(summary)

        for room, records in room_allocs.items():
            records.sort(key=lambda x: (x['bench_number'], x['seat_number']))

            # Group into 3-seat benches for realistic classroom seating layout
            bench_map = defaultdict(dict)
            for r in records:
                bench_map[r['bench_number']][r['seat_number']] = r

            max_bench = max((r['bench_number'] for r in records), default=0)
            benches = []
            for b_num in range(1, max_bench + 1):
                benches.append({
                    'bench_number': b_num,
                    'seat_1': bench_map[b_num].get(1),
                    'seat_2': bench_map[b_num].get(2),
                    'seat_3': bench_map[b_num].get(3),
                })

            # Divide benches into exactly 3 columns (Col 1: B1-B5, Col 2: B6-B10, Col 3: B11-B15)
            col1 = [b for b in benches if 1 <= b['bench_number'] <= 5]
            col2 = [b for b in benches if 6 <= b['bench_number'] <= 10]
            col3 = [b for b in benches if 11 <= b['bench_number'] <= 15]
            extra = [b for b in benches if b['bench_number'] > 15]
            if extra:
                col3.extend(extra)

            columns = []
            if col1:
                columns.append({'title': 'Column 1 (Benches 1–5)', 'benches': col1})
            if col2:
                columns.append({'title': 'Column 2 (Benches 6–10)', 'benches': col2})
            if col3:
                columns.append({'title': 'Column 3 (Benches 11–15)', 'benches': col3})

            dept_codes = sorted(list(set(r['department'] for r in records if r['department'])))
            class_names = sorted(list(set(r['class_name'] for r in records if r['class_name'])))

            rooms_data[room.room_number] = {
                'room_id': room.room_id,
                'room_number': room.room_number,
                'total_students': len(records),
                'total_benches': max_bench,
                'stream_a': get_stream_summary(records, 1),
                'stream_b': get_stream_summary(records, 2),
                'stream_c': get_stream_summary(records, 3),
                'exam_date': selected_slot['date'],
                'session': selected_slot['shift'],
                'departments': ", ".join(dept_codes),
                'classes': ", ".join(class_names),
                'classes_list': class_names,
                'benches': benches,
                'columns': columns,
                'students': records,
            }

    # sort rooms numerically
    def try_int(val):
        try:
            return (0, int(val))
        except ValueError:
            return (1, val)

    sorted_rooms = [rooms_data[k] for k in sorted(rooms_data.keys(), key=try_int)]

    all_slot_classes = sorted(list(set(r['class_name'] for r in all_slot_students if r['class_name'])))

    return render(
        request,
        "exam_allocator/session_allocation_result.html",
        {
            "session": session,
            "slots": slots,
            "selected_slot": selected_slot,
            "rooms": sorted_rooms,
            "all_classes": all_slot_classes if selected_slot else [],
            "total_slot_students": len(all_slot_students) if selected_slot else 0,
            "all_students": all_slot_students if selected_slot else [],
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
        UploadedFile.FileKind.ELECTIVE_LIST,
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

            if filename.endswith((".xlsx", ".xlsm", ".xls")):
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
                # Elective List
                # -----------------------------------------------------
                elif file_kind == UploadedFile.FileKind.ELECTIVE_LIST:
                    if source_format not in (UploadedFile.SourceFormat.XLSX, UploadedFile.SourceFormat.PDF):
                        raise ValueError(
                            "Elective Data supports Excel (.xlsx, .xls, .xlsm) and PDF files only."
                        )

                    result = parse_elective_file(record.file.path)
                    result.source_file = record.original_filename

                    total_extracted_students = sum(
                        len(subj.students) for g in result.groups for subj in g.subjects
                    )
                    if total_extracted_students == 0:
                        raise ValueError("No valid elective student records were extracted from the file.")

                    stats = import_elective_data(session, result)

                    if stats.get("students_count", 0) == 0:
                        raise ValueError("No valid elective records were saved to the database.")

                    warning_count = len(result.issues)
                    msg = (
                        f"File: {record.original_filename}\n"
                        f"Status: Success\n"
                        f"Departments: {stats.get('departments_count', 0)}\n"
                        f"Elective Groups: {stats.get('groups_count', 0)}\n"
                        f"Subjects: {stats.get('subjects_count', 0)}\n"
                        f"Students: {stats.get('students_count', 0)}\n"
                        f"Duplicates Skipped: {stats.get('duplicates_count', 0)}\n"
                        f"Unresolved: {stats.get('unresolved_count', 0)}\n"
                        f"Warnings: {warning_count}\n"
                        f"Errors: 0"
                    )
                    messages.success(request, msg)

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
                if file_kind == UploadedFile.FileKind.ELECTIVE_LIST:
                    messages.error(
                        request,
                        f"File: {record.original_filename}\nStatus: Failed\nErrors: 1\nDetails: {exc}",
                    )
                else:
                    messages.error(
                        request,
                        f"Import failed for {uploaded.name}: {exc}",
                    )
                error_occurred = True

        if file_kind != UploadedFile.FileKind.ELECTIVE_LIST and (not error_occurred or len(uploaded_files) > 1):
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

    # Elective Groups for session (prefetch subjects and student registrations)
    elective_groups_qs = (
        ElectiveGroup.objects.filter(session=session)
        .prefetch_related(
            Prefetch(
                "subjects",
                queryset=ElectiveSubject.objects.prefetch_related("student_registrations").order_by("subject_code"),
            )
        )
        .order_by("elective_label")
    )

    total_elective_subjects = 0
    total_elective_registrations = 0
    unique_elective_students = set()
    unresolved_registrations_count = 0
    all_elective_departments = set()
    elective_groups_list = []

    for eg in elective_groups_qs:
        group_students_count = 0
        enriched_subjects = []
        for subj in eg.subjects.all():
            regs = list(subj.student_registrations.all())
            reg_count = len(regs)
            group_students_count += reg_count
            total_elective_registrations += reg_count
            total_elective_subjects += 1

            subj_depts = set()
            for r in regs:
                unique_elective_students.add(r.roll_number)
                if r.is_unresolved:
                    unresolved_registrations_count += 1
                if r.department:
                    subj_depts.add(r.department)
                    all_elective_departments.add(r.department)

            enriched_subjects.append({
                "subject": subj,
                "registrations": regs,
                "reg_count": reg_count,
                "departments": sorted(list(subj_depts)),
            })

        elective_groups_list.append({
            "group": eg,
            "elective_label": eg.elective_label,
            "subjects": enriched_subjects,
            "total_students": group_students_count,
            "subjects_count": len(enriched_subjects),
        })

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
            "elective_groups_list": elective_groups_list,
            "elective_groups_count": len(elective_groups_list),
            "elective_subjects_count": total_elective_subjects,
            "elective_registrations_count": total_elective_registrations,
            "elective_unique_students_count": len(unique_elective_students),
            "elective_unresolved_count": unresolved_registrations_count,
            "elective_departments_count": len(all_elective_departments),
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


# ─────────────────────────────────────────────────────────────────────────────
# API: BULK CLEAR CATEGORIES (FULL ELECTIVES, TIMETABLE, STUDENTS, ROOMS)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_clear_electives(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    with transaction.atomic():
        ElectiveStudentRegistration.objects.filter(elective_subject__group__session=session).delete()
        ElectiveSubject.objects.filter(group__session=session).delete()
        ElectiveGroup.objects.filter(session=session).delete()
        UploadedFile.objects.filter(session=session, file_kind=UploadedFile.FileKind.ELECTIVE_LIST).delete()
    return JsonResponse({"success": True})


@require_POST
def api_clear_timetable(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    with transaction.atomic():
        exam_ids = list(Exam.objects.filter(subject__session=session).values_list("exam_id", flat=True))
        Allocation.objects.filter(exam_id__in=exam_ids).delete()
        ExamRegistration.objects.filter(exam_id__in=exam_ids).delete()
        ExamTarget.objects.filter(exam_id__in=exam_ids).delete()
        Exam.objects.filter(pk__in=exam_ids).delete()
        UploadedFile.objects.filter(session=session, file_kind=UploadedFile.FileKind.TIMETABLE).delete()
    return JsonResponse({"success": True})


@require_POST
def api_clear_students(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    with transaction.atomic():
        class_ids = list(Class.objects.filter(department__session=session).values_list("class_id", flat=True))
        student_ids = list(Student.objects.filter(student_class_id__in=class_ids).values_list("student_id", flat=True))
        Allocation.objects.filter(registration__student_id__in=student_ids).delete()
        ExamRegistration.objects.filter(student_id__in=student_ids).delete()
        Student.objects.filter(pk__in=student_ids).delete()
        Class.objects.filter(pk__in=class_ids).delete()
        Department.objects.filter(session=session).delete()
        UploadedFile.objects.filter(session=session, file_kind=UploadedFile.FileKind.STUDENT_LIST).delete()
    return JsonResponse({"success": True})


@require_POST
def api_clear_rooms(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    with transaction.atomic():
        room_ids = list(Room.objects.filter(session=session).values_list("room_id", flat=True))
        if Allocation.objects.filter(room_id__in=room_ids).exists():
            return JsonResponse({"success": False, "error": "Cannot delete rooms because seat allocations exist."}, status=400)
        Room.objects.filter(pk__in=room_ids).delete()
        UploadedFile.objects.filter(session=session, file_kind=UploadedFile.FileKind.CLASSROOM_LIST).delete()
    return JsonResponse({"success": True})


@require_POST
def api_delete_uploaded_file(request, file_id):
    record = get_object_or_404(UploadedFile, pk=file_id)
    session = record.session
    with transaction.atomic():
        if record.file_kind == UploadedFile.FileKind.ELECTIVE_LIST:
            ElectiveStudentRegistration.objects.filter(
                elective_subject__group__session=session,
                source_file=record.original_filename,
            ).delete()
            ElectiveSubject.objects.filter(
                group__session=session,
                student_registrations__isnull=True,
            ).delete()
            ElectiveGroup.objects.filter(
                session=session,
                subjects__isnull=True,
            ).delete()
        record.delete()
    return JsonResponse({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# API: ELECTIVE SUBJECT & REGISTRATION EDIT/DELETE
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_edit_elective_subject(request, subject_id):
    subject = get_object_or_404(ElectiveSubject, elective_subject_id=subject_id)
    body = json.loads(request.body)
    code = body.get("subject_code", "").strip()
    name = body.get("subject_name", "").strip()
    etype = body.get("elective_type", "").strip()
    if not code or not name:
        return JsonResponse({"success": False, "error": "Subject code and name are required."}, status=400)

    subject.subject_code = code
    subject.subject_name = name
    if etype:
        subject.elective_type = etype
        group, _ = ElectiveGroup.objects.get_or_create(
            session=subject.group.session,
            elective_label=etype,
            defaults={"department_code": "ELECTIVE", "department_name": "Electives"}
        )
        subject.group = group
    subject.save()
    return JsonResponse({
        "success": True,
        "subject_code": subject.subject_code,
        "subject_name": subject.subject_name,
        "elective_type": subject.elective_type,
    })


@require_POST
def api_delete_elective_subject(request, subject_id):
    subject = get_object_or_404(ElectiveSubject, elective_subject_id=subject_id)
    group = subject.group
    with transaction.atomic():
        subject.student_registrations.all().delete()
        subject.delete()
        if not group.subjects.exists():
            group.delete()
    return JsonResponse({"success": True})


@require_POST
def api_delete_elective_group(request, group_id):
    group = get_object_or_404(ElectiveGroup, group_id=group_id)
    with transaction.atomic():
        for subj in group.subjects.all():
            subj.student_registrations.all().delete()
            subj.delete()
        group.delete()
    return JsonResponse({"success": True})


@require_POST
def api_edit_elective_registration(request, registration_id):
    reg = get_object_or_404(ElectiveStudentRegistration, registration_id=registration_id)
    body = json.loads(request.body)
    roll = body.get("roll_number", "").strip()
    name = body.get("student_name", "").strip()
    dept = body.get("department", "").strip()
    cname = body.get("class_name", "").strip()
    if not roll or not name:
        return JsonResponse({"success": False, "error": "Roll number and name are required."}, status=400)

    if (
        ElectiveStudentRegistration.objects.filter(elective_subject=reg.elective_subject, roll_number__iexact=roll)
        .exclude(pk=registration_id)
        .exists()
    ):
        return JsonResponse({"success": False, "error": f"Student with roll '{roll}' is already in this subject."}, status=400)

    reg.roll_number = roll
    reg.student_name = name
    reg.department = dept
    reg.class_name = cname
    reg.save(update_fields=["roll_number", "student_name", "department", "class_name"])
    return JsonResponse({
        "success": True,
        "roll_number": reg.roll_number,
        "student_name": reg.student_name,
        "department": reg.department,
        "class_name": reg.class_name,
    })


@require_POST
def api_delete_elective_registration(request, registration_id):
    reg = get_object_or_404(ElectiveStudentRegistration, registration_id=registration_id)
    reg.delete()
    return JsonResponse({"success": True})


@require_POST
def api_add_elective_student(request, subject_id):
    subject = get_object_or_404(ElectiveSubject, elective_subject_id=subject_id)
    body = json.loads(request.body)
    roll = body.get("roll_number", "").strip()
    name = body.get("student_name", "").strip()
    dept = body.get("department", "").strip()
    cname = body.get("class_name", "").strip()
    if not roll or not name:
        return JsonResponse({"success": False, "error": "Roll number and name are required."}, status=400)

    if ElectiveStudentRegistration.objects.filter(elective_subject=subject, roll_number__iexact=roll).exists():
        return JsonResponse({"success": False, "error": f"Student with roll '{roll}' is already in this subject."}, status=400)

    reg = ElectiveStudentRegistration.objects.create(
        elective_subject=subject,
        roll_number=roll,
        student_name=name,
        department=dept,
        class_name=cname,
        source_file="Manual Entry",
    )
    return JsonResponse({
        "success": True,
        "registration_id": reg.registration_id,
        "roll_number": reg.roll_number,
        "student_name": reg.student_name,
        "department": reg.department,
        "class_name": reg.class_name,
    })


# ─────────────────────────────────────────────────────────────────────────────
# API: TIMETABLE EXAM EDIT, ADD & DELETE
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_edit_exam(request, exam_id):
    exam = get_object_or_404(Exam, exam_id=exam_id)
    body = json.loads(request.body)
    exam_date = body.get("exam_date", "").strip()
    sess = body.get("session", "").strip()
    slot = body.get("slot", "").strip()
    if not exam_date or not sess:
        return JsonResponse({"success": False, "error": "Exam date and session (FN/AN) are required."}, status=400)

    exam.exam_date = exam_date
    exam.session = sess
    exam.save(update_fields=["exam_date", "session"])
    if slot:
        target = exam.targets.first()
        if target:
            target.slot = slot
            target.save(update_fields=["slot"])
        else:
            ExamTarget.objects.create(exam=exam, branch_code="ALL", slot=slot)
    return JsonResponse({
        "success": True,
        "exam_date": str(exam.exam_date),
        "session": exam.session,
        "slot": slot,
    })


@require_POST
def api_delete_exam(request, exam_id):
    exam = get_object_or_404(Exam, exam_id=exam_id)
    with transaction.atomic():
        exam.allocations.all().delete()
        exam.registrations.all().delete()
        exam.targets.all().delete()
        exam.delete()
    return JsonResponse({"success": True})


@require_POST
def api_add_exam(request, session_id):
    session = get_object_or_404(AllocationSession, session_id=session_id)
    body = json.loads(request.body)
    sub_code = body.get("subject_code", "").strip()
    sub_name = body.get("subject_name", "").strip()
    exam_date = body.get("exam_date", "").strip()
    sess = body.get("session", "").strip()
    slot = body.get("slot", "").strip()
    branch = body.get("branch", "").strip()
    if not sub_code or not exam_date or not sess:
        return JsonResponse({"success": False, "error": "Subject code, date, and session are required."}, status=400)

    with transaction.atomic():
        subject, _ = Subject.objects.get_or_create(
            session=session,
            subject_code=sub_code,
            defaults={"subject_name": sub_name or sub_code, "semester": 8}
        )
        exam = Exam.objects.create(
            subject=subject,
            exam_date=exam_date,
            session=sess,
            duration=180,
        )
        if branch or slot:
            ExamTarget.objects.create(
                exam=exam,
                branch_code=branch or "ALL",
                slot=slot,
            )
    return JsonResponse({"success": True, "exam_id": exam.exam_id})


# ─────────────────────────────────────────────────────────────────────────────
# API: STUDENT DELETE & CLASS ADD-STUDENT / DELETE
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
def api_delete_student(request, student_id):
    student = get_object_or_404(Student, student_id=student_id)
    with transaction.atomic():
        Allocation.objects.filter(registration__student=student).delete()
        student.exam_registrations.all().delete()
        student.elective_registrations.all().delete()
        student.delete()
    return JsonResponse({"success": True})


@require_POST
def api_add_class_student(request, class_id):
    cls = get_object_or_404(Class, class_id=class_id)
    body = json.loads(request.body)
    roll = body.get("roll_number", "").strip()
    name = body.get("student_name", "").strip()
    adm = body.get("admission_no", "").strip()
    reg = body.get("uni_reg_no", "").strip()
    gender = body.get("gender", "").strip()
    if not roll or not name:
        return JsonResponse({"success": False, "error": "Roll number and name are required."}, status=400)

    if Student.objects.filter(student_class=cls, roll_number__iexact=roll).exists():
        return JsonResponse({"success": False, "error": f"Student with roll '{roll}' already exists in this class."}, status=400)

    student = Student.objects.create(
        student_class=cls,
        roll_number=roll,
        student_name=name,
        admission_no=adm,
        uni_reg_no=reg,
        gender=gender,
    )
    return JsonResponse({
        "success": True,
        "student_id": student.student_id,
        "roll_number": student.roll_number,
        "student_name": student.student_name,
        "admission_no": student.admission_no,
        "uni_reg_no": student.uni_reg_no,
        "gender": student.gender,
    })


@require_POST
def api_delete_class(request, class_id):
    cls = get_object_or_404(Class, class_id=class_id)
    with transaction.atomic():
        stud_ids = list(cls.students.values_list("student_id", flat=True))
        Allocation.objects.filter(registration__student_id__in=stud_ids).delete()
        ExamRegistration.objects.filter(student_id__in=stud_ids).delete()
        cls.students.all().delete()
        cls.delete()
    return JsonResponse({"success": True})

