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
    path("session/<int:session_id>/blueprint/", views.blueprint_review, name="blueprint_review"),
    path("session/<int:session_id>/allocations/", views.session_allocation_result, name="session_allocation_result"),
    path("session/<int:session_id>/allocate/", views.generate_session_allocation, name="generate_session_allocation"),
    path("exam/<int:exam_id>/generate/", views.generate_allocation, name="generate_allocation"),
    path("exam/<int:exam_id>/allocations/", views.allocation_list, name="allocation_list"),

    # ── Blueprint API ─────────────────────────────────────────────────────
    path("api/session/<int:session_id>/blueprint/allocate/", views.api_blueprint_allocate, name="api_blueprint_allocate"),
    path("api/session/<int:session_id>/blueprint/validate/", views.api_blueprint_validate, name="api_blueprint_validate"),
    path("api/session/<int:session_id>/blueprint/move/", views.api_blueprint_move, name="api_blueprint_move"),
    path("api/session/<int:session_id>/blueprint/swap/", views.api_blueprint_swap, name="api_blueprint_swap"),
    path("api/session/<int:session_id>/blueprint/room-capacity/", views.api_blueprint_room_capacity, name="api_blueprint_room_capacity"),
    path("api/session/<int:session_id>/blueprint/student/add/", views.api_blueprint_student_add, name="api_blueprint_student_add"),
    path("api/session/<int:session_id>/blueprint/student/remove/", views.api_blueprint_student_remove, name="api_blueprint_student_remove"),
    path("api/session/<int:session_id>/blueprint/assignment/remove/", views.api_blueprint_assignment_remove, name="api_blueprint_assignment_remove"),
    path("api/session/<int:session_id>/blueprint/assignment/edit/", views.api_blueprint_assignment_edit, name="api_blueprint_assignment_edit"),
    path("api/session/<int:session_id>/blueprint/split/", views.api_blueprint_split, name="api_blueprint_split"),
    path("api/session/<int:session_id>/blueprint/room/add/", views.api_blueprint_room_add, name="api_blueprint_room_add"),
    path("api/session/<int:session_id>/blueprint/dummy-room/add/", views.api_blueprint_dummy_room_add, name="api_blueprint_dummy_room_add"),
    path("api/session/<int:session_id>/blueprint/room/remove/", views.api_blueprint_room_remove, name="api_blueprint_room_remove"),
    path("api/session/<int:session_id>/blueprint/assign-room-name/", views.api_blueprint_assign_room_name, name="api_blueprint_assign_room_name"),
    path("api/session/<int:session_id>/blueprint/unallocated-students/", views.api_blueprint_unallocated_students, name="api_blueprint_unallocated_students"),
    path("api/session/<int:session_id>/blueprint/allocate-unallocated/", views.api_blueprint_allocate_unallocated, name="api_blueprint_allocate_unallocated"),
    path("api/session/<int:session_id>/blueprint/finalize/", views.api_blueprint_finalize, name="api_blueprint_finalize"),
    path("api/session/<int:session_id>/blueprint/unfinalize/", views.api_blueprint_unfinalize, name="api_blueprint_unfinalize"),
    path("api/session/<int:session_id>/blueprint/generate-seats/", views.api_blueprint_generate_seats, name="api_blueprint_generate_seats"),
    path("api/session/<int:session_id>/blueprint/reset/", views.api_blueprint_reset, name="api_blueprint_reset"),


    # ── Data API ──────────────────────────────────────────────────────────
    path("api/class/<int:class_id>/students/", views.api_class_students, name="api_class_students"),
    path("api/student/<int:student_id>/edit/", views.api_edit_student, name="api_edit_student"),
    path("api/student/<int:student_id>/delete/", views.api_delete_student, name="api_delete_student"),
    path("api/class/<int:class_id>/add-student/", views.api_add_class_student, name="api_add_class_student"),
    path("api/class/<int:class_id>/delete/", views.api_delete_class, name="api_delete_class"),

    path("api/session/<int:session_id>/rooms/add/", views.api_add_room, name="api_add_room"),
    path("api/room/<int:room_id>/edit/", views.api_edit_room, name="api_edit_room"),
    path("api/room/<int:room_id>/delete/", views.api_delete_room, name="api_delete_room"),

    path("api/exam/<int:exam_id>/target-students/", views.api_exam_target_students, name="api_exam_target_students"),
    path("api/exam/<int:exam_id>/edit/", views.api_edit_exam, name="api_edit_exam"),
    path("api/exam/<int:exam_id>/delete/", views.api_delete_exam, name="api_delete_exam"),
    path("api/session/<int:session_id>/exams/add/", views.api_add_exam, name="api_add_exam"),

    path("api/session/<int:session_id>/clear-electives/", views.api_clear_electives, name="api_clear_electives"),
    path("api/session/<int:session_id>/clear-timetable/", views.api_clear_timetable, name="api_clear_timetable"),
    path("api/session/<int:session_id>/clear-students/", views.api_clear_students, name="api_clear_students"),
    path("api/session/<int:session_id>/clear-rooms/", views.api_clear_rooms, name="api_clear_rooms"),
    path("api/uploaded-file/<int:file_id>/delete/", views.api_delete_uploaded_file, name="api_delete_uploaded_file"),

    path("api/elective-group/<int:group_id>/delete/", views.api_delete_elective_group, name="api_delete_elective_group"),
    path("api/elective-subject/<int:subject_id>/edit/", views.api_edit_elective_subject, name="api_edit_elective_subject"),
    path("api/elective-subject/<int:subject_id>/delete/", views.api_delete_elective_subject, name="api_delete_elective_subject"),
    path("api/elective-subject/<int:subject_id>/add-student/", views.api_add_elective_student, name="api_add_elective_student"),
    path("api/elective-registration/<int:registration_id>/edit/", views.api_edit_elective_registration, name="api_edit_elective_registration"),
    path("api/elective-registration/<int:registration_id>/delete/", views.api_delete_elective_registration, name="api_delete_elective_registration"),
]
