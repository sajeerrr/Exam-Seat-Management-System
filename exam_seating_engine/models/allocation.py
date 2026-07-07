from dataclasses import dataclass
from group import Group


@dataclass
class Allocation:
    group: Group
    allocated_count: int