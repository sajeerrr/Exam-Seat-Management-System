for seat in plan.seats:

    print(
        seat.room_no,
        seat.bench_no,
        seat.stream,
        seat.student.register_no,
        seat.student.name,
    )