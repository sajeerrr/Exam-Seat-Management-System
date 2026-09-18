class LookaheadSimulator:
    def __init__(self, depth=1, discount=0.45):
        self.depth = depth
        self.discount = discount

    def adjust_scores(self, candidates, context, features):
        if self.depth <= 0:
            return candidates

        for candidate in candidates:
            if candidate.total_score == float("-inf"):
                continue
            future_score = self._future_score(candidate, context)
            candidate.score_breakdown["lookahead"] = future_score
            candidate.total_score += self.discount * future_score

        return candidates

    def _future_score(self, candidate, context):
        projected = {
            g.group_id: g.remaining_count
            for g in context.groups
            if g.remaining_count > 0
        }
        for assignment in candidate.assignments:
            projected[assignment.group_id] -= assignment.count
        remaining_counts = [v for v in projected.values() if v > 0]

        if not remaining_counts:
            return 100

        future_rooms = context.room_allocations[candidate.room_index + 1:]
        future_capacity = sum(r.classroom.capacity for r in future_rooms)
        if future_capacity <= 0:
            return -100

        remaining = sum(remaining_counts)
        if remaining < 15:
            return -60 + remaining

        pressure = min(1, remaining / future_capacity)
        balance = self._balance(remaining_counts)
        return 60 * (1 - abs(0.75 - pressure)) + 40 * balance

    def _balance(self, values):
        if not values:
            return 1
        average = sum(values) / len(values)
        variance = sum((v - average) ** 2 for v in values) / len(values)
        return 1 / (1 + variance / 100)
