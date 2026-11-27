"""v13+ A9: генератор мутаций — эталон, который растёт сам.

Запуск:  python bench/mutate.py --build [--seed 13] [--per-base 4]  — варианты в bench/mutations/ + manifest.json
         python bench/mutate.py [--profile fast] [--only ТИП …] [--limit N] [--write]  — прогон агента и строгий счёт

База — чистые ТЗ bench/clean/*.md (в них дефектов нет, см. bench/clean/README.md). В каждый вариант вносится один
дефект известного типа (или два — комбинация) в известное место; эталон (тип, строки-опоры, критерии, ожидаемая
серьёзность) пишется автоматически. Типы — по свойствам ISO/IEC/IEEE 29148:
  vague        — срок с числом заменён размытым «в разумные сроки»          (проверяемость)
  units        — у суммы пропала единица («500 000» без «тенге»)            (однозначность)
  tbd          — значение заменено на «TBD»                                  (полнота)
  andor        — «или» заменено на «и/или»                                   (однозначность)
  open_list    — перечень открыт «и т. д.»                                   (полнота)
  boundary     — из диапазона убрано «включительно»                          (однозначность границы)
  contradiction — второе требование задаёт то же правило другим числом       (непротиворечивость, обе стороны)
  status       — два HTTP-статуса на один и тот же случай (документы с API)  (непротиворечивость, обе стороны)
Счёт строгий: дефект найден, только если цитата замечания по нужному критерию лежит на строке-опоре
(для противоречия — цитаты покрывают обе строки). Интервалы — bench/gold_score.py::bootstrap.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "mutations"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

ROW = re.compile(r"^\|\s*([A-ZА-ЯЁ]{1,5}-\d{2})\s*\|(.+)\|\s*([^|]*)\|\s*$")
_TIME = re.compile(r"не (?:позднее|дольше|более) (\d[\d  ,]*\s*(?:секунд\w*|минут\w*|час\w*|рабочих дней|дней))"
                   r"(?: для \d+ % \w+)?")
_MONEY = re.compile(r"(\d[\d  ]*\d)\s+(тенге|₸)")
_RANGE_INC = re.compile(r"(от [\d  ]+ до [\d  ]+)(?: тенге| ₸)? включительно")
_NUM_UNIT = re.compile(r"(\d[\d  ]*)(\s*)(секунд\w*|минут\w*|час\w*|дней|месяц\w*|тенге|₸|%)")
_SKIP_SECTION = re.compile(r"критери|ошибк|ответ|событи|термин|қабылдау|қате", re.I)

VAGUE = ["в разумные сроки", "оперативно", "без заметной задержки", "как можно быстрее", "в приемлемое время"]
CRIT = {"vague": ["verifiable", "unambiguous"], "units": ["unambiguous", "complete", "correct", "verifiable"],
        "tbd": ["complete"], "andor": ["unambiguous"], "open_list": ["complete"], "boundary": ["unambiguous", "verifiable"],
        "contradiction": ["set_consistent"], "status": ["set_consistent"]}
SEV = {"vague": "major", "units": "major", "tbd": "major", "andor": "major", "open_list": "major", "boundary": "major",
       "contradiction": "critical", "status": "critical"}
TYPES = list(CRIT)


def _rows(lines: list[str]) -> list[tuple[int, str, str]]:
    """(индекс строки, ID, текст требования) — строки таблиц требований (не приёмка, не ошибки, не API)."""
    out, sec = [], ""
    for i, ln in enumerate(lines):
        h = re.match(r"^#{1,6}\s+(.+)", ln)
        if h:
            sec = h.group(1)
            continue
        m = ROW.match(ln)
        if m and not _SKIP_SECTION.search(sec):
            out.append((i, m.group(1), m.group(2).strip()))
    return out


def _sub_row(lines, i, old, new):
    assert old in lines[i], (lines[i], old)
    lines[i] = lines[i].replace(old, new, 1)


def op(kind: str, lines: list[str], rng: random.Random, used: set[int]) -> dict | None:
    """Внести дефект kind в lines (на месте). Возвращает запись эталона или None, если в документе нет подходящего места."""
    rows = [r for r in _rows(lines) if r[0] not in used]
    rng.shuffle(rows)
    for i, rid, text in rows:
        if kind == "vague" and (m := _TIME.search(text)):
            _sub_row(lines, i, m.group(0), rng.choice(VAGUE))
        elif kind == "units" and (m := _MONEY.search(text)) and not _RANGE_INC.search(text):
            _sub_row(lines, i, m.group(0), m.group(1))
        elif kind == "tbd" and (m := _NUM_UNIT.search(text)):
            _sub_row(lines, i, m.group(0), "TBD")
        elif kind == "andor" and " или " in text:
            _sub_row(lines, i, " или ", " и/или ")
        elif kind == "open_list" and re.search(r"\w, [^|]*? и \w", text):
            m = re.search(r"(\w+, [^|.;]*? и )(\w[\w-]*)", text)
            _sub_row(lines, i, m.group(0), m.group(0) + " т. д.")
            lines[i] = lines[i].replace(" и " + m.group(2) + " т. д.", ", " + m.group(2) + " и т. д.", 1)
        elif kind == "boundary" and (m := _RANGE_INC.search(text)):
            _sub_row(lines, i, " включительно", "")
        elif kind == "contradiction" and (m := _NUM_UNIT.search(text)) and not rid.endswith("-99"):
            num = re.sub(r"[  ]", "", m.group(1))
            if not num.isdigit():
                continue
            new_num = str(int(num) * 2 if int(num) < 1000 else int(num) // 2)
            new_text = text.replace(m.group(0), new_num + m.group(2) + m.group(3), 1)
            prefix = rid.rsplit("-", 1)[0]
            new_line = f"| {prefix}-99 | {new_text} | Высокий |"
            j = max(r[0] for r in _rows(lines) if r[1].startswith(prefix + "-")) + 1
            lines.insert(j, new_line)
            used.update({i, j})
            return {"type": kind, "anchors": [i + 1, j + 1], "ids": [rid, f"{prefix}-99"], "criteria": CRIT[kind],
                    "severity": SEV[kind]}
        else:
            continue
        used.add(i)
        return {"type": kind, "anchors": [i + 1], "ids": [rid], "criteria": CRIT[kind], "severity": SEV[kind]}
    if kind == "status":  # таблица кодов ответа API: тот же случай под другим кодом
        sec = ""
        for i, ln in enumerate(lines):
            h = re.match(r"^#{1,6}\s+(.+)", ln)
            if h:
                sec = h.group(1)
            m = re.match(r"^\|\s*(4\d\d)\s*\|([^|]+)\|", ln)
            if m and re.search(r"ответ|api", sec, re.I) and i not in used:
                other = "409" if m.group(1) != "409" else "422"
                new = ln.replace(f"| {m.group(1)} |", f"| {other} |", 1)
                lines.insert(i + 1, new)
                used.update({i, i + 1})
                return {"type": kind, "anchors": [i + 1, i + 2], "ids": [m.group(1), other], "criteria": CRIT[kind],
                        "severity": SEV[kind]}
    return None


def build(seed: int = 13, per_base: int = 4) -> dict:
    """Для каждой базы: per_base одиночных мутаций разных типов + 1 комбинация из двух. Детерминировано при seed."""
    rng = random.Random(seed)
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    manifest = {"seed": seed, "per_base": per_base, "variants": []}
    bases = sorted(p for p in (HERE / "clean").glob("*.md") if p.name != "README.md")
    for base in bases:
        src = base.read_text(encoding="utf-8").splitlines()
        kk = base.stem.endswith("_kk")
        kinds = [k for k in TYPES if not (kk and k in ("vague", "andor", "open_list", "tbd"))]
        rng.shuffle(kinds)
        plans = [[k] for k in kinds[:per_base]] + [kinds[per_base:per_base + 2] or kinds[:2]]
        for n, plan in enumerate(plans, 1):
            lines = list(src)
            used: set[int] = set()
            defects = []
            for k in plan:
                d = op(k, lines, rng, used)
                if d:
                    defects.append(d)
            if not defects:
                continue
            # вставки строк сдвигают номера: опоры пересчитываются по тексту строк
            text = "\n".join(lines) + "\n"
            text = text.replace("Вымышленный документ без внесённых дефектов", "Вымышленный документ с внесённым дефектом "
                                "(генератор мутаций bench/mutate.py)", 1)
            name = f"{base.stem}__{n:02d}_{'+'.join(d['type'] for d in defects)}"
            (OUT / f"{name}.md").write_text(text, encoding="utf-8")
            final = text.splitlines()
            for d in defects:
                d["anchor_text"] = [final[a - 1] for a in d["anchors"]]
            manifest["variants"].append({"name": name, "base": base.stem, "file": f"bench/mutations/{name}.md",
                                         "defects": defects})
    manifest["total_defects"] = sum(len(v["defects"]) for v in manifest["variants"])
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def found(rv, d: dict) -> bool:
    """Строгий счёт: замечание по одному из критериев, цитата которого лежит на строке-опоре (для двух опор — на обеих)."""
    from req_review.verify import norm

    anchors = [norm(t) for t in d["anchor_text"]]
    lines = {ln.lineno: norm(ln.text) for ln in rv.doc.lines}

    def on(q: str, a: str) -> bool:
        q = norm(q)
        return bool(q) and q in a

    # строки-опоры в разобранном документе (номера могут сдвинуться при чтении) — ищем по тексту
    for rr in rv.req_results:
        for f in rr.findings:
            if f.criterion in d["criteria"] and len(anchors) == 1 and on(f.quote, anchors[0]):
                return True
    for f in rv.set_findings:
        if f.criterion not in d["criteria"] and not (d["type"] in ("vague", "units", "tbd", "open_list", "boundary", "andor")
                                                     and f.criterion.startswith("set_")):
            continue
        covered = [any(on(r.quote, a) for r in f.refs) for a in anchors]
        if all(covered) and (f.criterion in d["criteria"] or len(anchors) == 1):
            return True
    del lines
    return False


def evaluate(manifest: dict, llm, profile: str = "fast", only: list[str] | None = None, limit: int | None = None,
             log=print) -> dict:
    from gold_score import bootstrap

    from req_review.pipeline import Options, review_document

    rows = []
    vs = [v for v in manifest["variants"] if not only or any(d["type"] in only for d in v["defects"])][:limit]
    for v in vs:
        rv = review_document(ROOT / v["file"], llm, Options(profile=profile, domain="fintech"), log=lambda m: None)
        for d in v["defects"]:
            rows.append({"variant": v["name"], "type": d["type"], "found": found(rv, d), "combo": len(v["defects"]) > 1})
        log(f"{v['name']}: " + ", ".join(f"{d['type']} {'✅' if r['found'] else '—'}"
                                         for d, r in zip(v["defects"], rows[-len(v['defects']):])))
    by_type: dict[str, list[int]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(int(r["found"]))
    flat = [int(r["found"]) for r in rows]
    return {"model": getattr(llm, "label", ""), "profile": profile, "variants": len(vs), "defects": len(rows),
            "found": sum(flat), "recall": sum(flat) / len(flat) if flat else 0.0, "recall_ci": bootstrap(flat),
            "by_type": {k: {"found": sum(v), "total": len(v)} for k, v in sorted(by_type.items())},
            "combo": {"found": sum(int(r["found"]) for r in rows if r["combo"]), "total": sum(r["combo"] for r in rows)},
            "rows": rows}


def md(res: dict) -> str:
    pct = lambda x: f"{100 * x:.0f} %"  # noqa: E731
    lo, hi = res["recall_ci"]
    lines = [f"## Корпус мутаций (v13+, профиль {res['profile']})", "",
             f"*Модель:* {res['model']}. Команда: `python bench/mutate.py --build && python bench/mutate.py`. Счёт строгий: "
             "цитата замечания должна лежать на строке-опоре (для противоречия — на обеих).", "",
             f"Найдено **{res['found']} из {res['defects']}** ({pct(res['recall'])}, 95 % интервал {pct(lo)}–{pct(hi)}) "
             f"в {res['variants']} вариантах; в комбинациях из двух дефектов — {res['combo']['found']} из {res['combo']['total']}.",
             "", "| Тип дефекта | Найдено |", "|---|---|"]
    for k, v in res["by_type"].items():
        lines.append(f"| {k} | {v['found']} из {v['total']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python bench/mutate.py")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--per-base", type=int, default=4)
    ap.add_argument("--profile", default="fast")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.build or not (OUT / "manifest.json").exists():
        m = build(a.seed, a.per_base)
        print(f"вариантов {len(m['variants'])}, дефектов {m['total_defects']} → bench/mutations/")
        if a.build:
            return 0
    load_dotenv(ROOT / ".env")
    from req_review.llm import build_llm_from_env

    res = evaluate(json.loads((OUT / "manifest.json").read_text(encoding="utf-8")), build_llm_from_env(), a.profile,
                   a.only, a.limit)
    text = md(res)
    print(text)
    if a.write:
        (HERE / f"mutations_{a.profile}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
