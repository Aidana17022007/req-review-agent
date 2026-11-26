"""RAG ReqLens: база знаний (стандарты, нормы РК, шаблоны требований) и поиск по длинным документам.

    python -m req_review.rag build [kb/]      — собрать индекс базы знаний
    python -m req_review.rag search "запрос"  — найти фрагменты

RAG=off выключает всё: агент работает как раньше.
"""
from .index import Index, build_index, get_kb, rag_enabled  # noqa: F401
