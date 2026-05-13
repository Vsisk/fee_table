from __future__ import annotations

from datetime import date
import random


class FeeTableIdGenerator:
    """Generate 16 digit ids in yyyyMMdd + 8 random digits format."""

    def __init__(self, today: date | None = None, rng: random.Random | None = None) -> None:
        self._today = today
        self._rng = rng or random.Random()

    def new_id(self) -> str:
        day = (self._today or date.today()).strftime("%Y%m%d")
        suffix = self._rng.randint(0, 99_999_999)
        return f"{day}{suffix:08d}"
