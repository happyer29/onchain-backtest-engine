"""Wall-clock adapter for durable operational supervisor timestamps."""

from __future__ import annotations

import time


# Keep the system clock contract and validation rules together.
class SystemClock:
    def now_ns(self) -> int:
        return time.time_ns()


__all__ = ["SystemClock"]
