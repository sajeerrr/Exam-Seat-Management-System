from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreamAssignment:
    stream: str
    group_id: str
    count: int


@dataclass
class AllocationCandidate:
    room_index: int
    assignments: list[StreamAssignment]
    heuristic_name: str
    decision_level: int = 99
    score_breakdown: dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0

    @property
    def used_capacity(self) -> int:
        return sum(a.count for a in self.assignments)

    def signature(self):
        return tuple(
            sorted(
                (a.stream, a.group_id, a.count)
                for a in self.assignments
                if a.count > 0
            )
        )
