"""v12: параллельные вызовы (детерминированная сборка), граф трассировки с разрывами, коды выхода --gate."""
import json
import threading
import time
from pathlib import Path

import pytest

from req_review.parallel import pmap
from req_review.reader import read_document
from req_review.verify import quote_in

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "sample_requirements.md"


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")


def test_pmap_keeps_input_order_and_raises_first_error():
    def slow(x):
        time.sleep(0.02 * (5 - x))  # последние отвечают первыми
        return x * 10
    assert pmap(slow, range(5), n=5) == [0, 10, 20, 30, 40]

    def boom(x):
        if x in (1, 3):
            raise ValueError(f"e{x}")
        return x
    with pytest.raises(ValueError, match="e1"):
        pmap(boom, range(5), n=3)


def test_throttle_spaces_starts_across_threads():
    from req_review.llm import BaseLLM

    class Fake(BaseLLM):
        provider, model = "fake", "m"

        def __init__(self):
            super().__init__(min_interval=0.05, max_retries=0)
            self.starts, self.active, self.peak = [], 0, 0
            self.lk = threading.Lock()

        def _call(self, system, prompt, *, task, context):
            with self.lk:
                self.starts.append(time.monotonic())
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.1)
            with self.lk:
                self.active -= 1
            return "{}"

        def _cache_path(self, system, prompt):
            return None

    f = Fake()
    pmap(lambda i: f.generate_json("s", str(i)), range(6), n=6)
    gaps = [b - a for a, b in zip(sorted(f.starts), sorted(f.starts)[1:])]
    assert min(gaps) >= 0.045  # LLM_RPM / LLM_MIN_INTERVAL соблюдается и в параллельном режиме
    assert f.peak <= 3 and f.stats.calls == 6  # LLM_CONCURRENCY=3 по умолчанию


def _strip(d):
    for k in ("started", "duration_s", "stages", "critical_path", "log", "time_estimate"):
        d["passport"].pop(k, None)
    return d


