# engine/config.py
"""
Configuration constants for the seating allocation engine.
Weights and thresholds are centralized here for easy tuning.
"""


class AllocationLimits:
    """Limits and thresholds for allocation constraints."""

    # Maximum departments per room
    MAX_DEPARTMENTS_NORMAL: int = 4
    MAX_DEPARTMENTS_FALLBACK: int = 4
    MAX_DEPARTMENTS_EXTREME: int = 5
    MAX_DEPARTMENTS_PER_ROOM: int = 4

    # Maximum subjects (exams / question papers) per room
    MAX_SUBJECTS_NORMAL: int = 4
    MAX_SUBJECTS_FALLBACK: int = 4
    MAX_SUBJECTS_EXTREME: int = 5
    MAX_SUBJECTS_PER_ROOM: int = 4

    # Stream capacity (students per stream/column)
    DEFAULT_STREAM_CAPACITY: int = 15

    # Optimization limits
    MAX_OPTIMIZATION_PASSES: int = 8
    MAX_STALLED_STEPS: int = 3

    # Candidate generation limits
    MAX_GROUPS_PER_STEP: int = 8
    MAX_CANDIDATES_PER_STEP: int = 70

    # Fragment repair threshold
    TINY_FRAGMENT_THRESHOLD: int = 5

    # Minimum students required per allocated room (dynamic threshold)
    MIN_ROOM_STUDENTS: int = 25
    TARGET_ROOM_STUDENTS_MIN: int = 25
    TARGET_ROOM_STUDENTS_MAX: int = 30


class CPSolverConfig:
    """Configuration for the CP-SAT solver (Phase 1)."""
    TIME_LIMIT_SECONDS: float = 10.0
    NUM_WORKERS: int = 4
    # Weights for the CP-SAT objective
    ABC_BONUS: int = 200      # Reward for ABC room (3 distinct depts, one per stream)
    TRUE_ABC_BONUS: int = 400 # Strong reward for true ABC room with single-dept streams
    ABA_BONUS: int = 100      # Reward for ABA room (A==C != B, one dept per stream)
    STREAM_OCCUPANCY_BONUS: int = 10  # Reward per occupied stream
    STREAM_PURITY_BONUS: int = 80     # Reward for stream containing exactly one department
    ROOM_USAGE_PENALTY: int = 5     # Penalty per room used (to encourage consolidation)
    UTILIZATION_BONUS: int = 1      # Reward for total utilization (less important now)
    FRAGMENTATION_PENALTY: int = 20   # Penalty for fragmentation (extra rooms per dept)
    CONSOLIDATION_PENALTY: int = 150  # Strong penalty for spreading department across rooms
    UNDERFILLED_ROOM_PENALTY: int = 250  # Penalty for rooms with 0 < students < MIN_ROOM_STUDENTS


