import pytest


@pytest.fixture(autouse=True)
def _no_llm_cache(monkeypatch):
    """Тесты не должны читать/писать кэш ответов модели."""
    monkeypatch.setenv("LLM_CACHE", "0")
