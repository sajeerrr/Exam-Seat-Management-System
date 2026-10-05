from dataclasses import dataclass, field


@dataclass
class ValidationResult:

    success: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    normal_subject_violations: int = 0
    elective_adjacency_violations: int = 0
    minor_adjacency_violations: int = 0
    honours_adjacency_violations: int = 0
    max_departments_per_room: int = 0
    missing_students: int = 0
    duplicate_students: int = 0
    capacity_violations: int = 0

    def add_error(self, message: str):
        self.success = False
        self.errors.append(message)

    def add_warning(self, message: str):
        self.warnings.append(message)

    def generate_report(self) -> str:
        return (
            "================ ALLOCATION VALIDATION REPORT ================\n"
            f"Normal subject violations: {self.normal_subject_violations}\n"
            f"Elective subject adjacency violations: {self.elective_adjacency_violations}\n"
            f"Minor subject adjacency violations: {self.minor_adjacency_violations}\n"
            f"Honours subject adjacency violations: {self.honours_adjacency_violations}\n"
            f"Maximum departments per room: {self.max_departments_per_room}\n"
            f"Missing students: {self.missing_students}\n"
            f"Duplicate students: {self.duplicate_students}\n"
            f"Capacity violations: {self.capacity_violations}\n"
            f"Status: {'PASSED' if self.success else 'FAILED'}\n"
            "=============================================================="
        )
