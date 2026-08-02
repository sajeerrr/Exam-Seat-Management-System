from dataclasses import dataclass, field

@dataclass
class Student:
    register_no: str          # University Register No  e.g. TKM23CE002
    name: str
    department: str
    semester: int
    section: str
    subject_code: str
    subject_name: str
    exam_date: str
    session: str              # FN / AN
    roll_no: str = field(default="")   # College Roll No  e.g. B23CEA01