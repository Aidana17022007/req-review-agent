"""Перефразы чистых ТЗ: тот же смысл другими словами (замены, сохраняющие значения, термины и ID).

Запуск: python bench/clean/paraphrase.py  →  bench/clean/paraphrased/<имя>.md
Замены не трогают термины глоссария (иначе появился бы настоящий дефект «один объект — разные названия»),
числа, единицы, идентификаторы и тексты сообщений в «…». Перефраз нужен, чтобы ложные тревоги мерить не на одной
удачной формулировке.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "paraphrased"

RU = [
    (r"\bне позднее (\d)", r"в пределах \1"),
    (r"\bне дольше (\d)", r"не более \1"),
    (r"\bпоказывает\b", "отображает"), (r"\bпоказываются\b", "отображаются"), (r"\bпоказывается\b", "отображается"),
    (r"\bпоказаны\b", "отображены"),
    (r"\bвключительно\b", "с обеими границами"),
    (r"\bтолько по TLS\b", "исключительно по TLS"), (r"\bтолько по протоколу TLS\b", "исключительно по протоколу TLS"),
    (r"Журнал аудита записывает (каждый|каждую|каждое)", r"В журнал аудита записывается \1"),
    (r"мониторинг отправляет оповещение дежурной смене", "дежурная смена получает оповещение от мониторинга"),
    (r"Резервная копия ([^;|]*?) создаётся", r"Резервное копирование \1 выполняется"),
    (r"\bне превышает\b", "не больше"),
    (r"\bне взимается\b", "не берётся"),
    (r"\bпосле подтверждения\b", "с момента подтверждения"),
    (r"\bдоступна только после\b", "открывается только после"), (r"\bдоступен только после\b", "открывается только после"),
]
KK = [
    (r"\bжіберіледі\b", "жолданады"),
    (r"\bкөрсетеді\b", "бейнелейді"),
    (r"\bқолжетімді\b", "пайдалануға болады"),
]


def _apply(text: str, rules) -> str:
    out = []
    for line in text.splitlines():
        parts = re.split(r"(«[^»]*»)", line)  # тексты сообщений не трогаем
        for i, p in enumerate(parts):
            if i % 2 == 0:
                for a, b in rules:
                    p = re.sub(a, b, p)
            parts[i] = p
        out.append("".join(parts))
    return "\n".join(out) + "\n"


def build() -> list[Path]:
    OUT.mkdir(exist_ok=True)
    made = []
    for p in sorted(HERE.glob("*.md")):
        if p.name == "README.md":
            continue
        text = p.read_text(encoding="utf-8")
        new = _apply(text, KK if p.stem.endswith("_kk") else RU)
        new = new.replace("Вымышленный документ без внесённых дефектов", "Перефраз чистого вымышленного документа: тот же смысл, "
                          "другие формулировки; дефектов нет", 1)
        assert new != text, p.name
        q = OUT / p.name
        q.write_text(new, encoding="utf-8")
        made.append(q)
    return made


if __name__ == "__main__":
    for q in build():
        print(q.relative_to(HERE.parent.parent))
