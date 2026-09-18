# engine/config.py
"""
Configuration constants for the seating allocation engine.
Weights and thresholds are centralized here for easy tuning.
"""


class ScoringWeights:
    """Weights for candidate evaluation in the hyper-heuristic allocator.

    Higher weights = more influence on the final score.
    Positive values reward, negative values penalize.

    Rationale for current values:
    - abc_reward (140): Strongly prefer ABC pattern (3 distinct depts in A,B,C)
    - continuity (95): Reward extending existing department placements
    - fragmentation (70): Reward completing groups (reduces fragmentation)
    - leftover (35): Reward allocations that leave clean remainder counts
    - balance (30): Reward balanced group sizes across remaining students
    - diversity (18): Reward using diverse departments per room
    - utilization (15): Reward filling rooms to capacity
    - future (20): Reward maintaining good future room pressure
    - new_fragments (-90): Strongly penalize creating new department fragments
    - department_room_penalty (-55): Penalize spreading departments across many rooms
    - mixed_column_penalty (-45): Penalize mixing departments in a single stream
    - repeated_pattern_penalty (-70): Penalize ABA/AAB patterns vs ABC
    - partial_penalty (-35): Penalize leaving rooms partially filled
    - final_tail_penalty (-80): Strongly penalize tiny leftover groups at the end
    """

    # Rewards (positive weights)
    ABC_REWARD: float = 140.0
    CONTINUITY: float = 95.0
    FRAGMENTATION: float = 70.0
    LEFTOVER: float = 35.0
    BALANCE: float = 30.0
    DIVERSITY: float = 18.0
    UTILIZATION: float = 15.0
    FUTURE: float = 20.0

    # Penalties (negative weights - stored as positive, applied as negative)
    NEW_FRAGMENTS_PENALTY: float = 90.0
    DEPARTMENT_ROOM_PENALTY: float = 55.0
    MIXED_COLUMN_PENALTY: float = 45.0
    REPEATED_PATTERN_PENALTY: float = 70.0
    PARTIAL_PENALTY: float = 35.0
    FINAL_TAIL_PENALTY: float = 80.0


class AllocationLimits:
    """Limits and thresholds for allocation constraints."""

    # Maximum departments per room
    MAX_DEPARTMENTS_NORMAL: int = 3
    MAX_DEPARTMENTS_FALLBACK: int = 4

    # Stream capacity (students per stream/column)
    DEFAULT_STREAM_CAPACITY: int = 15

    # Optimization limits
    MAX_OPTIMIZATION_PASSES: int = 8
    MAX_STALLED_STEPS: int = 3  # Increased from 2 for better allocation

    # Candidate generation limits
    MAX_GROUPS_PER_STEP: int = 8
    MAX_CANDIDATES_PER_STEP: int = 70

    # Fragment repair threshold
    TINY_FRAGMENT_THRESHOLD: int = 5


class AllocationThresholds:
    """Threshold values for allocation decisions."""

    # Dominant group ratio that triggers ABA pattern
    DOMINANT_GROUP_RATIO: float = 0.45

    # Minimum students for dominant group to use ABA
    DOMINANT_GROUP_MIN_SIZE: int = 20

    # Preferred remainder counts (multiples of stream capacity)
    PREFERRED_REMAINDERS: tuple = (0, 15, 30, 45, 60, 75, 90, 105, 120)

    # Tiny remainder penalty threshold
    TINY_REMAINDER_THRESHOLD: int = 5
    TINY_REMAINDER_PENALTY: float = 8.0
