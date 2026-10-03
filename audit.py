import sys
sys.path.append('D:/Projects/S3 project/Seat Manager')

from data.loader.classroom_loader import ClassroomLoader
from data.loader.student_loader import StudentLoader
from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.room_allocation import RoomAllocation
from engine.services.allocation_service import AllocationService

def compute_metrics(context):
    """Compute quality metrics for the given allocation context."""
    groups = context.groups
    room_allocations = context.room_allocations

    # Basic counts
    total_students_expected = sum(g.remaining_count + g.allocated_count for g in groups)
    total_students_allocated = sum(g.allocated_count for g in groups)

    # Room level metrics
    abc_count = 0
    aba_count = 0
    other_3_stream_count = 0
    two_stream_room_count = 0
    one_stream_room_count = 0
    total_capacity = 0
    used_capacity = 0
    fragmentation = 0
    tiny_fragment_count = 0
    smallest_fragment = float('inf')

    # For department spread
    dept_rooms = {}

    for room in room_allocations:
        cap = room.classroom.capacity
        used = room.used_capacity
        total_capacity += cap
        used_capacity += used

        # Count streams with students
        streams_with_students = []
        for stream_name in ['A', 'B', 'C']:
            stream = room.get_stream(stream_name)
            if len(stream.students) > 0:
                streams_with_students.append(stream_name)

        num_streams = len(streams_with_students)
        if num_streams == 3:
            # Check for ABC or ABA
            depts = []
            for stream_name in ['A', 'B', 'C']:
                stream = room.get_stream(stream_name)
                if len(stream.students) > 0:
                    # Get department of first student in stream (assuming homogeneous stream)
                    dept = stream.students[0].department if stream.students else None
                    depts.append(dept)

            if len(set(depts)) == 3:
                abc_count += 1
            elif depts[0] == depts[2] and depts[0] != depts[1]:
                aba_count += 1
            else:
                other_3_stream_count += 1
        elif num_streams == 2:
            two_stream_room_count += 1
        elif num_streams == 1:
            one_stream_room_count += 1

        # Utilization
        # Fragmentation: count of extra rooms per department
        for stream_name in ['A', 'B', 'C']:
            stream = room.get_stream(stream_name)
            if len(stream.students) > 0:
                dept = stream.students[0].department
                dept_rooms.setdefault(dept, 0)
                dept_rooms[dept] += 1

                # Fragment within stream
                if len(stream.students) > 0:
                    # Count contiguous fragments of same dept/subject
                    # We'll do a simple version: count changes in (dept, subject_code)
                    if len(stream.students) == 0:
                        frag_count = 0
                    else:
                        frag_count = 1
                        prev_key = (stream.students[0].department, stream.students[0].subject_code)
                        for student in stream.students[1:]:
                            key = (student.department, student.subject_code)
                            if key != prev_key:
                                frag_count += 1
                                prev_key = key
                            if len(stream.students) == 0:
                                break
                    if frag_count > 0:
                        # Each fragment beyond the first is extra
                        fragmentation += max(0, frag_count - 1)
                        # Track tiny fragments (<=5 students)
                        # We'll need to compute fragment sizes - for now approximate
                        # We'll leave this for now and compute separately below

    # Compute tiny fragments and smallest fragment more accurately
    # We'll iterate over each stream and find contiguous groups of same (dept, subject_code)
    tiny_fragment_count = 0
    smallest_fragment = float('inf')
    for room in room_allocations:
        for stream_name in ['A', 'B', 'C']:
            stream = room.get_stream(stream_name)
            if len(stream.students) == 0:
                continue
            i = 0
            while i < len(stream.students):
                j = i
                dept = stream.students[i].department
                subj = stream.students[i].subject_code
                while j < len(stream.students) and \
                      stream.students[j].department == dept and \
                      stream.students[j].subject_code == subj:
                    j += 1
                frag_size = j - i
                if frag_size <= 5:
                    tiny_fragment_count += 1
                if frag_size < smallest_fragment:
                    smallest_fragment = frag_size
                i = j

    # Department spread: number of rooms each department appears in
    dept_spread = {}
    for dept, count in dept_rooms.items():
        dept_spread[dept] = count

    # Capacity violations and subject conflicts - we can use the validator
    from engine.validators.allocation_validator import AllocationValidator
    validator = AllocationValidator()
    validation_result = validator.validate(context)
    capacity_violations = 0
    subject_conflicts = 0
    invalid_allocations = 0
    if not validation_result.success:
        # Count errors by type (simplistic)
        for error in validation_result.errors:
            if 'capacity' in error.lower():
                capacity_violations += 1
            elif 'subject' in error.lower() or 'conflict' in error.lower():
                subject_conflicts += 1
            else:
                invalid_allocations += 1

    # Overall objective - we can use the LNS engine's scoring function for comparison
    from engine.lns.lns_engine import LNSEngine
    lns_engine = LNSEngine()
    overall_objective = lns_engine._score_context(context)

    utilization = used_capacity / total_capacity if total_capacity > 0 else 0

    return {
        'students_allocated': total_students_allocated,
        'students_expected': total_students_expected,
        'abc_count': abc_count,
        'aba_count': aba_count,
        'other_3_stream_count': other_3_stream_count,
        'two_stream_room_count': two_stream_room_count,
        'one_stream_room_count': one_stream_room_count,
        'total_capacity': total_capacity,
        'used_capacity': used_capacity,
        'utilization': utilization,
        'unused_seats': total_capacity - used_capacity,
        'fragment_count': fragmentation,  # This is actually extra rooms per dept + extra fragments? We'll refine
        'tiny_fragment_count': tiny_fragment_count,
        'smallest_fragment': smallest_fragment if smallest_fragment != float('inf') else 0,
        'department_spread': dept_spread,
        'capacity_violations': capacity_violations,
        'subject_conflicts': subject_conflicts,
        'invalid_allocations': invalid_allocations,
        'overall_objective': overall_objective
    }

def main():
    # Load data for a specific session: 29-01-2026 FN
    classroom_file = "resources/Class.xlsx"
    student_file = "resources/Students.xlsx"
    timetable_file = "resources/Timetable.xlsx"

    classrooms = ClassroomLoader(classroom_file).load()
    all_students = StudentLoader(
        student_file=student_file,
        timetable_file=timetable_file,
    ).load()

    # Filter for 29-01-2026 FN
    selected_date = "29-01-2026"
    selected_session = "FN"
    filtered_students = [
        s for s in all_students
        if s.exam_date == selected_date and s.session == selected_session
    ]

    print(f"Loaded {len(filtered_students)} students for {selected_date} {selected_session}")

    # Build groups
    groups = GroupBuilder().build(filtered_students)
    print(f"Built {len(groups)} groups")

    # Prepare room allocations
    room_allocations = [RoomAllocation(classroom=room) for room in classrooms]

    # Create context
    context = AllocationContext(
        groups=groups,
        room_allocations=room_allocations,
        remaining_pool=None  # We'll let the service handle this
    )

    # Run allocation service
    service = AllocationService()
    ctx, seat_plan = service.execute(context)

    # Compute metrics
    metrics = compute_metrics(ctx)

    print("\n=== ALLOCATION METRICS ===")
    for key, value in metrics.items():
        if key not in ['department_spread']:
            print(f"{key}: {value}")

    print("\nDepartment Spread:")
    for dept, count in metrics['department_spread'].items():
        print(f"  {dept}: {count} rooms")

if __name__ == "__main__":
    main()