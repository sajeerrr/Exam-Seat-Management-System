from dataclasses import dataclass

from .group import Group


@dataclass
class StreamState: #for every stream group allocate

    stream: str
    group: Group | None