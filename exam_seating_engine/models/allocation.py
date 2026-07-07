from dataclasses import dataclass

@dataclass
class Allocation:
    room_no: str
    group_id: str
    allocated_count: int