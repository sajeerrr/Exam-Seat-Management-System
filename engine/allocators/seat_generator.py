from engine.models.seat import Seat
from engine.models.seat_plan import SeatPlan


class SeatGenerator:

    def execute(self, context):
        plan = SeatPlan()

        for room in context.room_allocations:
            self.generate_room(room, plan)

        return plan

    def generate_room(self, room, plan):
        streams = ["A", "B", "C"]

        for stream_name in streams:
            stream_students = [
                student
                for alloc in room.allocations
                if alloc.stream == stream_name
                for student in alloc.students
            ]

            bench_no = 1
            for student in stream_students:
                seat = Seat(
                    classroom=room.classroom,
                    bench_no=bench_no,
                    stream=stream_name,
                    student=student,
                )
                plan.add(seat)
                bench_no += 1