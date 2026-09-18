from django.urls import path

from . import views

app_name = "exam_allocator"


urlpatterns = [
    path(
        "",
        views.session_list,
        name="session_list",
    ),
    path(
        "session/new/",
        views.create_session,
        name="create_session",
    ),
    path(
        "session/<int:session_id>/",
        views.session_detail,
        name="session_detail",
    ),
    path(
        "session/<int:session_id>/delete/",
        views.delete_session,
        name="delete_session",
    ),
    path(
        "session/<int:session_id>/exams/",
        views.exam_list,
        name="session_exam_list",
    ),
    path(
        "session/<int:session_id>/upload/",
        views.upload_file,
        name="upload_file",
    ),
    path(
        "session/<int:session_id>/registrations/generate/",
        views.generate_registrations,
        name="generate_registrations",
    ),
    path(
        "session/<int:session_id>/allocations/",
        views.session_allocation_result,
        name="session_allocation_result",
    ),
    path(
        "session/<int:session_id>/allocate/",
        views.generate_session_allocation,
        name="generate_session_allocation",
    ),
    path(
        "exam/<int:exam_id>/generate/",
        views.generate_allocation,
        name="generate_allocation",
    ),
    path(
        "exam/<int:exam_id>/allocations/",
        views.allocation_list,
        name="allocation_list",
    ),
]
