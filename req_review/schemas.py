"""Официальные JSON-схемы ответов для Gemini (generationConfig.responseSchema, R3).

Модель не может выйти за схему — ремонт JSON нужен реже. Если модель/API схему не принимает, клиент
откатывается на обычный JSON-режим (GEMINI_RESPONSE_SCHEMA=0 выключает схемы совсем).
"""
from __future__ import annotations

S, B, N = {"type": "STRING"}, {"type": "BOOLEAN"}, {"type": "INTEGER"}


def obj(props: dict, required: list[str] | None = None) -> dict:
    d = {"type": "OBJECT", "properties": props}
    if required:
        d["required"] = required
    return d


def arr(item: dict) -> dict:
    return {"type": "ARRAY", "items": item}


SEVERITY = {"type": "STRING", "enum": ["critical", "major", "minor"]}
FINDING = obj({"criterion": S, "quote": S, "problem": S, "severity": SEVERITY, "fix": S},
              ["criterion", "quote", "problem", "severity", "fix"])

SCHEMAS = {
    "check": obj({"results": arr(obj({
        "id": S, "ears": S, "category": S,
        "findings": arr(FINDING),
        "dismissed_hints": arr(S),
        "suggested_rewrite": S,
        "test": obj({"possible": B, "scenarios": arr(obj({"title": S, "gherkin": S}, ["gherkin"])),
                     "reason": S, "blocker_quote": S}, ["possible"]),
    }, ["id", "findings"]))}, ["results"]),
    "set": obj({"findings": arr(obj({
        "type": S, "criterion": S, "refs": arr(obj({"id": S, "quote": S}, ["id", "quote"])),
        "problem": S, "severity": SEVERITY, "fix": S,
    }, ["type", "criterion", "refs", "problem", "severity", "fix"]))}, ["findings"]),
    "crosscheck": obj({"findings": arr(obj({
        "type": S, "criterion": S, "refs": arr(obj({"id": S, "quote": S}, ["id", "quote"])),
        "problem": S, "severity": SEVERITY, "fix": S,
    }, ["refs", "problem", "severity"]))}, ["findings"]),
    "gaps": obj({"findings": arr(obj({
        "type": S, "criterion": S, "refs": arr(obj({"id": S, "quote": S}, ["id", "quote"])),
        "problem": S, "severity": SEVERITY, "fix": S, "check": S,
    }, ["type", "refs", "problem", "severity", "fix"]))}, ["findings"]),
    "critic": obj({"verdicts": arr(obj({"n": N, "verdict": {"type": "STRING", "enum": ["keep", "downgrade", "drop", "merge"]},
                                        "into": N, "severity": SEVERITY, "reason": S}, ["n", "verdict"]))}, ["verdicts"]),
    "extras": obj({
        "coverage": arr(obj({"id": S, "status": {"type": "STRING", "enum": ["covered", "partial", "missing"]},
                             "quotes": arr(S), "comment": S}, ["id", "status"])),
        "synonyms": arr(obj({"terms": arr(S), "preferred": S, "problem": S}, ["terms"])),
    }),
}
