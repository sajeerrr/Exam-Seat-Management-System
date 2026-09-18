from engine.models.room_allocation import subject_conflict_key


class HeuristicSelector:
    """Chooses the next low-level allocation heuristic from current state."""

    ABC = "ABC"
    ABA = "ABA"
    SUBJECT_SPLIT = "SUBJECT_SPLIT"
    PACK_LEFTOVERS = "PACK_LEFTOVERS"

    def select(self, state, room_alloc, groups):
        if state.remaining_students == 0 or state.active_groups == 0:
            return None

        if 0 < room_alloc.used_capacity < room_alloc.classroom.capacity:
            return self.PACK_LEFTOVERS

        active_groups = [g for g in groups if g.remaining_count > 0]
        active_depts = {g.department for g in active_groups}

        if not active_groups:
            return None

        subject_totals = {}
        subject_group_counts = {}
        for group in active_groups:
            subject_key = subject_conflict_key(
                group.subject_code,
                group.department,
                group.subject_name,
            )
            subject_totals[subject_key] = (
                subject_totals.get(subject_key, 0)
                + group.remaining_count
            )
            subject_group_counts[subject_key] = (
                subject_group_counts.get(subject_key, 0)
                + 1
            )

        largest_subject = max(subject_totals, key=subject_totals.get)
        largest_subject_total = subject_totals[largest_subject]
        stream_capacity = room_alloc.stream_a.capacity
        has_buffer_subject = len(subject_totals) > 1
        if (
            subject_group_counts[largest_subject] > 1
            and has_buffer_subject
            and largest_subject_total >= stream_capacity * 2
        ):
            return self.SUBJECT_SPLIT

        largest_share = 0
        if state.remaining_students:
            largest_share = state.largest_group / state.remaining_students

        if (
            len(active_depts) <= 2
            or (
                largest_share >= 0.45
                and state.largest_group >= room_alloc.stream_a.capacity + 5
            )
        ):
            return self.ABA

        if state.average_group_size <= room_alloc.stream_a.capacity // 2:
            return self.PACK_LEFTOVERS

        return self.ABC

    def fallbacks(self, chosen):
        order = [
            self.SUBJECT_SPLIT,
            self.ABC,
            self.ABA,
            self.PACK_LEFTOVERS,
        ]
        if chosen in order:
            order.remove(chosen)
            return [chosen] + order
        return order
