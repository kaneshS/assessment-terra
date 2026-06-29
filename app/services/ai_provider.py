from dataclasses import dataclass
from typing import Protocol


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class AIFailure(Exception):
    """Raised when AI generation fails before producing usage."""

    pass


class AIPartialFailure(Exception):
    """Raised when AI fails after partial token usage."""

    def __init__(self, partial_result: GenerationResult, message: str = "Partial failure") -> None:
        self.partial_result = partial_result
        super().__init__(message)


class AIProvider(Protocol):
    def generate(self, prompt: str, max_completion_tokens: int) -> GenerationResult:
        ...


@dataclass
class MockLLMOptions:
    fail_before_usage: bool = False
    fail_after_partial: bool = False
    return_high_token_count: bool = False
    high_total_tokens: int = 55
    fixed_total_tokens: int | None = None


class MockLLM:
    """Deterministic mock LLM using word-count tokenization."""

    def __init__(self, options: MockLLMOptions | None = None) -> None:
        self.options = options or MockLLMOptions()

    def generate(self, prompt: str, max_completion_tokens: int) -> GenerationResult:
        if self.options.fail_before_usage:
            raise AIFailure("AI failed before producing usage")

        prompt_tokens = len(prompt.split())

        if self.options.fixed_total_tokens is not None:
            total_tokens = self.options.fixed_total_tokens
            completion_tokens = max(0, total_tokens - prompt_tokens)
            response_text = " ".join(["token"] * completion_tokens)
        elif self.options.return_high_token_count:
            total_tokens = self.options.high_total_tokens
            completion_tokens = max(0, total_tokens - prompt_tokens)
            response_text = " ".join(["token"] * completion_tokens)
        else:
            full_response_words = f"Echo: {prompt}".split()
            generated_words = full_response_words[:max_completion_tokens]
            response_text = " ".join(generated_words)
            completion_tokens = len(generated_words)
            total_tokens = prompt_tokens + completion_tokens

        result = GenerationResult(
            text=response_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        if self.options.fail_after_partial:
            raise AIPartialFailure(result, "AI failed after partial usage")

        return result
