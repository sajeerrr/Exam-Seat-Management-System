from dataclasses import dataclass

from engine.models.room_allocation import subject_conflict_key


@dataclass
class StateFeatures:
    remaining_students: int
    remaining_group_count: int
    largest_group_size: int
    smallest_group_size: int
    average_group_size: float
    group_size_variance: float
    dominant_group_ratio: float
    department_count: int
    subject_conflict_density: float
    available_room_count: int
    partial_room_count: int
    estimated_min_rooms_needed: int


class FeatureExtractor:
    def extract(self, context) -> StateFeatures:
        groups = [g for g in context.groups if g.remaining_count > 0]
        sizes = [g.remaining_count for g in groups]
        remaining_students = sum(sizes)
        largest = max(sizes) if sizes else 0
        smallest = min(sizes) if sizes else 0
        average = remaining_students / len(sizes) if sizes else 0
        variance = self._variance(sizes, average)
        departments = {g.department for g in groups}
        subject_keys = [
            subject_conflict_key(
                g.subject_code,
                g.department,
                g.subject_name,
            )
            for g in groups
        ]
        available_rooms = [
            r for r in context.room_allocations
            if r.used_capacity < r.classroom.capacity
        ]
        partial_rooms = [
            r for r in context.room_allocations
            if 0 < r.used_capacity < r.classroom.capacity
        ]

        return StateFeatures(
            remaining_students=remaining_students,
            remaining_group_count=len(groups),
            largest_group_size=largest,
            smallest_group_size=smallest,
            average_group_size=average,
            group_size_variance=variance,
            dominant_group_ratio=(
                largest / remaining_students if remaining_students else 0
            ),
            department_count=len(departments),
            subject_conflict_density=self._conflict_density(subject_keys),
            available_room_count=len(available_rooms),
            partial_room_count=len(partial_rooms),
            estimated_min_rooms_needed=self._estimated_min_rooms(
                available_rooms,
                remaining_students,
            ),
        )

    def _variance(self, values, average):
        if not values:
            return 0
        return sum((v - average) ** 2 for v in values) / len(values)

    def _conflict_density(self, subject_keys):
        if not subject_keys:
            return 0
        return 1 - (len(set(subject_keys)) / len(subject_keys))

    def _estimated_min_rooms(self, rooms, remaining_students):
        capacity = 0
        for index, room in enumerate(rooms, start=1):
            capacity += room.classroom.capacity - room.used_capacity
            if capacity >= remaining_students:
                return index
        return len(rooms)
