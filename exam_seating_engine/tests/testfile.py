from exam_seating_engine.algorithms.priority_queue import PriorityQueue
from exam_seating_engine.tests.helper import build_group


def test_push():

    pq = PriorityQueue()
    pq.push(build_group("ME",90))
    pq.push(build_group("CE",75))
    pq.push(build_group("EE",60))
    pq.push(build_group("CS",44))
    assert pq.peek().department == "ME"


def test_pop():

    pq = PriorityQueue()
    pq.push(build_group("ME",90))
    pq.push(build_group("CE",75))
    pq.push(build_group("EE",60))
    top = pq.pop()
    assert top.department == "ME"
    assert pq.peek().department == "CE"


def test_update():

    pq = PriorityQueue()
    me = build_group("ME",90)
    ce = build_group("CE",75)
    ee = build_group("EE",60)
    pq.push(me)
    pq.push(ce)
    pq.push(ee)
    me.allocate(60)   # 90 - 60 = 30 remaining, less than CE's 75
    pq.update(me)
    assert pq.peek().department == "CE"


def test_remove():

    pq = PriorityQueue()
    me = build_group("ME",90)
    ce = build_group("CE",75)
    pq.push(me)
    pq.push(ce)
    pq.remove(me)
    assert pq.peek().department == "CE"


def test_empty():

    pq = PriorityQueue()
    assert pq.pop() is None
    assert pq.peek() is None


def test_size():

    pq = PriorityQueue()
    assert pq.size() == 0
    pq.push(build_group("ME",10))
    assert pq.size() == 1