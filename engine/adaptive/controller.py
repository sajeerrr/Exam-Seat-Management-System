class HyperHeuristicController:
    def select(self, scored_candidates):
        feasible = [
            c for c in scored_candidates
            if c.total_score != float("-inf")
        ]

        if not feasible:
            return None

        return max(
            feasible,
            key=lambda c: (
                -c.decision_level,
                c.total_score,
                c.score_breakdown.get("continuity", 0),
                -c.score_breakdown.get("new_fragments", 0),
                -c.score_breakdown.get("mixed_column_penalty", 0),
                c.score_breakdown.get("leftover", 0),
                c.score_breakdown.get("utilization", 0),
                -len(c.assignments),
                c.heuristic_name,
                c.signature(),
            ),
        )
