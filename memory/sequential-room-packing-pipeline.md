---
name: sequential-room-packing-pipeline
description: Hybrid allocation pipeline starting with sequential room packing followed by CP-SAT, ABC/ABA optimization, local optimization, LNS, and validation.
metadata:
  type: project
---

# Sequential Room Packing Pipeline

The exam seating allocation engine follows a robust hybrid pipeline:
1. **Sequential Room Packing**: Establishes sensible room structure and packs classrooms deterministically based on official room order (`resources/Class.xlsx`) to maximize room filling before opening new rooms.
2. **CP-SAT Solver**: Solves global assignment constraints and enforces hard rules (room capacity, stream limits, adjacent subject separation).
3. **ABC/ABA Optimization**: Pattern matching and stream arrangement optimization for multi-department sessions.
4. **Local Optimization**: Refines tiny fragments ($\le 5$ students) and consolidates department placements.
5. **LNS (Large Neighborhood Search)**: Iterative destroy-and-repair heuristic with strict validity checks and rollback safeguards.
6. **Validation**: Final constraint check ensuring zero violations, zero duplicates, and 100% student completeness.

[[hyper-heuristic-allocator]]
[[sequential-allocator]]
