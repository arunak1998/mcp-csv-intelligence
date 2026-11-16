"""Wall-clock milliseconds per named step, reported with every answer, dashboard, upload and query."""

import time
from collections.abc import Iterator
from contextlib import contextmanager


def elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


class Timer:
    """Times named steps; a step that runs more than once adds up. report() adds the total."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self.ms: dict[str, int] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, elapsed_ms(start))

    def record(self, name: str, ms: int) -> None:
        self.ms[name] = self.ms.get(name, 0) + ms

    def report(self) -> dict[str, int]:
        """The steps in the order they first ran, plus total time since the timer was created."""
        return {**self.ms, "total": elapsed_ms(self._start)}
