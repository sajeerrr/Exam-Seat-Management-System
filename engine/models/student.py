from dataclasses import dataclass, field


def normalize_subject_category(raw_category: str) -> str:
    """Normalizes category into 'NORMAL', 'ELECTIVE', 'MINOR', or 'HONOURS'."""
    if not raw_category:
        return "NORMAL"
    cat = str(raw_category).strip().upper()
    if "ELECTIVE" in cat:
        return "ELECTIVE"
    if "MINOR" in cat:
        return "MINOR"
    if "HONOUR" in cat:
        return "HONOURS"
    return "NORMAL"


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
    subject_category: str = field(default="NORMAL")  # NORMAL, ELECTIVE, MINOR, HONOURS

    def __post_init__(self):
        self.subject_category = normalize_subject_category(self.subject_category)

    @property
    def is_special_subject(self) -> bool:
        """Returns True if this student belongs to Elective, Minor, or Honours."""
        return self.subject_category in {"ELECTIVE", "MINOR", "HONOURS"}

    @property
    def normalized_subject_code(self) -> str:
        """Normalized subject code for exact group/conflict matching."""
        return str(self.subject_code).strip().upper() if self.subject_code else ""
