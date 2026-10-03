from django.urls import path

from . import views

app_name = "exam_allocator"


urlpatterns = [
    # ── Session management ────────────────────────────────────────────────
    path("", views.session_list, name="session_list"),
    path("session/new/", views.create_session, name="create_session"),
    path("session/<int:session_id>/", views.session_detail, name="session_detail"),
    path("session/<int:session_id>/delete/", views.delete_session, name="delete_session"),

    # ── Import & Review ───────────────────────────────────────────────────
    path("session/<int:session_id>/import/", views.import_data, name="import_data"),
    path("session/<int:session_id>/review/", views.review_session, name="review_session"),
    path("session/<int:session_id>/upload/", views.upload_file, name="upload_file"),

    # ── Exams / Allocation ────────────────────────────────────────────────
    path("session/<int:session_id>/exams/", views.exam_list, name="session_exam_list"),
    path("session/<int:session_id>/registrations/generate/", views.generate_registrations, name="generate_registrations"),
    path("session/<int:session_id>/allocations/", views.session_allocation_result, name="session_allocation_result"),
    path("session/<int:session_id>/allocate/", views.generate_session_allocation, name="generate_session_allocation"),
    path("exam/<int:exam_id>/generate/", views.generate_allocation, name="generate_allocation"),
    path("exam/<int:exam_id>/allocations/", views.allocation_list, name="allocation_list"),

    # ── Data API ──────────────────────────────────────────────────────────
    path("api/class/<int:class_id>/students/", views.api_class_students, name="api_class_students"),
    path("api/student/<int:student_id>/edit/", views.api_edit_student, name="api_edit_student"),
    path("api/session/<int:session_id>/rooms/add/", views.api_add_room, name="api_add_room"),
    path("api/room/<int:room_id>/edit/", views.api_edit_room, name="api_edit_room"),
    path("api/room/<int:room_id>/delete/", views.api_delete_room, name="api_delete_room"),
    path("api/exam/<int:exam_id>/target-students/", views.api_exam_target_students, name="api_exam_target_students"),
]
