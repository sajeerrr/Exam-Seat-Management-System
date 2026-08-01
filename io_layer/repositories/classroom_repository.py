# io_layer/repositories/classroom_repository.py
"""
In-memory classroom repository.
"""

import logging
from engine.models.classroom import Classroom
from engine.models.room_allocation import RoomAllocation

logger = logging.getLogger(__name__)


class ClassroomRepository:
    """
    Stores classrooms and vends RoomAllocation objects for the engine.

    Usage
    -----
    repo = ClassroomRepository()
    repo.load(classrooms)
    allocations = repo.get_room_allocations()
    """

    def __init__(self):
        self._classrooms: list[Classroom] = []

    def load(self, classrooms: list[Classroom]) -> None:
        self._classrooms = list(classrooms)
        logger.info("ClassroomRepository loaded %d classrooms", len(self._classrooms))

    def get_all(self) -> list[Classroom]:
        return list(self._classrooms)

    def get_room_allocations(self) -> list[RoomAllocation]:
        """Return a fresh RoomAllocation wrapper for every classroom."""
        return [RoomAllocation(c) for c in self._classrooms]

    def count(self) -> int:
        return len(self._classrooms)

    def __len__(self) -> int:
        return self.count()
