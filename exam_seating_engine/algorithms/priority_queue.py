from __future__ import annotations
from typing import Optional
from exam_seating_engine.models.group import Group


class PriorityQueue:
    """
    Max Heap implementation for Group objects.

    The group with the highest remaining student count
    always stays at the root.

    Complexity

    push()   O(log n)

    pop()    O(log n)

    peek()   O(1)

    update() O(log n)

    remove() O(log n)
    """

    def __init__(self):

        self._heap: list[Group] = []

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def push(self, group: Group) -> None:

        """
        Insert a group into the heap.
        """

        self._heap.append(group)
        self._heapify_up(len(self._heap) - 1)

    def pop(self) -> Optional[Group]:

        """
        Remove and return the largest group.
        """

        if not self._heap:
            return None

        if len(self._heap) == 1:
            return self._heap.pop()

        root = self._heap[0]

        self._heap[0] = self._heap.pop()

        self._heapify_down(0)

        return root

    def peek(self) -> Optional[Group]:

        """
        Return the largest group.
        """

        if not self._heap:
            return None

        return self._heap[0]

    def update(self, group: Group) -> None:
        """
        Reorder heap after the group's priority changes.
        """

        try:

            index = self._heap.index(group)

        except ValueError:

            return

        self._heapify_up(index)

        self._heapify_down(index)

    def remove(self, group: Group) -> bool:
        """
        Remove a specific group.
        """

        try:

            index = self._heap.index(group)

        except ValueError:

            return False

        last = self._heap.pop()

        if index < len(self._heap):

            self._heap[index] = last

            self._heapify_up(index)

            self._heapify_down(index)

        return True

    def is_empty(self) -> bool:

        return len(self._heap) == 0

    def size(self) -> int:

        return len(self._heap)

    def clear(self) -> None:

        self._heap.clear()

    def to_list(self):

        return list(self._heap)

    # --------------------------------------------------
    # Heap Helpers
    # --------------------------------------------------

    def _parent(self, index: int) -> int:

        return (index - 1) // 2

    def _left(self, index: int) -> int:

        return 2 * index + 1

    def _right(self, index: int) -> int:

        return 2 * index + 2

    def _swap(self, i: int, j: int):

        self._heap[i], self._heap[j] = self._heap[j], self._heap[i]

    def _heapify_up(self, index: int):

        while index > 0:

            parent = self._parent(index)

            if self._heap[index].priority <= self._heap[parent].priority:

                break

            self._swap(index, parent)

            index = parent

    def _heapify_down(self, index: int):

        size = len(self._heap)

        while True:

            largest = index

            left = self._left(index)

            right = self._right(index)

            if (
                left < size
                and self._heap[left].priority
                > self._heap[largest].priority
            ):

                largest = left

            if (
                right < size
                and self._heap[right].priority
                > self._heap[largest].priority
            ):

                largest = right

            if largest == index:

                break

            self._swap(index, largest)

            index = largest