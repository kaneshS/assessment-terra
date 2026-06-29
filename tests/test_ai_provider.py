import pytest

from app.services.ai_provider import AIFailure, AIPartialFailure, MockLLM, MockLLMOptions


def test_mock_llm_echo_and_token_counts():
    llm = MockLLM()
    result = llm.generate("hello world", max_completion_tokens=100)
    assert result.text == "Echo: hello world"
    assert result.prompt_tokens == 2
    assert result.completion_tokens == len(result.text.split())
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


def test_mock_llm_completion_tokens_match_truncated_output():
    llm = MockLLM()
    result = llm.generate("hello world", max_completion_tokens=1)
    assert result.text == "Echo:"
    assert result.completion_tokens == 1
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


def test_mock_llm_high_token_count():
    llm = MockLLM(MockLLMOptions(return_high_token_count=True, high_total_tokens=55))
    result = llm.generate("one two three four five", max_completion_tokens=50)
    assert result.total_tokens == 55


def test_mock_llm_fixed_total_tokens():
    llm = MockLLM(MockLLMOptions(fixed_total_tokens=45))
    result = llm.generate("one two three four five", max_completion_tokens=512)
    assert result.total_tokens == 45
    assert result.prompt_tokens == 5
    assert result.completion_tokens == 40


def test_mock_llm_fail_before_usage_raises_ai_failure():
    llm = MockLLM(MockLLMOptions(fail_before_usage=True))
    with pytest.raises(AIFailure):
        llm.generate("hello", max_completion_tokens=100)


def test_mock_llm_fail_after_partial_raises_with_partial_result():
    llm = MockLLM(MockLLMOptions(fail_after_partial=True))
    with pytest.raises(AIPartialFailure) as exc_info:
        llm.generate("one two three", max_completion_tokens=100)
    partial = exc_info.value.partial_result
    assert partial.prompt_tokens == 3
    assert partial.total_tokens == partial.prompt_tokens + partial.completion_tokens

