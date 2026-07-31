from dataclasses import dataclass

from .group import Group

@dataclass
class Allocation:
    
    stream: str      # "A", "B", or "C"
    group: Group
    start_index: int
    end_index: int
    allocated_count: int