def test_parallel_run_gives_same_report_json_as_sequential(tmp_path, mock_env, monkeypatch):
    from req_review.pipeline import Options, run

    monkeypatch.setenv("MOCK_LATENCY", "0.01")
    out = {}
    for c in ("1", "4"):
        monkeypatch.setenv("LLM_CONCURRENCY", c)
        p = tmp_path / c / "r.md"
        run(str(ROOT / "bench" / "real" / "notifications.md"), str(p),
            Options(profile="deep", html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
        out[c] = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    st = out["4"]["passport"]
    assert st["stages"] and st["critical_path"]["stages"] and st["critical_path"]["concurrency"] == 4
    assert any(x.get("parallel") for x in st["stages"])  # проверка требований ‖ проверка набора
    assert st["critical_path"]["seconds"] <= st["critical_path"]["stages_sum_s"]
    assert _strip(out["1"]) == _strip(out["4"])


API_TZ = """# Кэшбэк (выдуманный пример)

## Дизайн UI
Профиль → Кэшбэк. На экране видны переключатель, поле «Категория» и кнопка «Сохранить».

## Функциональные требования
- **К-1.** Клиент выбирает категорию кэшбэка и сохраняет выбор кнопкой «Сохранить».
- **К-2.** Кэшбэк начисляется 5 числа следующего месяца на карту клиента.

## Критерии приемки
| Условие | Действие | Результат |
| :--- | :--- | :--- |
| Категория не выбрана | К-1: выбрать «Кафе» и нажать «Сохранить» | Категория «Кафе» сохранена |

## REST API
| Поле | Значение |
| :--- | :--- |
| **REST type** | POST |
| **Request URL** | `/cashback/category` |

### Параметры запроса
| Parameter | Format | Description |
| :--- | :--- | :--- |
| `category` | string | Категория кэшбэка |
| `cardId` | — | Идентификатор карты |

### Статусы
**200.** Успешное сохранение выбранной категории.
```json
{"result":"OK"}
```
**409.**
"""


def _rv(tmp_path, text):
    from req_review.checker import ReqResult, ReviewResult
    from req_review.splitter import split_requirements

    p = tmp_path / "tz.md"
    p.write_text(text, encoding="utf-8")
    doc = read_document(p)
    sp = split_requirements(doc)
    return ReviewResult(doc=doc, split=sp, req_results=[ReqResult(req=r) for r in sp.requirements], set_findings=[],
                        dropped=[])


def test_traceability_graph_and_gaps_on_invented_tz(tmp_path):
    from req_review.traceability import build, to_json

    rv = _rv(tmp_path, API_TZ)
    rv.traceability = build(rv)
    tr = to_json(rv)
    types = tr["stats"]["nodes"]
    assert types.get("api_method") == 1 and types.get("api_param") == 2 and types.get("ui_field") == 2
    assert {"в документе", "выведено кодом"} <= set(tr["stats"]["edges"])
    edges = {(e["from"], e["to"], e["kind"]) for e in tr["edges"]}
    assert ("UI:категория", "P:req:category", "выведено кодом") in edges  # поле экрана ↔ параметр API
    acc = next(n["id"] for n in tr["nodes"] if n["type"] == "acceptance")
    k1 = next(n["id"] for n in tr["nodes"] if n["label"] == "К-1")
    assert (k1, acc, "в документе") in edges  # ID правила в строке приёмки
    gaps = {g["type"]: g for g in tr["gaps"]}
    assert set(gaps) == {"operation_without_method", "ui_field_without_param", "param_without_type",
                         "status_without_description", "rule_without_acceptance"}
    assert "чтения" in gaps["operation_without_method"]["problem"]  # «видны» — чтение, а метод только записи
    assert "cardId" in gaps["param_without_type"]["problem"] and "409" in gaps["status_without_description"]["problem"]
    assert "К-2" in gaps["rule_without_acceptance"]["problem"]
    for g in tr["gaps"]:  # каждый разрыв — замечание набора с дословной цитатой
        assert g["new"] and g["finding"].startswith("S-")
    for f in rv.set_findings:
        assert f.source == "трассировка (код)" and all(quote_in(r.quote, rv.doc.text) for r in f.refs)


def test_traceability_links_to_existing_finding_instead_of_duplicate(tmp_path):
    from req_review.checker import SetFinding, SetRef
    from req_review.traceability import build, to_json

    rv = _rv(tmp_path, API_TZ)
    rv.set_findings.append(SetFinding("gap", "set_complete", [SetRef("DOC", "REST type")],
                                      "В API нет метода чтения выбранной категории.", "critical", "", "LLM"))
    rv.traceability = build(rv)
    g = next(g for g in to_json(rv)["gaps"] if g["type"] == "operation_without_method")
    assert g["new"] is False and g["finding"] == "S-01"
    assert sum("метод" in f.problem and "чтения" in f.problem for f in rv.set_findings) == 1


def test_traceability_silent_without_api(tmp_path):
    from req_review.traceability import build

    rv = _rv(tmp_path, "# ТЗ\n\n## Требования\n- **Т-1.** Клиент видит баланс карты.\n")
    tr = build(rv)
    assert tr["gaps"] == [] and rv.set_findings == []


def test_report_has_traceability_section_and_json(tmp_path, mock_env):
    from req_review.pipeline import Options, run

    p = tmp_path / "r.md"
    run(str(ROOT / "bench" / "real" / "notifications.md"), str(p), Options(html=False, xlsx=False, jira=False, pdf=False),
        log=lambda m: None)
    md = p.read_text(encoding="utf-8")
    assert md.index("## 4.") < md.index("### Трассировка") < md.index("## 5.")
    tr = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))["traceability"]
    assert {"nodes", "edges", "gaps", "stats"} <= set(tr) and tr["gaps"]
    assert all(g["finding"] for g in tr["gaps"])


@pytest.mark.parametrize("gate,expected", [(False, 0), (True, 1)])
def test_gate_exit_code(tmp_path, mock_env, gate, expected):
    from req_review.cli import main

    args = [str(FIX), str(tmp_path / "r.md"), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira",
            "--no-html"] + (["--gate"] if gate else [])
    assert main(args) == expected  # в тестовом ТЗ есть критичные замечания → NO-GO


def test_gate_go_when_no_critical():
    from types import SimpleNamespace as NS

    from req_review.cli import gate_code

    ctx = NS(rv=NS(depth={"verdict": {"development": "с оговорками"}}, req_results=[], set_findings=[]))
    assert gate_code(ctx, True) == 0 and gate_code(ctx, False) == 0


def test_exit_codes_before_report(tmp_path, mock_env):
    from req_review.cli import main

    assert main([str(tmp_path / "нет.md"), str(tmp_path / "r.md"), "--quiet"]) == 2
    empty = tmp_path / "empty.md"
    empty.write_text("# Заметки\n\nПросто текст без требований.\n", encoding="utf-8")
    assert main([str(empty), str(tmp_path / "r2.md"), "--quiet"]) == 3
