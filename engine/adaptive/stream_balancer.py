"""
Room Stream Balancer (Option A: Cohorts-Intact Stream Balancing).

Balances student counts across streams (A, B, C) within rooms.
Reduces large discrepancies (e.g. Stream B: 14 vs Stream C: 2) between streams by
moving entire intact department/subject cohorts to underfilled streams without splitting
any cohort, strictly ensuring zero capacity, department limit, or horizontal adjacency violations.
"""

import logging
from typing import List, Dict, Tuple, Optional, Any
from engine.context.allocation_context import AllocationContext
from engine.models.room_allocation import RoomAllocation, subject_conflict_key
from engine.validators.allocation_validator import AllocationValidator

logger = logging.getLogger(__name__)


class RoomStreamBalancer:
    """
    Intra-room stream balancer that minimizes stream count variance
    by moving intact cohorts between streams within a room.
    """

    def __init__(self):
        self.validator = AllocationValidator()

    def balance(self, context: AllocationContext) -> bool:
        """
        Balances streams for all active rooms in context.
        Returns True if any moves were executed.
        """
        changed = False
        for room in context.room_allocations:
            if room.used_capacity == 0:
                continue
            if self._balance_single_room(context, room):
                changed = True
        return changed

    def _balance_single_room(self, context: AllocationContext, room: RoomAllocation) -> bool:
        room_changed = False
        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            counts = {s: len(room.get_stream(s).students) for s in ["A", "B", "C"]}
            cur_diff = max(counts.values()) - min(counts.values())
            if cur_diff <= 1:
                break

            # Extract contiguous intact cohorts for each stream
            stream_chunks = {}
            for s_name in ["A", "B", "C"]:
                st = room.get_stream(s_name)
                chunks = []
                cur_chunk = []
                cur_key = None
                for stu in st.students:
                    k = (
                        getattr(stu, "department", ""),
                        getattr(stu, "normalized_subject_code", str(getattr(stu, "subject_code", "")).strip().upper()),
                    )
                    if k == cur_key or cur_key is None:
                        cur_chunk.append(stu)
                        cur_key = k
                    else:
                        chunks.append(cur_chunk)
                        cur_chunk = [stu]
                        cur_key = k
                if cur_chunk:
                    chunks.append(cur_chunk)
                stream_chunks[s_name] = chunks

            best_move = None
            best_reduction = 0.0

            mean_cnt = sum(counts.values()) / 3.0
            cur_var = sum((c - mean_cnt) ** 2 for c in counts.values())

            for from_s in ["A", "B", "C"]:
                if counts[from_s] <= min(counts.values()):
                    continue

                for c_idx, chunk in enumerate(stream_chunks[from_s]):
                    chunk_len = len(chunk)

                    for to_s in ["A", "B", "C"]:
                        if to_s == from_s:
                            continue
                        if counts[to_s] + chunk_len > room.get_stream(to_s).capacity:
                            continue

                        new_counts = dict(counts)
                        new_counts[from_s] -= chunk_len
                        new_counts[to_s] += chunk_len

                        new_var = sum((c - mean_cnt) ** 2 for c in new_counts.values())
                        if new_var >= cur_var - 1e-5:
                            continue

                        # Test applying the move in memory
                        st_from = room.get_stream(from_s)
                        st_to = room.get_stream(to_s)
                        orig_from = list(st_from.students)
                        orig_to = list(st_to.students)

                        new_from_students = []
                        for idx, ch in enumerate(stream_chunks[from_s]):
                            if idx != c_idx:
                                new_from_students.extend(ch)
                        st_from.students = new_from_students
                        st_to.students = orig_to + chunk

                        # Check that adjacent streams (A & B, B & C) never share departments
                        st_a_depts = set(room.get_stream("A").departments)
                        st_b_depts = set(room.get_stream("B").departments)
                        st_c_depts = set(room.get_stream("C").departments)
                        if not st_a_depts.isdisjoint(st_b_depts) or not st_b_depts.isdisjoint(st_c_depts):
                            st_from.students = orig_from
                            st_to.students = orig_to
                            continue

                        # Check that no two streams share any subject conflict key
                        st_a_subjs = {
                            subject_conflict_key(getattr(s, "subject_code", ""), getattr(s, "department", ""), getattr(s, "subject_name", ""))
                            for s in room.get_stream("A").students
                        }
                        st_b_subjs = {
                            subject_conflict_key(getattr(s, "subject_code", ""), getattr(s, "department", ""), getattr(s, "subject_name", ""))
                            for s in room.get_stream("B").students
                        }
                        st_c_subjs = {
                            subject_conflict_key(getattr(s, "subject_code", ""), getattr(s, "department", ""), getattr(s, "subject_name", ""))
                            for s in room.get_stream("C").students
                        }
                        if not st_a_subjs.isdisjoint(st_b_subjs) or not st_b_subjs.isdisjoint(st_c_subjs) or not st_a_subjs.isdisjoint(st_c_subjs):
                            st_from.students = orig_from
                            st_to.students = orig_to
                            continue

                        # Validate against full allocation constraints
                        v_res = self.validator.validate(context)
                        st_from.students = orig_from
                        st_to.students = orig_to

                        if v_res.success:
                            reduction = cur_var - new_var
                            if best_move is None or reduction > best_reduction:
                                best_reduction = reduction
                                best_move = (from_s, c_idx, to_s, chunk)

            if best_move:
                from_s, c_idx, to_s, chunk = best_move
                st_from = room.get_stream(from_s)
                st_to = room.get_stream(to_s)
                new_from_students = []
                for idx, ch in enumerate(stream_chunks[from_s]):
                    if idx != c_idx:
                        new_from_students.extend(ch)
                st_from.students = new_from_students
                st_to.students.extend(chunk)
                room_changed = True
            else:
                break

        return room_changed

