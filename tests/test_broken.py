"""v9: «сломанные» входные файлы → понятное сообщение по-русски, что сделать, код возврата, без трейсбека;
журнал прогона <отчёт>.log рядом с отчётом — без ключей и без полного текста документа."""
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BROKEN = ROOT / "tests" / "fixtures" / "broken"
CASES = {  # файл → (код возврата, фрагмент сообщения, фрагмент подсказки)
    "empty.md": (3, "пустой", "выбран нужный файл"),
    "encrypted.pdf": (3, "защищён паролем", "Сохранить как PDF"),
    "scan.pdf": (3, "скан без текстового слоя", "OCR"),
    "fake.docx": (3, "не является документом Word", "Сохранить как"),
    "old.doc": (2, "старый Word", "сохраните как .docx"),
    "binary.md": (3, "двоичные данные", ".md или .txt"),
    "noreqs.md": (3, "не найдено ни одного требования", "ID (FR-01"),
}


@pytest.fixture()
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")


@pytest.mark.parametrize("name", sorted(CASES))
def test_broken_file_gives_clear_message_and_exit_code(name, tmp_path, mock_env, capsys):
    from req_review.cli import main

    code, msg, hint = CASES[name]
    rc = main([str(BROKEN / name), str(tmp_path / "r.md"), "--quiet"])
    out = capsys.readouterr()
    text = out.out + out.err
    assert rc == code, text
    assert msg in text and hint in text and "Что сделать:" in text
    assert "Traceback" not in text and "Exception" not in text


def test_old_doc_renamed_to_docx(tmp_path, mock_env, capsys):
    from req_review.cli import main

    p = tmp_path / "renamed.docx"
    shutil.copy(BROKEN / "old.doc", p)
    rc = main([str(p), str(tmp_path / "r.md"), "--quiet"])
    text = "".join(capsys.readouterr())
    assert rc == 3 and "старого формата Word (.doc)" in text and "Traceback" not in text


def test_studio_error_event_has_hint(tmp_path, mock_env):
    """Studio: ошибка «сломанного» файла приходит событием error с code и подсказкой (экран ошибки в UI)."""
    from req_review.errors import DocumentError
    from req_review.reader import read_document

    with pytest.raises(DocumentError) as e:
        read_document(BROKEN / "scan.pdf")
    assert e.value.kind == "document" and e.value.code == 3 and "OCR" in e.value.hint
    src = (ROOT / "req_review" / "web" / "app.py").read_text(encoding="utf-8")
    assert 'job.push("error", msg=e.message, code=e.kind, hint=' in src


def test_run_log_written_without_keys_and_document_text(tmp_path, mock_env, monkeypatch):
    from req_review.pipeline import Options, run

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKE-not-real-42")
    doc = ROOT / "tests" / "fixtures" / "sample_requirements.md"
    out = tmp_path / "report.md"
    run(str(doc), str(out), Options(html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    log = (tmp_path / "report.log").read_text(encoding="utf-8")
    assert "== этап: Чтение" in log and "== этап: Отчёты" in log and "--- длительность этапов ---" in log
    assert "обращений к модели:" in log and "из кэша:" in log and "повторов:" in log and "переключения моделей:" in log
    assert "отброшено замечаний с неподтверждённой цитатой:" in log
    assert "AIza" not in log and "not-a-real-key" not in log
    body = [ln for ln in doc.read_text(encoding="utf-8").splitlines() if len(ln) > 80]
    assert not any(ln in log for ln in body)  # полного текста документа в журнале нет
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["passport"]["log"] == "report.log"
    assert "| Журнал прогона | `report.log`" in out.read_text(encoding="utf-8")


def test_run_log_written_on_error(tmp_path, mock_env):
    from req_review.errors import DocumentError
    from req_review.pipeline import Options, run

    with pytest.raises(DocumentError):
        run(str(BROKEN / "noreqs.md"), str(tmp_path / "r.md"), Options(), log=lambda m: None)
    log = (tmp_path / "r.log").read_text(encoding="utf-8")
    assert "ОШИБКА: В документе не найдено ни одного требования" in log


def test_redact_removes_key_like_strings(monkeypatch):
    from req_review.runlog import redact

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret-value-123456")
    assert "***" in redact("Bearer abcdefghijklmnop") and "or-secret" not in redact("ключ or-secret-value-123456")
