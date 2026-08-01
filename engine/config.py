# engine/config.py
"""
Central configuration for the Exam Seat Management Engine.
Never hardcode these values anywhere else in the codebase.
"""

# ── Stream identifiers ──────────────────────────────────────────────────────
STREAMS: list[str] = ["A", "B", "C"]
STREAM_COUNT: int = len(STREAMS)

# ── Default classroom dimensions ────────────────────────────────────────────
DEFAULT_ROWS: int = 5
DEFAULT_BENCHES_PER_ROW: int = 3
DEFAULT_SEATS_PER_BENCH: int = 3

# Derived: seats in one stream column  (rows × benches_per_row)
DEFAULT_STREAM_CAPACITY: int = DEFAULT_ROWS * DEFAULT_BENCHES_PER_ROW   # 15
# Derived: total seats per room
DEFAULT_ROOM_CAPACITY: int = DEFAULT_STREAM_CAPACITY * STREAM_COUNT      # 45

# ── Session identifiers ─────────────────────────────────────────────────────
SESSION_FN: str = "FN"   # Forenoon
SESSION_AN: str = "AN"   # Afternoon

# ── Logging format ──────────────────────────────────────────────────────────
LOG_FORMAT: str = "%(levelname)s | %(name)s | %(message)s"
