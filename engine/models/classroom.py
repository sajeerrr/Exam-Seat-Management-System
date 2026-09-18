from dataclasses import dataclass


@dataclass
class Classroom:
    room_no: str
    rows: int = 5
    benches_per_row: int = 3
    seats_per_bench: int = 3

    @property  # total student capacity
    def capacity(self) -> int:
        return self.rows * self.benches_per_row * self.seats_per_bench

    @property  # total bench capacity
    def column_capacity(self) -> int:
        return self.rows * self.benches_per_row