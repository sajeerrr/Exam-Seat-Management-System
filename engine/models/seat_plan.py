# engine/models/seat_plan.py

from dataclasses import dataclass, field
from .seat import Seat


@dataclass
class SeatPlan:

    seats: list[Seat] = field(default_factory=list)

    def add(self, seat):
        self.seats.append(seat)

    def add_seat(self, seat):
        self.seats.append(seat)