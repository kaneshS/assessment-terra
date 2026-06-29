from math import ceil

DEFAULT_MAX_COMPLETION_TOKENS = 512


def count_prompt_tokens(prompt: str) -> int:
    return len(prompt.split())


def estimate_credits(
    prompt: str, max_completion_tokens: int, multiplier: float
) -> tuple[int, int]:
    """Return (estimated_tokens, estimated_credits).

    Pre-request estimates use word-split prompt tokenization plus the internal
    completion cap (conservative upper bound for reservation).
    Actual billing after generation uses tokenizer-accurate counts from the
    AI provider, which may be lower than this estimate.
    """
    prompt_tokens = count_prompt_tokens(prompt)
    estimated_tokens = prompt_tokens + max_completion_tokens
    estimated_credits = ceil(estimated_tokens * multiplier)
    return estimated_tokens, estimated_credits


def actual_credits_from_tokens(total_tokens: int, multiplier: float) -> int:
    return ceil(total_tokens * multiplier)
