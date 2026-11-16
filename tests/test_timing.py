import time

from csv_intelligence.timing import Timer


def test_steps_are_reported_in_order_with_a_total():
    timer = Timer()
    with timer.step("first"):
        time.sleep(0.01)
    with timer.step("second"):
        pass
    report = timer.report()
    assert list(report) == ["first", "second", "total"]
    assert report["first"] >= 10 and report["total"] >= report["first"] + report["second"]


def test_a_repeated_step_adds_up():
    timer = Timer()
    timer.record("query", 5)
    timer.record("query", 7)
    assert timer.ms == {"query": 12}


def test_a_failing_step_is_still_timed():
    timer = Timer()
    try:
        with timer.step("boom"):
            raise ValueError
    except ValueError:
        pass
    assert "boom" in timer.ms
