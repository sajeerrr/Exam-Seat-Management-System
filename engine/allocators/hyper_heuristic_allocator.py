from engine.adaptive.adaptive_allocator import AdaptiveAllocationEngine


class HyperHeuristicAllocator:
    """Compatibility wrapper for the adaptive hyper-heuristic engine."""

    def __init__(self):
        self.engine = AdaptiveAllocationEngine()

    def execute(self, context):
        return self.engine.execute(context)
