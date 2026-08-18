# engine/allocators/seat_generator.py

from engine.models.seat import Seat
from engine.models.seat_plan import SeatPlan


class SeatGenerator:

    def generate(self, context) -> SeatPlan:
        seat_plan = SeatPlan()

        for room_alloc in context.room_allocations:
            classroom = room_alloc.classroom

            # Iterate over all 3 stream columns in the room
            for stream_name in ["A", "B", "C"]:
                stream = room_alloc.get_stream(stream_name)
                if not stream:
                    continue

                # Map allocated students to benches sequentially
                for index, student in enumerate(stream.students, start=1):
                    seat = Seat(
                        classroom=classroom,  # <-- PASS classroom object here
                        bench_no=index,
                        stream=stream_name,
                        student=student,
                    )
                    seat_plan.add_seat(seat)

        return seat_plan