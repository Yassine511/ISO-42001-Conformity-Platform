"""Wilson score intervals and the Metric container used by every M6 artifact.

Every published percentage carries its raw counts and a Wilson 95% interval
(plan §10: n is small — 14 holdout questions — so no percentage is reported
without its n). Pair-level metrics over correlated units (claim–citation
pairs from the same question) must label the interval as descriptive; that
wording lives in the scoring code, not here.
"""

import math
from dataclasses import asdict, dataclass


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Closed-form Wilson score interval for a binomial proportion.

    Returns (low, high) in [0, 1], or None when n == 0 (no interval exists).
    """
    if n < 0 or successes < 0 or successes > n:
        raise ValueError(f"comptes invalides : {successes}/{n}")
    if n == 0:
        return None
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass
class Metric:
    """count/n with ratio and Wilson CI — the only shape metrics are published in."""

    count: int
    n: int
    ratio: float | None
    ci_low: float | None
    ci_high: float | None

    @classmethod
    def of(cls, count: int, n: int) -> "Metric":
        ci = wilson_interval(count, n)
        return cls(
            count=count,
            n=n,
            ratio=(count / n) if n else None,
            ci_low=ci[0] if ci else None,
            ci_high=ci[1] if ci else None,
        )

    def to_dict(self) -> dict:
        return asdict(self)
