import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any

from django.db import transaction
from django.utils.dateparse import parse_date

from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
from engine.allocators.seat_generator import SeatGenerator
from engine.builders.group_builder import GroupBuilder
from engine.config import AllocationLimits
from engine.context.allocation_context import AllocationContext
from engine.models.classroom import Classroom as EngineClassroom
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation

from exam_allocator.models import (
    Allocation,
    AllocationSession,
    Exam,
    ExamRegistration,
    Room,
    RoomBlueprint,
    SlotBlueprint,
    StreamBlueprintAssignment,
)
from exam_allocator.services.engine_adapter import (
    django_room_to_engine_classroom,
    get_engine_students,
)
from exam_allocator.services.registration_service import create_exam_registrations
from exam_allocator.services.session_allocation_service import (
    SessionAllocationError,
    save_session_seat_plan,
)

logger = logging.getLogger(__name__)


class BlueprintServiceError(Exception):
    """Base exception for blueprint operations."""
    pass


class BlueprintValidationError(BlueprintServiceError):
    """Raised when blueprint validation fails."""
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


class BlueprintService:

    @classmethod
    def get_slot_exams(cls, session: AllocationSession, exam_date: Any, shift: str) -> List[Exam]:
        """Fetch all exams in a session for a specific date and shift."""
        if isinstance(exam_date, str):
            parsed_date = parse_date(exam_date)
            if parsed_date:
                exam_date = parsed_date
        return list(
            Exam.objects.filter(
                subject__session=session,
                exam_date=exam_date,
                session=shift,
            ).select_related("subject", "subject__session")
        )

    @classmethod
    def get_or_create_slot_blueprint(
        cls, session: AllocationSession, exam_date: Any, shift: str
    ) -> SlotBlueprint:
        if isinstance(exam_date, str):
            parsed_date = parse_date(exam_date)
            if parsed_date:
                exam_date = parsed_date

        blueprint, created = SlotBlueprint.objects.get_or_create(
            session=session,
            exam_date=exam_date,
            shift=shift,
            defaults={"status": SlotBlueprint.Status.DRAFT},
        )
        return blueprint

    @classmethod
    def allocate_departments_for_slot(
        cls,
        session: AllocationSession,
        exam_date: Any,
        shift: str,
        force_reallocate: bool = False,
    ) -> SlotBlueprint:
        """
        Stage A: Allocate departments and classes across rooms and streams (A, B, C)
        without generating physical seat assignments.
        """
        if isinstance(exam_date, str):
            parsed_date = parse_date(exam_date)
            if parsed_date:
                exam_date = parsed_date

        existing_bp = SlotBlueprint.objects.filter(
            session=session, exam_date=exam_date, shift=shift
        ).first()
        if (
            existing_bp
            and existing_bp.room_blueprints.exists()
            and existing_bp.status in (SlotBlueprint.Status.FINALIZED, SlotBlueprint.Status.SEATS_GENERATED)
            and not force_reallocate
        ):
            return existing_bp

        exams = cls.get_slot_exams(session, exam_date, shift)
        if not exams:
            raise BlueprintServiceError(
                f"No examinations found for {exam_date} {shift} in session {session.name}."
            )

        # Ensure registrations exist for all exams in this slot
        for ex in exams:

            if not ExamRegistration.objects.filter(exam=ex).exists():
                create_exam_registrations(ex)

        # Collect engine students
        engine_students = []
        for ex in exams:
            engine_students.extend(get_engine_students(ex))

        if not engine_students:
            raise BlueprintServiceError(
                f"No eligible students found for {exam_date} {shift}."
            )

        # Build allocation groups
        groups = GroupBuilder().build(engine_students)
        if not groups:
            raise BlueprintServiceError(
                f"Could not build allocation groups for {exam_date} {shift}."
            )

        rooms = list(Room.objects.filter(session=session).order_by("room_number"))
        if not rooms:
            raise BlueprintServiceError(
                f"No classrooms available in session {session.name}."
            )

        room_allocations = [
            RoomAllocation(classroom=django_room_to_engine_classroom(r))
            for r in rooms
        ]

        context = AllocationContext(
            groups=groups,
            room_allocations=room_allocations,
            remaining_pool=RemainingPool(),
        )

        # Execute ConstrainedBestFitAllocator (Stage A ONLY - no SeatGenerator)
        allocator = ConstrainedBestFitAllocator()
        from engine.adaptive.invariant import AbcInvariant
        capacity = context.room_allocations[0].classroom.column_capacity if context.room_allocations else 15
        context.abc_invariant = AbcInvariant(context, stream_capacity=capacity)
        context = allocator.execute(context)

        # Persist Blueprint transactionally
        with transaction.atomic():
            slot_blueprint = cls.get_or_create_slot_blueprint(session, exam_date, shift)
            
            # If reallocating, invalidate any existing physical allocations
            Allocation.objects.filter(exam__in=exams).delete()

            # Clean up old room blueprints and stream assignments for this slot
            slot_blueprint.room_blueprints.all().delete()

            room_lookup = {r.room_number: r for r in rooms}
            order_idx = 1

            for ra in context.room_allocations:
                total_in_room = sum(len(ra.streams[s].students) for s in ["A", "B", "C"])
                if total_in_room == 0:
                    continue

                r_obj = room_lookup.get(ra.classroom.room_no)
                if not r_obj:
                    continue

                # Analyze pattern and departments
                stream_depts = {
                    s: list(dict.fromkeys(getattr(stu, "department", "") for stu in ra.streams[s].students if getattr(stu, "department", "")))
                    for s in ["A", "B", "C"]
                }
                all_depts = sorted(list(set(d for depts in stream_depts.values() for d in depts)))
                
                # Check ABC vs ABA pattern
                main_a = stream_depts["A"][0] if stream_depts["A"] else ""
                main_b = stream_depts["B"][0] if stream_depts["B"] else ""
                main_c = stream_depts["C"][0] if stream_depts["C"] else ""

                if main_a and main_b and main_c and main_a != main_b and main_b != main_c and main_a != main_c:
                    pattern = "ABC"
                elif main_a and main_b and main_c and main_a == main_c and main_a != main_b:
                    pattern = "ABA"
                else:
                    pattern = "MIXED" if len(all_depts) >= 2 else (main_a or "SINGLE")

                room_bp = RoomBlueprint.objects.create(
                    slot_blueprint=slot_blueprint,
                    room=r_obj,
                    room_order=order_idx,
                    pattern=pattern,
                    capacity=r_obj.capacity,
                    total_students=total_in_room,
                    unused_capacity=max(0, r_obj.capacity - total_in_room),
                    department_count=len(all_depts),
                )
                order_idx += 1

                # Group students in each stream by contiguous (dept, class, subject)
                for stream_name in ["A", "B", "C"]:
                    students_in_stream = ra.streams[stream_name].students
                    if not students_in_stream:
                        continue

                    # Group into contiguous chunks
                    chunks = []
                    curr_chunk = None
                    for stu in students_in_stream:
                        roll = getattr(stu, "roll_no", None) or getattr(stu, "register_no", "")
                        d_code = getattr(stu, "department", "") or ""
                        c_name = getattr(stu, "class_name", "") or ""
                        s_code = getattr(stu, "subject_code", "") or ""
                        s_name = getattr(stu, "subject_name", "") or ""
                        cat = getattr(stu, "subject_category", "NORMAL") or "NORMAL"

                        key = (d_code, c_name, s_code, s_name, cat)
                        if curr_chunk and curr_chunk["key"] == key:
                            curr_chunk["rolls"].append(roll)
                        else:
                            curr_chunk = {
                                "key": key,
                                "dept": d_code,
                                "class": c_name,
                                "subj_code": s_code,
                                "subj_name": s_name,
                                "category": cat,
                                "rolls": [roll],
                            }
                            chunks.append(curr_chunk)

                    for assign_order, chk in enumerate(chunks, start=1):
                        StreamBlueprintAssignment.objects.create(
                            room_blueprint=room_bp,
                            stream_name=stream_name,
                            department_code=chk["dept"],
                            class_name=chk["class"],
                            subject_code=chk["subj_code"],
                            subject_name=chk["subj_name"],
                            subject_category=chk["category"],
                            student_count=len(chk["rolls"]),
                            student_rolls=chk["rolls"],
                            order=assign_order,
                        )

            # Auto-validate the newly generated blueprint
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            slot_blueprint.version = 1
            slot_blueprint.save()

        return slot_blueprint

    @classmethod
    def validate_blueprint(
        cls, slot_blueprint: SlotBlueprint
    ) -> Tuple[bool, List[str], List[str], Dict[str, Any]]:
        """
        Authoritative backend validation of a SlotBlueprint against hard constraints and objectives.
        Returns: (is_valid, errors, warnings, stats)
        """
        errors: List[str] = []
        warnings: List[str] = []

        exams = cls.get_slot_exams(
            slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
        )
        if not exams:
            errors.append(
                f"No exams found for slot {slot_blueprint.exam_date} {slot_blueprint.shift}."
            )

        # Expected eligible engine students
        expected_students = []
        for ex in exams:
            expected_students.extend(get_engine_students(ex))

        expected_rolls = {
            (getattr(s, "roll_no", None) or getattr(s, "register_no", "")).strip()
            for s in expected_students
            if (getattr(s, "roll_no", None) or getattr(s, "register_no", "")).strip()
        }

        # ── 1. Student Integrity ───────────────────────────────────────────
        all_allocated_rolls = []
        roll_assignment_map = defaultdict(list)

        room_blueprints = list(
            slot_blueprint.room_blueprints.all()
            .select_related("room")
            .prefetch_related("stream_assignments")
            .order_by("room_order")
        )

        for rb in room_blueprints:
            for sa in rb.stream_assignments.all():
                if sa.student_count != len(sa.student_rolls):
                    errors.append(
                        f"Room {rb.room.room_number} Stream {sa.stream_name} count mismatch: "
                        f"student_count={sa.student_count} != rolls len={len(sa.student_rolls)}."
                    )
                for roll in sa.student_rolls:
                    clean_roll = str(roll).strip()
                    all_allocated_rolls.append(clean_roll)
                    roll_assignment_map[clean_roll].append(
                        f"Room {rb.room.room_number} Stream {sa.stream_name}"
                    )

        # Check duplicates
        duplicate_rolls = [
            roll for roll, locs in roll_assignment_map.items() if len(locs) > 1
        ]
        if duplicate_rolls:
            for roll in duplicate_rolls[:5]:
                errors.append(
                    f"Student {roll} allocated multiple times: {', '.join(roll_assignment_map[roll])}."
                )
            if len(duplicate_rolls) > 5:
                errors.append(f"... and {len(duplicate_rolls) - 5} more duplicate students.")

        # Check omitted eligible students
        allocated_roll_set = set(all_allocated_rolls)
        missing_rolls = expected_rolls - allocated_roll_set
        if missing_rolls:
            missing_sample = list(missing_rolls)[:5]
            errors.append(
                f"Missing {len(missing_rolls)} eligible students: {', '.join(missing_sample)}"
                + (f" and {len(missing_rolls) - 5} others" if len(missing_rolls) > 5 else "")
                + "."
            )

        # Check ineligible students
        ineligible_rolls = allocated_roll_set - expected_rolls
        if ineligible_rolls:
            ineligible_sample = list(ineligible_rolls)[:5]
            errors.append(
                f"{len(ineligible_rolls)} ineligible students allocated: {', '.join(ineligible_sample)}."
            )

        # ── 2. Capacity and Room Integrity ──────────────────────────────────
        rooms_used = len(room_blueprints)
        total_room_cap = sum(rb.capacity for rb in room_blueprints)
        total_allocated = len(all_allocated_rolls)
        remaining_cap = total_room_cap - total_allocated

        # Track departments across rooms for department scattering
        dept_room_map = defaultdict(set)
        patterns_count = defaultdict(int)

        for rb in room_blueprints:
            patterns_count[rb.pattern] += 1
            stream_counts = defaultdict(int)
            stream_subjects = defaultdict(set)
            room_depts = set()

            for sa in rb.stream_assignments.all():
                stream_counts[sa.stream_name] += sa.student_count
                if sa.department_code:
                    room_depts.add(sa.department_code)
                    dept_room_map[sa.department_code].add(rb.room.room_number)
                if sa.subject_code:
                    stream_subjects[sa.stream_name].add(sa.subject_code.strip().upper())

            # Stream capacity check
            stream_cap = rb.room.benches or 15
            for s_name in ["A", "B", "C"]:
                if stream_counts[s_name] > stream_cap:
                    errors.append(
                        f"Stream {s_name} in Room {rb.room.room_number} exceeds bench capacity: "
                        f"{stream_counts[s_name]} > {stream_cap}."
                    )

            # Room capacity check
            total_room_students = sum(stream_counts.values())
            if total_room_students > rb.capacity:
                errors.append(
                    f"Room {rb.room.room_number} exceeds room capacity: "
                    f"{total_room_students} > {rb.capacity}."
                )

            # Department limit check (<= 4 departments per room)
            if len(room_depts) > AllocationLimits.MAX_DEPARTMENTS_PER_ROOM:
                errors.append(
                    f"Room {rb.room.room_number} contains {len(room_depts)} departments "
                    f"(limit is {AllocationLimits.MAX_DEPARTMENTS_PER_ROOM}): {', '.join(sorted(room_depts))}."
                )

            # ── 3. Special Subject Feasibility ──────────────────────────────
            # For special subjects (ELECTIVE, MINOR, HONOURS), adjacent streams with same subject code
            # would cause immediate horizontal adjacency conflicts on benches!
            overlap_ab = stream_subjects["A"].intersection(stream_subjects["B"])
            overlap_bc = stream_subjects["B"].intersection(stream_subjects["C"])
            if overlap_ab:
                errors.append(
                    f"Room {rb.room.room_number} has same subject code in adjacent Streams A and B: "
                    f"{', '.join(sorted(overlap_ab))}."
                )
            if overlap_bc:
                errors.append(
                    f"Room {rb.room.room_number} has same subject code in adjacent Streams B and C: "
                    f"{', '.join(sorted(overlap_bc))}."
                )

            # Check if ABA is used when ABC was possible
            if rb.pattern == "ABA" and len(room_depts) >= 3:
                warnings.append(
                    f"Room {rb.room.room_number} is configured as ABA despite having 3+ departments available."
                )

        # Department scattering metric: sum of (rooms_count - 1) for depts spanning multiple rooms
        dept_scattering = sum(max(0, len(rms) - 1) for rms in dept_room_map.values())
        if dept_scattering > 8:
            warnings.append(
                f"High department scattering detected ({dept_scattering} split instances across rooms)."
            )

        room_utilization = (
            round((total_allocated / total_room_cap) * 100, 1) if total_room_cap > 0 else 0.0
        )
        if room_utilization < 50.0 and rooms_used > 1:
            warnings.append(
                f"Low room utilization ({room_utilization}%). Consider consolidating into fewer classrooms."
            )

        pattern_summary = ", ".join(f"{k}: {v}" for k, v in sorted(patterns_count.items()))

        stats = {
            "total_eligible_students": len(expected_rolls),
            "total_allocated_students": total_allocated,
            "unallocated_count": len(missing_rolls),
            "duplicate_count": len(duplicate_rolls),
            "rooms_used": rooms_used,
            "total_room_capacity": total_room_cap,
            "remaining_capacity": remaining_cap,
            "department_scattering": dept_scattering,
            "room_utilization": room_utilization,
            "pattern_distribution": pattern_summary,
            "validation_errors_count": len(errors),
            "validation_warnings_count": len(warnings),
        }

        # Update blueprint fields
        slot_blueprint.total_eligible_students = len(expected_rolls)
        slot_blueprint.total_allocated_students = total_allocated
        slot_blueprint.unallocated_count = len(missing_rolls)
        slot_blueprint.duplicate_count = len(duplicate_rolls)
        slot_blueprint.rooms_used = rooms_used
        slot_blueprint.total_room_capacity = total_room_cap
        slot_blueprint.remaining_capacity = remaining_cap
        slot_blueprint.department_scattering = dept_scattering
        slot_blueprint.room_utilization = room_utilization
        slot_blueprint.pattern_distribution = pattern_summary
        slot_blueprint.validation_errors = errors
        slot_blueprint.validation_warnings = warnings

        is_valid = len(errors) == 0
        return is_valid, errors, warnings, stats

    @classmethod
    def modify_blueprint_assignment(
        cls,
        slot_blueprint: SlotBlueprint,
        assignment_id: int,
        target_room_id: int,
        target_stream: str,
        reject_invalid: bool = True,
    ) -> Dict[str, Any]:
        """
        Manually edit/move a stream assignment to another room or stream.
        Runs automatic backend validation immediately after the change.
        If reject_invalid is True and hard constraints fail, rolls back and preserves the last valid state.
        """
        if target_stream not in ("A", "B", "C"):
            raise BlueprintServiceError(f"Invalid target stream: {target_stream}")

        with transaction.atomic():
            sid = transaction.savepoint()

            assignment = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id,
                room_blueprint__slot_blueprint=slot_blueprint,
            )
            target_room = Room.objects.get(room_id=target_room_id, session=slot_blueprint.session)
            
            target_room_bp, _ = RoomBlueprint.objects.get_or_create(
                slot_blueprint=slot_blueprint,
                room=target_room,
                defaults={
                    "capacity": target_room.capacity,
                    "room_order": slot_blueprint.room_blueprints.count() + 1,
                },
            )

            # Move assignment
            old_room_bp = assignment.room_blueprint
            assignment.room_blueprint = target_room_bp
            assignment.stream_name = target_stream
            assignment.save()

            # Invalidate any previously generated physical seating for this slot
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            # Recalculate room blueprint metrics
            cls._recalculate_room_blueprint(old_room_bp)
            cls._recalculate_room_blueprint(target_room_bp)

            # Clean up empty room blueprints if any
            if old_room_bp.stream_assignments.count() == 0:
                old_room_bp.delete()

            # Run backend validation
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)

            if not is_valid and reject_invalid:
                transaction.savepoint_rollback(sid)
                return {
                    "success": False,
                    "rejected": True,
                    "errors": errors,
                    "warnings": warnings,
                    "message": "Proposed edit violated hard constraints and was rejected. Previous valid state preserved.",
                }

            # Update status
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()
            transaction.savepoint_commit(sid)

            return {
                "success": is_valid,
                "rejected": False,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
            }

    @classmethod
    def _recalculate_room_blueprint(cls, room_bp: RoomBlueprint):
        """Recalculate total students, depts, unused capacity and pattern for a room."""
        stream_depts = {"A": set(), "B": set(), "C": set()}
        total_students = 0

        for sa in room_bp.stream_assignments.all():
            total_students += sa.student_count
            if sa.department_code:
                stream_depts[sa.stream_name].add(sa.department_code)

        all_depts = set(d for depts in stream_depts.values() for d in depts)
        room_bp.total_students = total_students
        room_bp.unused_capacity = max(0, room_bp.capacity - total_students)
        room_bp.department_count = len(all_depts)

        # Pattern
        d_a = next(iter(stream_depts["A"])) if stream_depts["A"] else ""
        d_b = next(iter(stream_depts["B"])) if stream_depts["B"] else ""
        d_c = next(iter(stream_depts["C"])) if stream_depts["C"] else ""

        if d_a and d_b and d_c and d_a != d_b and d_b != d_c and d_a != d_c:
            room_bp.pattern = "ABC"
        elif d_a and d_b and d_c and d_a == d_c and d_a != d_b:
            room_bp.pattern = "ABA"
        else:
            room_bp.pattern = "MIXED" if len(all_depts) >= 2 else (d_a or "SINGLE")

        room_bp.save()

    @classmethod
    def finalize_blueprint(cls, slot_blueprint: SlotBlueprint) -> SlotBlueprint:
        """
        Stage C: Explicit blueprint finalization.
        Reruns authoritative backend validation against current database state.
        Blocks finalization if any hard constraint fails.
        """
        with transaction.atomic():
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            if not is_valid:
                raise BlueprintValidationError(
                    f"Blueprint finalization blocked by {len(errors)} error(s).",
                    errors=errors,
                )

            slot_blueprint.status = SlotBlueprint.Status.FINALIZED
            slot_blueprint.version += 1
            slot_blueprint.save()
            return slot_blueprint

    @classmethod
    def unfinalize_blueprint(cls, slot_blueprint: SlotBlueprint) -> SlotBlueprint:
        """
        Unfinalize a blueprint so the user can make modifications.
        Marks physical seating as outdated and deletes it.
        """
        with transaction.atomic():
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            slot_blueprint.status = SlotBlueprint.Status.NEEDS_REVIEW
            slot_blueprint.save()
            return slot_blueprint

    @classmethod
    def generate_seats_from_blueprint(
        cls, slot_blueprint: SlotBlueprint
    ) -> List[Allocation]:
        """
        Stage D: Generate physical seats using the finalized blueprint.
        Does NOT re-allocate departments or streams.
        Applies SeatGenerator and validates 8-neighborhood Moore adjacency for special subjects.
        """
        if slot_blueprint.status not in (
            SlotBlueprint.Status.FINALIZED,
            SlotBlueprint.Status.SEATS_GENERATED,
        ):
            raise BlueprintServiceError(
                f"Cannot generate seats: Blueprint must be FINALIZED first (current status: {slot_blueprint.status})."
            )


        exams = cls.get_slot_exams(
            slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
        )
        if not exams:
            raise BlueprintServiceError("No examinations found for this slot.")

        # Map eligible engine students by roll number
        slot_students = []
        for ex in exams:
            slot_students.extend(get_engine_students(ex))

        student_by_roll = {}
        for s in slot_students:
            roll = (getattr(s, "roll_no", None) or getattr(s, "register_no", "")).strip()
            if roll:
                student_by_roll[roll] = s

        # Reconstruct RoomAllocation objects strictly from finalized RoomBlueprint and StreamBlueprintAssignments
        room_blueprints = list(
            slot_blueprint.room_blueprints.all()
            .select_related("room")
            .prefetch_related("stream_assignments")
            .order_by("room_order")
        )

        room_allocations = []
        for rb in room_blueprints:
            classroom = django_room_to_engine_classroom(rb.room)
            ra = RoomAllocation(classroom=classroom)

            for stream_name in ["A", "B", "C"]:
                assignments = rb.stream_assignments.filter(stream_name=stream_name).order_by("order", "assignment_id")
                stream_students = []
                for sa in assignments:
                    for roll in sa.student_rolls:
                        clean_roll = str(roll).strip()
                        stu = student_by_roll.get(clean_roll)
                        if stu:
                            stream_students.append(stu)
                        else:
                            raise BlueprintServiceError(
                                f"Student roll {clean_roll} in finalized blueprint not found in eligible students."
                            )
                ra.streams[stream_name].students = stream_students

            room_allocations.append(ra)

        # Invoke SeatGenerator (strictly maps students to physical seats without reallocating)
        context = AllocationContext(
            groups=[],
            room_allocations=room_allocations,
            remaining_pool=RemainingPool(),
        )
        seat_generator = SeatGenerator()
        seat_plan = seat_generator.generate(context)

        # Validate physical seats & save transactionally
        with transaction.atomic():
            allocations = save_session_seat_plan(
                session=slot_blueprint.session,
                seat_plan=seat_plan,
                exams=exams,
                expected_students=len(slot_students),
            )
            slot_blueprint.status = SlotBlueprint.Status.SEATS_GENERATED
            slot_blueprint.save()

        return allocations

    @classmethod
    def reset_slot_blueprint(cls, slot_blueprint: SlotBlueprint) -> None:
        """
        Delete a slot's blueprint, room blueprints, stream assignments,
        and any physical seat allocations for this slot transactionally.
        """
        with transaction.atomic():
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()
            slot_blueprint.room_blueprints.all().delete()
            slot_blueprint.delete()

