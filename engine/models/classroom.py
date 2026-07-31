from dataclasses import dataclass

@dataclass
class Classroom:
    room_no: str
    rows: int
    benches_per_row: int
    seats_per_bench: int = 3

    @property #capacity of students in a class
    def capacity(self):
        return self.rows * self.benches_per_row * self.seats_per_bench

    @property #capacity of bench in a class 
    def column_capacity(self):
        return self.rows * self.benches_per_row