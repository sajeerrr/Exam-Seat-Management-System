import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any

from django.db import models, transaction
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
    Subject,
    ElectiveSubject,
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
            stream_cap = math.ceil(rb.capacity / 3) if rb.capacity else (rb.room.benches or 15)
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
        slot_blueprint.remaining_capacity = max(0, remaining_cap)
        slot_blueprint.department_scattering = dept_scattering
        slot_blueprint.room_utilization = room_utilization
        slot_blueprint.pattern_distribution = pattern_summary
        slot_blueprint.validation_errors = errors
        slot_blueprint.validation_warnings = warnings

        is_valid = len(errors) == 0
        return is_valid, errors, warnings, stats

    @classmethod
    def serialize_slot_rooms(cls, slot_blueprint: SlotBlueprint) -> List[Dict[str, Any]]:
        """
        Serialize all room blueprints and their stream assignments into structured dicts.
        Ensures subject names and class names are populated accurately.
        """
        session = slot_blueprint.session
        subject_map = dict(
            Subject.objects.filter(session=session).values_list("subject_code", "subject_name")
        )
        elective_map = dict(
            ElectiveSubject.objects.filter(group__session=session).values_list("subject_code", "subject_name")
        )

        rbs = (
            slot_blueprint.room_blueprints.all()
            .select_related("room")
            .prefetch_related("stream_assignments")
            .order_by("room_order")
        )

        rooms_list = []
        for rb in rbs:
            assignments_by_stream = {"A": [], "B": [], "C": []}
            stream_totals = {"A": 0, "B": 0, "C": 0}
            stream_cap = math.ceil(rb.capacity / 3) if rb.capacity else (rb.room.benches or 15)

            for sa in rb.stream_assignments.all():
                subj_name = (
                    sa.subject_name
                    or subject_map.get(sa.subject_code)
                    or elective_map.get(sa.subject_code)
                    or ""
                )
                assign_data = {
                    "assignment_id": sa.assignment_id,
                    "stream_name": sa.stream_name,
                    "department_code": sa.department_code,
                    "class_name": sa.class_name,
                    "subject_code": sa.subject_code,
                    "subject_name": subj_name,
                    "subject_category": sa.subject_category,
                    "student_count": sa.student_count,
                    "student_rolls": sa.student_rolls or [],
                    "order": sa.order,
                }
                assignments_by_stream[sa.stream_name].append(assign_data)
                stream_totals[sa.stream_name] += sa.student_count

            rooms_list.append({
                "room_blueprint_id": rb.room_blueprint_id,
                "room_id": rb.room.room_id,
                "room_number": rb.room.room_number,
                "room_order": rb.room_order,
                "pattern": rb.pattern,
                "capacity": rb.capacity,
                "stream_limit": stream_cap,
                "total_students": rb.total_students,
                "unused_capacity": rb.unused_capacity,
                "department_count": rb.department_count,
                "stream_a_count": stream_totals["A"],
                "stream_b_count": stream_totals["B"],
                "stream_c_count": stream_totals["C"],
                "stream_a": assignments_by_stream["A"],
                "stream_b": assignments_by_stream["B"],
                "stream_c": assignments_by_stream["C"],
            })

        return rooms_list

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
        Consolidates groups if an identical department/class/subject assignment exists in the target stream.
        Recalculates exact student counts from database registrations.
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
            old_room_bp = assignment.room_blueprint
            target_room = Room.objects.get(room_id=target_room_id, session=slot_blueprint.session)
            
            target_room_bp, _ = RoomBlueprint.objects.get_or_create(
                slot_blueprint=slot_blueprint,
                room=target_room,
                defaults={
                    "capacity": target_room.capacity,
                    "room_order": slot_blueprint.room_blueprints.count() + 1,
                },
            )

            # Check if moving to exact same room and stream
            if old_room_bp.pk == target_room_bp.pk and assignment.stream_name == target_stream:
                is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
                return {
                    "success": True,
                    "rejected": False,
                    "errors": errors,
                    "warnings": warnings,
                    "stats": stats,
                    "blueprint_status": slot_blueprint.status,
                    "rooms": cls.serialize_slot_rooms(slot_blueprint),
                }

            # Check for existing compatible group in destination stream for consolidation
            matching_assignment = (
                target_room_bp.stream_assignments
                .filter(
                    stream_name=target_stream,
                    department_code=assignment.department_code,
                    class_name=assignment.class_name,
                    subject_code=assignment.subject_code,
                    subject_category=assignment.subject_category,
                )
                .exclude(assignment_id=assignment.assignment_id)
                .first()
            )

            if matching_assignment:
                # Merge student rolls maintaining uniqueness and order
                seen = set()
                merged_rolls = []
                for r in (matching_assignment.student_rolls or []) + (assignment.student_rolls or []):
                    r_str = str(r).strip()
                    if r_str and r_str not in seen:
                        seen.add(r_str)
                        merged_rolls.append(r_str)

                matching_assignment.student_rolls = merged_rolls
                matching_assignment.student_count = len(merged_rolls)
                if not matching_assignment.subject_name and assignment.subject_name:
                    matching_assignment.subject_name = assignment.subject_name
                matching_assignment.save()

                # Source assignment is consolidated; delete it
                assignment.delete()
            else:
                # Move assignment to target
                assignment.room_blueprint = target_room_bp
                assignment.stream_name = target_stream
                assignment.student_count = len(assignment.student_rolls or [])
                max_order = (
                    target_room_bp.stream_assignments
                    .filter(stream_name=target_stream)
                    .aggregate(models.Max("order"))["order__max"] or 0
                )
                assignment.order = max_order + 1
                assignment.save()

            # Invalidate any previously generated physical seating for this slot
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            # Recalculate room blueprint metrics
            cls._recalculate_room_blueprint(old_room_bp)
            if old_room_bp.pk != target_room_bp.pk:
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
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def swap_blueprint_assignments(
        cls,
        slot_blueprint: SlotBlueprint,
        assignment_id_1: int,
        assignment_id_2: int,
        reject_invalid: bool = True,
    ) -> Dict[str, Any]:
        """
        Swap two stream assignments between rooms/streams.
        Runs validation and rolls back if hard constraints are violated.
        """
        if assignment_id_1 == assignment_id_2:
            return {
                "success": True,
                "rejected": False,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

        with transaction.atomic():
            sid = transaction.savepoint()

            a1 = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id_1,
                room_blueprint__slot_blueprint=slot_blueprint,
            )
            a2 = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id_2,
                room_blueprint__slot_blueprint=slot_blueprint,
            )

            r1, s1 = a1.room_blueprint, a1.stream_name
            r2, s2 = a2.room_blueprint, a2.stream_name

            a1.room_blueprint = r2
            a1.stream_name = s2
            a1.save()

            a2.room_blueprint = r1
            a2.stream_name = s1
            a2.save()

            # Invalidate generated seating
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            cls._recalculate_room_blueprint(r1)
            if r1.pk != r2.pk:
                cls._recalculate_room_blueprint(r2)

            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)

            if not is_valid and reject_invalid:
                transaction.savepoint_rollback(sid)
                return {
                    "success": False,
                    "rejected": True,
                    "errors": errors,
                    "warnings": warnings,
                    "message": "Proposed swap violated hard constraints and was rejected. Previous valid state preserved.",
                }

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
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def update_room_capacity(
        cls,
        slot_blueprint: SlotBlueprint,
        room_id: int,
        new_capacity: int,
    ) -> Dict[str, Any]:
        """
        Dynamically update configured capacity for a room in this blueprint.
        Recalculates stream and room limits, total/unused capacity, and validation status immediately.
        If capacity is reduced below current allocation, marks room invalid (NEEDS_REVIEW)
        and blocks finalization without automatically truncating students.
        Invalidates generated physical seats.
        """
        new_capacity = int(new_capacity)
        if new_capacity < 1:
            raise BlueprintServiceError("Capacity must be at least 1.")

        with transaction.atomic():
            rb = RoomBlueprint.objects.select_for_update().get(
                slot_blueprint=slot_blueprint,
                room__room_id=room_id,
            )
            rb.capacity = new_capacity
            rb.unused_capacity = max(0, rb.capacity - rb.total_students)
            rb.save()

            # Invalidate physical seats
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def add_student_to_assignment(
        cls,
        slot_blueprint: SlotBlueprint,
        assignment_id: int,
        roll_number: str,
        allow_capacity_increase: bool = False,
    ) -> Dict[str, Any]:
        """
        Controlled workflow to add an individual student to a stream assignment.
        1. Checks eligibility: student registered for an exam in this slot.
        2. Verifies uniqueness: student is not already allocated in this slot blueprint.
        3. Verifies subject match: registered subject matches assignment subject.
        4. Verifies stream and room capacity (unless allow_capacity_increase is True).
        5. Appends student roll, increments count, invalidates physical seats, reruns validation.
        """
        roll_clean = str(roll_number).strip()
        if not roll_clean:
            raise BlueprintServiceError("Roll number cannot be empty.")

        with transaction.atomic():
            assignment = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id,
                room_blueprint__slot_blueprint=slot_blueprint,
            )
            room_bp = assignment.room_blueprint

            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            expected_students = []
            for ex in exams:
                expected_students.extend(get_engine_students(ex))

            target_student = None
            for s in expected_students:
                r = (getattr(s, "roll_no", None) or getattr(s, "register_no", "")).strip()
                if r.upper() == roll_clean.upper():
                    target_student = s
                    break

            if not target_student:
                raise BlueprintServiceError(
                    f"Student '{roll_clean}' is not registered or eligible for an exam in slot {slot_blueprint.exam_date} {slot_blueprint.shift}."
                )

            # Check subject match
            student_subj = getattr(target_student, "subject_code", "").strip().upper()
            assign_subj = assignment.subject_code.strip().upper()
            if student_subj != assign_subj:
                raise BlueprintServiceError(
                    f"Student {roll_clean} is taking subject '{student_subj}', which does not match assignment subject '{assign_subj}'."
                )

            # Check uniqueness across all rooms & streams in this slot blueprint
            all_assignments = StreamBlueprintAssignment.objects.filter(
                room_blueprint__slot_blueprint=slot_blueprint
            )
            for sa in all_assignments:
                existing_rolls = [str(r).strip().upper() for r in (sa.student_rolls or [])]
                if roll_clean.upper() in existing_rolls:
                    raise BlueprintServiceError(
                        f"Student {roll_clean} is already allocated in Room {sa.room_blueprint.room.room_number}, Stream {sa.stream_name}."
                    )

            # Check stream capacity
            stream_assignments = room_bp.stream_assignments.filter(stream_name=assignment.stream_name)
            current_stream_count = sum(sa.student_count for sa in stream_assignments)
            stream_cap = math.ceil(room_bp.capacity / 3) if room_bp.capacity else (room_bp.room.benches or 15)

            if current_stream_count + 1 > stream_cap:
                if allow_capacity_increase:
                    new_cap = (current_stream_count + 1) * 3
                    if new_cap > room_bp.capacity:
                        room_bp.capacity = new_cap
                        room_bp.save()
                else:
                    raise BlueprintServiceError(
                        f"Adding student would exceed Stream {assignment.stream_name} capacity ({current_stream_count + 1} > {stream_cap}). Enable capacity expansion to override."
                    )

            # Check room capacity
            if room_bp.total_students + 1 > room_bp.capacity:
                if allow_capacity_increase:
                    room_bp.capacity = room_bp.total_students + 1
                    room_bp.save()
                else:
                    raise BlueprintServiceError(
                        f"Adding student would exceed Room {room_bp.room.room_number} capacity ({room_bp.total_students + 1} > {room_bp.capacity}). Enable capacity expansion to override."
                    )

            rolls = list(assignment.student_rolls or [])
            rolls.append(roll_clean)
            assignment.student_rolls = rolls
            assignment.student_count = len(rolls)
            assignment.save()

            # Invalidate physical seats
            Allocation.objects.filter(exam__in=exams).delete()

            cls._recalculate_room_blueprint(room_bp)
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def remove_student_from_assignment(
        cls,
        slot_blueprint: SlotBlueprint,
        assignment_id: int,
        roll_number: str,
    ) -> Dict[str, Any]:
        """
        Remove an individual student from an assignment.
        The student becomes unallocated for the slot.
        """
        roll_clean = str(roll_number).strip()
        with transaction.atomic():
            assignment = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id,
                room_blueprint__slot_blueprint=slot_blueprint,
            )
            room_bp = assignment.room_blueprint

            rolls = [r for r in (assignment.student_rolls or []) if str(r).strip().upper() != roll_clean.upper()]
            if len(rolls) == len(assignment.student_rolls or []):
                raise BlueprintServiceError(f"Student {roll_clean} not found in this assignment.")

            if not rolls:
                assignment.delete()
            else:
                assignment.student_rolls = rolls
                assignment.student_count = len(rolls)
                assignment.save()

            # Invalidate physical seats
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            cls._recalculate_room_blueprint(room_bp)
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def remove_blueprint_assignment(
        cls,
        slot_blueprint: SlotBlueprint,
        assignment_id: int,
    ) -> Dict[str, Any]:
        """
        Remove an entire stream assignment from the room blueprint.
        Its students become unallocated.
        """
        with transaction.atomic():
            assignment = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id,
                room_blueprint__slot_blueprint=slot_blueprint,
            )
            room_bp = assignment.room_blueprint
            assignment.delete()

            # Invalidate physical seats
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            cls._recalculate_room_blueprint(room_bp)
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def edit_blueprint_assignment(
        cls,
        slot_blueprint: SlotBlueprint,
        assignment_id: int,
        department_code: Optional[str] = None,
        class_name: Optional[str] = None,
        subject_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Directly update metadata for a stream assignment.
        """
        with transaction.atomic():
            assignment = StreamBlueprintAssignment.objects.select_for_update().get(
                assignment_id=assignment_id,
                room_blueprint__slot_blueprint=slot_blueprint,
            )
            if department_code is not None:
                assignment.department_code = department_code.strip()
            if class_name is not None:
                assignment.class_name = class_name.strip()
            if subject_code is not None:
                assignment.subject_code = subject_code.strip()
            assignment.save()

            # Invalidate physical seats
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            cls._recalculate_room_blueprint(assignment.room_blueprint)
            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def add_room_to_blueprint(
        cls,
        slot_blueprint: SlotBlueprint,
        room_id: int,
    ) -> Dict[str, Any]:
        """
        Add an available classroom from the session into this slot blueprint.
        """
        with transaction.atomic():
            room = Room.objects.get(room_id=room_id, session=slot_blueprint.session)
            if RoomBlueprint.objects.filter(slot_blueprint=slot_blueprint, room=room).exists():
                raise BlueprintServiceError(f"Room {room.room_number} is already in the blueprint.")

            next_order = (slot_blueprint.room_blueprints.aggregate(models.Max("room_order"))["room_order__max"] or 0) + 1
            RoomBlueprint.objects.create(
                slot_blueprint=slot_blueprint,
                room=room,
                capacity=room.capacity,
                room_order=next_order,
                pattern="EMPTY",
                unused_capacity=room.capacity,
            )

            # Invalidate physical seats
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def remove_room_from_blueprint(
        cls,
        slot_blueprint: SlotBlueprint,
        room_id: int,
    ) -> Dict[str, Any]:
        """
        Remove a classroom from this slot blueprint.
        Any assignments previously in that room are removed and their students become unallocated.
        """
        with transaction.atomic():
            room_bp = RoomBlueprint.objects.filter(
                slot_blueprint=slot_blueprint,
                room__room_id=room_id,
            ).first()
            if not room_bp:
                raise BlueprintServiceError("Room is not part of this blueprint.")

            room_bp.delete()

            # Invalidate physical seats
            exams = cls.get_slot_exams(
                slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
            )
            Allocation.objects.filter(exam__in=exams).delete()

            is_valid, errors, warnings, stats = cls.validate_blueprint(slot_blueprint)
            slot_blueprint.status = (
                SlotBlueprint.Status.VALIDATED if is_valid else SlotBlueprint.Status.NEEDS_REVIEW
            )
            slot_blueprint.save()

            return {
                "success": True,
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "stats": stats,
                "blueprint_status": slot_blueprint.status,
                "rooms": cls.serialize_slot_rooms(slot_blueprint),
            }

    @classmethod
    def get_unallocated_students(cls, slot_blueprint: SlotBlueprint) -> List[Dict[str, Any]]:
        """
        Return all students registered for exams in this slot who are not currently allocated
        to any stream assignment in this slot blueprint.
        """
        exams = cls.get_slot_exams(
            slot_blueprint.session, slot_blueprint.exam_date, slot_blueprint.shift
        )
        expected_students = []
        for ex in exams:
            expected_students.extend(get_engine_students(ex))

        allocated_rolls = set()
        for sa in StreamBlueprintAssignment.objects.filter(
            room_blueprint__slot_blueprint=slot_blueprint
        ):
            for r in (sa.student_rolls or []):
                clean_r = str(r).strip().upper()
                if clean_r:
                    allocated_rolls.add(clean_r)

        unallocated = []
        for s in expected_students:
            roll = (getattr(s, "roll_no", None) or getattr(s, "register_no", "")).strip()
            if roll and roll.upper() not in allocated_rolls:
                unallocated.append({
                    "roll_number": roll,
                    "name": getattr(s, "name", ""),
                    "department": getattr(s, "department", ""),
                    "class_name": getattr(s, "class_name", ""),
                    "subject_code": getattr(s, "subject_code", ""),
                    "subject_name": getattr(s, "subject_name", ""),
                    "subject_category": getattr(s, "subject_category", "REGULAR"),
                })

        return sorted(unallocated, key=lambda x: (x["department"], x["class_name"], x["roll_number"]))

    @classmethod
    def _recalculate_room_blueprint(cls, room_bp: RoomBlueprint):
        """Recalculate total students, depts, unused capacity and pattern for a room."""
        if not room_bp.pk:
            return
        stream_depts = {"A": set(), "B": set(), "C": set()}
        total_students = 0

        for sa in room_bp.stream_assignments.all():
            correct_count = len(sa.student_rolls or [])
            if sa.student_count != correct_count:
                sa.student_count = correct_count
                sa.save(update_fields=["student_count"])
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
            classroom = django_room_to_engine_classroom(rb.room, capacity=rb.capacity)
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
        room_capacities = {rb.room.room_id: rb.capacity for rb in room_blueprints}
        with transaction.atomic():
            allocations = save_session_seat_plan(
                session=slot_blueprint.session,
                seat_plan=seat_plan,
                exams=exams,
                expected_students=len(slot_students),
                room_capacities=room_capacities,
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

