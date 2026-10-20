# tests/benchmark_allocators.py
"""
Benchmark comparison suite for exam seat allocation engines:
1. Baseline Greedy (ConstrainedBestFitAllocator)
2. ABC-First Consolidation Hybrid (ABCHybridAllocator)
3. Enhanced CP-SAT Solver (CPSolver)

Evaluates:
- ABC Room Count (Target: >= 18 / 24)
- ABA Room Count
- Mixed-Department Streams (Target: <= 6, ideal 0)
- Department Room Scatter (Average & Max rooms per department)
- Max Departments per Room (Target: <= 3, max 4)
- Underfilled Rooms (< 25 students)
- Total Students Allocated vs Remaining
- Validation Status (0 errors)
- Execution Runtime (seconds / milliseconds)
"""

import time
from typing import Dict, Any, List
from exam_allocator.models import AllocationSession, Room
from exam_allocator.services.blueprint_service import BlueprintService
from exam_allocator.services.engine_adapter import get_engine_students, django_room_to_engine_classroom
from engine.builders.group_builder import GroupBuilder
from engine.context.allocation_context import AllocationContext
from engine.models.remaining_pool import RemainingPool
from engine.models.room_allocation import RoomAllocation
from engine.validators.allocation_validator import AllocationValidator
from engine.allocators.constrained_best_fit_allocator import ConstrainedBestFitAllocator
from engine.allocators.abc_hybrid_allocator import ABCHybridAllocator
from engine.cp.cp_solver import CPSolver


def evaluate_allocation_quality(name: str, context: AllocationContext, runtime_seconds: float) -> Dict[str, Any]:
    val = AllocationValidator().validate(context)
    
    total_rooms = len(context.room_allocations)
    active_rooms = [r for r in context.room_allocations if r.used_capacity > 0]
    
    abc_rooms = 0
    aba_rooms = 0
    other_rooms = 0
    mixed_streams = 0
    pure_streams = 0
    underfilled_rooms = 0
    max_depts_in_any_room = 0
    dept_room_counts: Dict[str, set] = {}

    for r in active_rooms:
        depts = r.departments
        if len(depts) > max_depts_in_any_room:
            max_depts_in_any_room = len(depts)

        if len(depts) >= 3:
            abc_rooms += 1
        elif len(depts) == 2:
            aba_rooms += 1
        else:
            other_rooms += 1

        if r.used_capacity < 25:
            underfilled_rooms += 1

        for s_name, stream in r.streams.items():
            if len(stream.students) > 0:
                if len(stream.departments) > 1:
                    mixed_streams += 1
                else:
                    pure_streams += 1

        for d in depts:
            dept_room_counts.setdefault(d, set()).add(r.classroom.room_no)

    dept_scatter = {d: len(rooms) for d, rooms in dept_room_counts.items()}
    avg_scatter = (sum(dept_scatter.values()) / len(dept_scatter)) if dept_scatter else 0.0
    max_scatter = max(dept_scatter.values()) if dept_scatter else 0
    unallocated = sum(g.remaining_count for g in context.groups)
    total_allocated = sum(g.allocated_count for g in context.groups)

    return {
        "engine": name,
        "valid": val.success,
        "errors": len(val.errors),
        "total_allocated": total_allocated,
        "unallocated": unallocated,
        "active_rooms": len(active_rooms),
        "abc_rooms": abc_rooms,
        "aba_rooms": aba_rooms,
        "mixed_streams": mixed_streams,
        "pure_streams": pure_streams,
        "max_depts_per_room": max_depts_in_any_room,
        "underfilled_rooms": underfilled_rooms,
        "avg_dept_room_spread": round(avg_scatter, 1),
        "max_dept_room_spread": max_scatter,
        "me_room_spread": dept_scatter.get("ME", 0),
        "runtime_s": round(runtime_seconds, 3),
        "dept_scatter_details": dept_scatter,
    }


