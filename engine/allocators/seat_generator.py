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
        allocations = []

        for stream in streams:
            allocation = room.streams.get(stream)
            allocations.append(allocation)

        bench_no = 1

        for i in range(room.classroom.column_capacity):
            for allocation in allocations:

                if allocation is None:
                    continue

                if i >= allocation.allocated_count:
                    continue

                student = allocation.students[i]

                seat = Seat(
                    room_no=room.classroom,
                    bench_no=bench_no,
                    stream=allocation.stream,
                    student=student,
                )

                plan.add(seat)

            bench_no += 1