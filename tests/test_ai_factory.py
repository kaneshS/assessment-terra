import pytest

from app.core.settings import Settings, get_settings
from app.services.ai_factory import create_ai_provider
from app.services.ai_provider import MockLLM


def test_create_ai_provider_mock():
    provider = create_ai_provider(Settings(ai_provider="mock"))
    assert isinstance(provider, MockLLM)


def test_create_ai_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown AI provider"):
        create_ai_provider(Settings(ai_provider="unknown"))


def test_settings_default_local(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.ai_provider == "local"
    assert settings.model_name == "Qwen/Qwen2.5-0.5B-Instruct"
    get_settings.cache_clear()


def test_create_ai_provider_local_falls_back_to_mock_on_import_error(monkeypatch):
    def _raise_import_error(_model_name: str):
        raise ImportError("torch not installed")

    monkeypatch.setattr(
        "app.services.ai_factory.get_local_llm_provider",
        _raise_import_error,
    )
    provider = create_ai_provider(Settings(ai_provider="local"))
    assert isinstance(provider, MockLLM)

