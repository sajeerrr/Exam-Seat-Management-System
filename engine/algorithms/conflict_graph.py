class ConflictGraph:
    """
    Stores department conflicts.

    Example:
        CS -> IT
        IT -> CS
    """

    def __init__(self):
        self.graph = {}

    def add_conflict(self, dept1: str, dept2: str):

        self.graph.setdefault(dept1, set()).add(dept2)
        self.graph.setdefault(dept2, set()).add(dept1)

    def has_conflict(self, dept1: str, dept2: str) -> bool:

        return dept2 in self.graph.get(dept1, set())

    def remove_conflict(self, dept1: str, dept2: str):

        self.graph.get(dept1, set()).discard(dept2)
        self.graph.get(dept2, set()).discard(dept1)