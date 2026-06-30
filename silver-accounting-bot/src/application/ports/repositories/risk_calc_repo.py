from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from domain.enums import RiskScoreLevel


class RiskCalcRepo(Protocol):
    def compute_score(self, exposure: dict, violations: list[dict]) -> tuple[Decimal, RiskScoreLevel]: ...
