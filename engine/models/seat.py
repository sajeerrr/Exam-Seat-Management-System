from dataclasses import dataclass
from .student import Student
from .classroom import Classroom


@dataclass
class Seat:
    classroom: Classroom
    bench_no: int
    stream: str
    student: Student

    @property
    def room_no(self):
        return self.classroom.room_no