from dataclasses import dataclass, field


@dataclass
class ValidationResult:

    success: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str):
        self.success = False
        self.errors.append(message)

    def add_warning(self, message: str):
        self.warnings.append(message)