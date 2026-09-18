from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import Allocation, Exam
from .services.allocation_workflow import (
    AllocationWorkflowError,
    run_allocation,
)


@ensure_csrf_cookie
def exam_list(request):
    exams = Exam.objects.select_related("subject").order_by(
        "exam_date", "session", "exam_id"
    )

    return render(
        request,
        "exam_allocator/exam_list.html",
        {
            "exams": exams,
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
            "subject_code": (result["exam"].subject.subject_code),
            "subject_name": (result["exam"].subject.subject_name),
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
