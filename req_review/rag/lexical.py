"""Лексический поиск BM25 на чистом Python — офлайн-фолбэк и вторая половина гибридного поиска."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""и в во на с со к ко по о об от до из за для при не ни но а или же ли то это как что чтобы если
должен должна должно должны быть есть был была были который которая которые также только может могут
the a an of to in for and or is are be""".split())


def tokens(text: str) -> list[str]:
    """Токены с грубым стеммингом (первые 6 букв) — устойчиво к русским окончаниям без внешних библиотек."""
    return [w[:6] for w in re.findall(r"[а-яёa-z0-9]+", text.lower().replace("ё", "е")) if w not in STOP and len(w) > 1]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.toks = [tokens(d) for d in docs]
        self.tf = [Counter(t) for t in self.toks]
        self.avgdl = (sum(len(t) for t in self.toks) / len(self.toks)) if self.toks else 0.0
        df = Counter(w for t in self.toks for w in set(t))
        n = len(self.toks)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for tf, toks in zip(self.tf, self.toks):
            dl = len(toks) or 1
            s = 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out

    def search(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        sc = self.scores(query)
        return sorted(((i, s) for i, s in enumerate(sc) if s > 0), key=lambda x: -x[1])[:k]
