import pytest


@pytest.fixture(autouse=True)
def _no_llm_cache(monkeypatch):
    """Тесты не должны читать/писать кэш ответов модели."""
    monkeypatch.setenv("LLM_CACHE", "0")


@pytest.fixture(autouse=True)
def _no_demo_limits(monkeypatch):
    """v9: лимиты демо-сервера в тестах выключены, пока тест сам их не задаст."""
    for k in ("DEMO_UPLOADS_PER_IP", "DEMO_UPLOADS_TOTAL", "PORT"):
        monkeypatch.delenv(k, raising=False)
    try:
        from req_review.web import limits
    except ImportError:
        return
    limits.reset()