def run_benchmark(session_id: int, exam_date_str: str, shift: str):
    session = AllocationSession.objects.get(session_id=session_id)
    exams = BlueprintService.get_slot_exams(session, exam_date_str, shift)
    
    students = []
    for e in exams:
        students.extend(get_engine_students(e))
    
    rooms = list(Room.objects.filter(session=session).order_by("room_number"))
    
    print("=" * 80)
    print(f"BENCHMARK: Session {session_id} | Slot: {exam_date_str} {shift}")
    print(f"Cohort: {len(students)} students across {len(exams)} exams | Rooms: {len(rooms)} ({len(rooms)*45} capacity)")
    print("=" * 80)

    results = []

    # 1. Baseline Greedy (ConstrainedBestFitAllocator)
    groups1 = GroupBuilder().build(students)
    ra1 = [RoomAllocation(classroom=django_room_to_engine_classroom(r)) for r in rooms]
    ctx1 = AllocationContext(groups=groups1, room_allocations=ra1, remaining_pool=RemainingPool())
    t0 = time.time()
    res_ctx1 = ConstrainedBestFitAllocator().execute(ctx1, allow_unallocated=False)
    t1 = time.time()
    results.append(evaluate_allocation_quality("1. Baseline Greedy", res_ctx1, t1 - t0))

    # 2. Enhanced CP-SAT Solver
    groups2 = GroupBuilder().build(students)
    ra2 = [RoomAllocation(classroom=django_room_to_engine_classroom(r)) for r in rooms]
    t0 = time.time()
    res_ctx2 = CPSolver().solve(groups2, ra2)
    t1 = time.time()
    if res_ctx2:
        results.append(evaluate_allocation_quality("2. Enhanced CP-SAT", res_ctx2, t1 - t0))
    else:
        results.append({"engine": "2. Enhanced CP-SAT", "valid": False, "errors": 1, "runtime_s": round(t1 - t0, 3)})

    # 3. ABC-First Consolidation Hybrid
    groups3 = GroupBuilder().build(students)
    ra3 = [RoomAllocation(classroom=django_room_to_engine_classroom(r)) for r in rooms]
    ctx3 = AllocationContext(groups=groups3, room_allocations=ra3, remaining_pool=RemainingPool())
    t0 = time.time()
    res_ctx3 = ABCHybridAllocator().execute(ctx3, allow_unallocated=False)
    t1 = time.time()
    results.append(evaluate_allocation_quality("3. ABC Hybrid", res_ctx3, t1 - t0))

    # Print comparison table
    print("\nBENCHMARK RESULTS TABLE:")
    print("-" * 115)
    header = (
        f"{'Metric':<30} | {'1. Baseline Greedy':<22} | "
        f"{'2. Enhanced CP-SAT':<22} | {'3. ABC Hybrid':<22}"
    )
    print(header)
    print("-" * 115)

    metrics_to_show = [
        ("Validation Success", lambda r: f"{'PASS' if r.get('valid') else 'FAIL'} (err={r.get('errors',0)})"),
        ("Allocated / Total", lambda r: f"{r.get('total_allocated')}/{r.get('total_allocated',0)+r.get('unallocated',0)}"),
        ("ABC Rooms (>=3 depts)", lambda r: f"{r.get('abc_rooms',0)} / {r.get('active_rooms',0)}"),
        ("ABA Rooms (2 depts)", lambda r: f"{r.get('aba_rooms',0)}"),
        ("Mixed Streams (dept split)", lambda r: f"{r.get('mixed_streams',0)} / 72"),
        ("Pure Streams (1 dept)", lambda r: f"{r.get('pure_streams',0)} / 72"),
        ("Max Depts per Room", lambda r: f"{r.get('max_depts_per_room',0)}"),
        ("Underfilled Rooms (<25)", lambda r: f"{r.get('underfilled_rooms',0)}"),
        ("Avg Room Spread / Dept", lambda r: f"{r.get('avg_dept_room_spread',0)} rooms"),
        ("ME Room Spread (215 stu)", lambda r: f"{r.get('me_room_spread',0)} rooms"),
        ("Runtime", lambda r: f"{r.get('runtime_s',0)} s"),
    ]

    for label, fn in metrics_to_show:
        col1 = fn(results[0])
        col2 = fn(results[1])
        col3 = fn(results[2])
        print(f"{label:<30} | {col1:<22} | {col2:<22} | {col3:<22}")
    print("-" * 115)

    return results

