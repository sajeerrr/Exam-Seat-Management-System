from dataclasses import dataclass

@dataclass
class Student:
    register_no: str
    name: str
    department: str
    semester: int
    section: str
    subject_code: str
    subject_name: str
    exam_date: str
    session: str      # FN / AN