"""RAG: нарезка, BM25, mock-эмбеддинги, база знаний, основания, длинные документы, Q&A (без сети и ключа)."""
import json
from pathlib import Path

import pytest

from req_review.rag.chunk import chunk_text
from req_review.rag.embed import Embedder, mock_embed
from req_review.rag.index import build_index, get_kb
from req_review.rag.lexical import BM25

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("RAG_CACHE_DIR", str(tmp_path / "cache"))


def test_chunks_keep_sections_and_metadata():
    text = "---\ntitle: T\nurl: http://x\n---\n\n## verifiable · 29148 §5.2.5 g) Проверяемость\nМожно проверить тестом.\n"
    ch = chunk_text(text, "s.md")
    assert ch[0].section.startswith("verifiable") and ch[0].meta["url"] == "http://x" and ch[0].title == "T"


def test_bm25_and_mock_embedding_find_relevant_fragment():
    docs = ["лимит перевода 500 000 тенге", "push-уведомление о статусе", "журнал аудита хранит события"]
    assert BM25(docs).search("уведомление push", 1)[0][0] == 1
    a, b = mock_embed("порог уведомления"), mock_embed("порог уведомления клиенту")
    assert sum(x * y for x, y in zip(a, b)) > 0.5
    idx = build_index([("d.md", "## A\n" + docs[0] + "\n\n## B\n" + docs[1], {})], Embedder("mock", "hash-256"))
    assert idx.vectors and idx.search("статус уведомления", 1)[0][0].section == "B"


def test_offline_fallback_without_embeddings():
    idx = build_index([("d.md", "## A\nлимит перевода\n\n## B\nжурнал аудита", {})], Embedder("none"))
    assert idx.vectors is None and idx.mode == "BM25" and idx.search("аудит", 1)[0][0].section == "B"


def test_kb_loads_and_is_switchable(monkeypatch):
    kb = get_kb()
    assert kb is not None and {c.meta["kind"] for c in kb.chunks} >= {"standards", "law_kz", "patterns"}
    monkeypatch.setenv("RAG", "off")
    assert get_kb() is None


def test_basis_quotes_exist_in_kb(tmp_path):
    from req_review.cli import main

    out = tmp_path / "r.md"
    assert main([str(FIX), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira"]) == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    root = Path(__file__).parent.parent
    bases = [b for r in data["requirements"] for f in r["findings"] for b in f.get("basis", [])]
    assert bases, "у замечаний должно быть основание из базы знаний"
    from req_review.verify import quote_in

    for b in bases:
        assert quote_in(b["quote"], (root / b["file"]).read_text(encoding="utf-8"))
    assert "Основание" in out.read_text(encoding="utf-8")
    assert data["schema_version"] == "2.3" and data["categories"] and data["coverage_map"]
    # шаблон правки соответствует категории требования: «надёжной» у NFR-02 не притягивает шаблон OTP
    from req_review.rag.basis import pattern_fits

    for r in data["requirements"]:
        if r.get("rewrite_pattern"):
            assert pattern_fits(r["rewrite_pattern"]["id"], r.get("category")), (r.get("doc_id"), r["rewrite_pattern"]["id"])
    nfr2 = next(r for r in data["requirements"] if r.get("doc_id") == "NFR-02")
    assert (nfr2.get("rewrite_pattern") or {}).get("id") != "otp"


def test_pattern_fits_category():
    from req_review.categories import classify
    from req_review.rag.basis import pattern_fits

    assert classify("Система должна быть надёжной и работать без сбоев.") == "availability"
    assert not pattern_fits("otp", "availability") and pattern_fits("sla", "availability")
    assert pattern_fits("otp", "security") and pattern_fits("otp", None) and pattern_fits("unknown", "data")


def test_run_without_rag_still_works(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("RAG", "off")
    out = tmp_path / "r.md"
    assert main([str(FIX), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira"]) == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert not any(f.get("basis") for r in data["requirements"] for f in r["findings"])


def test_long_document_uses_rag_context_and_keeps_far_contradiction(monkeypatch):
    """120 требований: запрос короче полного текста, а противоречие между первым и последним всё равно находится."""
    from req_review.mock_llm import MockLLM
    from req_review.pipeline import Options, review_document

    lines = ["# Длинный документ", "", "## Термины", "- Клиент — физическое лицо.", "", "## Требования"]
    lines.append("- **REQ-1.** После 3 неверных вводов кода подтверждения перевод блокируется на 30 минут.")
    verbs = ["формировать", "показывать", "сохранять", "проверять", "отправлять", "архивировать", "сверять"]
    objs = ["выписку по счёту", "историю переводов", "лимиты карты", "реквизиты получателя", "журнал входов",
            "квитанцию платежа", "настройки уведомлений", "курсы валют", "статус заявки", "список устройств", "тарифы"]
    tails = ["по запросу клиента", "раз в сутки", "при входе в приложение", "после каждой операции", "для оператора колл-центра"]
    for i in range(2, 120):
        lines.append(f"- **REQ-{i}.** Система должна {verbs[i % 7]} {objs[i % 11]} {tails[i % 5]} в разделе {i}.")
    lines.append("- **REQ-120.** После 5 неверных вводов кода подтверждения перевод блокируется на 30 минут.")
    p = Path(__file__).parent / "_long_tmp.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    try:
        monkeypatch.setenv("RAG_CONTEXT", "off")
        full = review_document(p, MockLLM(), Options(profile="fast", domain="none"), log=lambda m: None)
        monkeypatch.setenv("RAG_CONTEXT", "auto")
        monkeypatch.setenv("RAG_CONTEXT_THRESHOLD", "5000")
        rv = review_document(p, MockLLM(), Options(profile="fast", domain="none"), log=lambda m: None)
        st, st_full = rv.doc._ctx_stats, full.doc._ctx_stats
        assert st["mode"] == "rag" and st_full["mode"] == "full"
        assert sum(st["prompt_chars"]) < 0.8 * sum(st_full["prompt_chars"])  # запросы заметно короче
        assert any(f.kind == "contradiction" and {r.req_id for r in f.refs} == {"R-001", "R-120"} for f in rv.set_findings)
    finally:
        p.unlink()


def test_answer_with_sources_is_grounded():
    from req_review.rag.qa import answer_with_sources

    report = {"requirements": [
        {"rid": "R-001", "doc_id": "FR-02", "text": "Система должна быстро проверять наличие получателя.", "line_start": 20,
         "findings": [{"severity": "critical", "problem": "«быстро» не измеримо"}]}]}
    doc = "# Документ\nСистема должна быстро проверять наличие получателя.\n"
    res = answer_with_sources("Почему FR-02 критичное?", report, doc, get_kb())
    assert res["sources"][0]["ref"] == "R-001" and "не измеримо" in res["answer"]
    assert all(s["kind"] != "requirement" or s["quote"] in doc for s in res["sources"])
