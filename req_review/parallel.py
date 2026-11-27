"""v12: параллельные обращения к модели с общим ограничителем.

LLM_CONCURRENCY (по умолчанию 3) — сколько запросов к модели одновременно «в полёте»; LLM_RPM / LLM_MIN_INTERVAL
соблюдаются ограничителем частоты в BaseLLM (старты запросов разносятся во времени, общий для всех потоков).
Сборка детерминирована: результаты возвращаются в порядке входа, а не в порядке ответов модели."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def concurrency() -> int:
    try:
        return max(1, int(os.getenv("LLM_CONCURRENCY", "3") or 3))
    except ValueError:
        return 3


def pmap(fn: Callable[[T], R], items: Iterable[T], n: int | None = None) -> list[R]:
    """[fn(x) for x in items] — параллельно, порядок результатов = порядок входа. Исключение первого по порядку
    элемента пробрасывается после завершения всех (как в последовательном цикле — без «полузаписанных» результатов)."""
    items = list(items)
    n = min(n or concurrency(), len(items))
    if n <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="llm") as ex:
        futs = [ex.submit(fn, x) for x in items]
        errs = [f.exception() for f in futs]
    for e in errs:
        if e is not None:
            raise e
    return [f.result() for f in futs]
