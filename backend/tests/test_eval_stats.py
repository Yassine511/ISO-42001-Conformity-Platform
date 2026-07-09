"""Wilson interval and Metric container (M6 harness — pure functions)."""

import pytest

from app.eval.stats import Metric, wilson_interval


def test_wilson_known_value():
    # 8/10 with z=1.96: standard Wilson result ≈ (0.490, 0.943)
    low, high = wilson_interval(8, 10)
    assert low == pytest.approx(0.4901, abs=1e-3)
    assert high == pytest.approx(0.9433, abs=1e-3)


def test_wilson_zero_successes():
    low, high = wilson_interval(0, 14)
    assert low == 0.0
    assert 0.0 < high < 0.3


def test_wilson_all_successes():
    low, high = wilson_interval(14, 14)
    assert high == 1.0
    assert 0.7 < low < 1.0


def test_wilson_n_zero_returns_none():
    assert wilson_interval(0, 0) is None


def test_wilson_invalid_counts_raise():
    with pytest.raises(ValueError):
        wilson_interval(5, 3)
    with pytest.raises(ValueError):
        wilson_interval(-1, 3)


def test_metric_of_embeds_counts_and_ci():
    m = Metric.of(3, 14)
    d = m.to_dict()
    assert d["count"] == 3 and d["n"] == 14
    assert d["ratio"] == pytest.approx(3 / 14)
    assert d["ci_low"] is not None and d["ci_high"] is not None


def test_metric_of_n_zero():
    d = Metric.of(0, 0).to_dict()
    assert d["ratio"] is None and d["ci_low"] is None and d["ci_high"] is None
