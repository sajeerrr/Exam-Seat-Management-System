from dataclasses import dataclass, field
from .group import Group


@dataclass
class RemainingPool:

    groups: list[Group] = field(default_factory=list)
    def add(self, group: Group):
        if group.remaining_count > 0:
            self.groups.append(group) #if group count greater then 0 it will add to remaining pool