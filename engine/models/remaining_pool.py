from dataclasses import dataclass, field


@dataclass
class RemainingPool:

    groups: list = field(default_factory=list)

    def add(self, group):

        if group not in self.groups:
            self.groups.append(group)

    def remove(self, group):

        if group in self.groups:
            self.groups.remove(group)

    def is_empty(self):

        return len(self.groups) == 0