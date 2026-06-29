from math import ceil

import pytest

from app.services.metering import (
    DEFAULT_MAX_COMPLETION_TOKENS,
    actual_credits_from_tokens,
    estimate_credits,
)


def test_estimate_credits_with_multiplier_half():
    _, credits = estimate_credits("one two three four", 10, 0.5)
    assert credits == ceil(14 * 0.5)


def test_estimate_credits_with_multiplier_one():
    _, credits = estimate_credits("one two three four", 10, 1.0)
    assert credits == ceil(14 * 1.0)


def test_estimate_credits_with_multiplier_two():
    _, credits = estimate_credits("one two three four", 10, 2.0)
    assert credits == ceil(14 * 2.0)


def test_estimate_credits_uses_internal_512_cap():
    prompt = "one two three four five six seven eight nine ten"
    tokens, credits = estimate_credits(prompt, DEFAULT_MAX_COMPLETION_TOKENS, 1.0)
    assert DEFAULT_MAX_COMPLETION_TOKENS == 512
    assert tokens == 10 + 512
    assert credits == ceil(522 * 1.0)


@pytest.mark.parametrize(
    ("total_tokens", "multiplier", "expected"),
    [
        (11, 0.5, 6),
        (10, 0.5, 5),
        (1, 1.0, 1),
        (1, 2.0, 2),
        (100, 0.5, 50),
        (101, 0.5, 51),
    ],
)
def test_actual_credits_uses_ceil(total_tokens, multiplier, expected):
    assert actual_credits_from_tokens(total_tokens, multiplier) == expected

