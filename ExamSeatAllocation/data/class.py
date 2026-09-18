from data.loader.classroom_loader import ClassroomLoader


def main():
    classroom_file = "resources/Class.xlsx"
    classrooms = ClassroomLoader(classroom_file).load()

    print("\n" + "=" * 72)
    print(f"                       CLASSROOM DETAILS INDEX")
    print("=" * 72)
    print(
        f"{'Room No':<12} | "
        f"{'Grid (R x B)':<14} | "
        f"{'Seats/Bench':<12} | "
        f"{'Total Benches':<14} | "
        f"{'Capacity':<10}"
    )
    print("-" * 72)

    total_capacity = 0
    total_benches = 0

    for room in classrooms:
        total_capacity += room.capacity
        total_benches += room.column_capacity
        grid_str = f"{room.rows} x {room.benches_per_row}"

        print(
            f"{room.room_no:<12} | "
            f"{grid_str:<14} | "
            f"{room.seats_per_bench:<12} | "
            f"{room.column_capacity:<14} | "
            f"{room.capacity} students"
        )

    print("-" * 72)
    print(f" TOTAL ROOMS: {len(classrooms):<5} | TOTAL BENCHES: {total_benches:<5} | TOTAL CAPACITY: {total_capacity} students")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()