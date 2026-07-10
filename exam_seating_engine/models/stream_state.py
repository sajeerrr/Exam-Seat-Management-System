from dataclasses import dataclass
from typing import Optional

from .group import Group


@dataclass
class StreamState: #for every stream group allocate
    stream: str
    group: Optional[Group] = None

    @property
    def is_empty(self):
        return self.group is None