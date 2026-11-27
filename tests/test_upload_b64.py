"""Загрузка документа в base64 (Studio): фильтр хостинга (Cloudflare перед Render) блокирует запросы, в тексте которых
есть пример «curl … -H "Authorization: Bearer …"» — обычное содержимое ТЗ на API. Закодированный файл фильтр не трогает;
сервер раскодирует его и проверяет так же, как обычную загрузку. Модель — mock, сеть не нужна."""
import base64
import hashlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from req_review.web import app as webapp  # noqa: E402

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "sample_requirements.md"
# фрагмент, на котором срабатывал фильтр хостинга (выдуманный пример, не документ организаторов)
CURL = '\n| **CURL** | `curl -G "$BASE/limits/save" -H "Authorization: Bearer $TOKEN" --data \'id=1&amount=500\'` |\n'


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("STUDIO_DEMO_DELAY", "0")
    monkeypatch.setenv("REQLENS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("RAG_EMBED", "off")
    return TestClient(webapp.app)


def _b64(data: bytes, name="req.md", **form):
    return {"files": {"file_b64": ("document.b64", base64.b64encode(data), "text/plain")},
            "data": {"filename": name, **form}}


def test_project_run_from_base64(client):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "base64"}).json()["id"]
    data = FIX.read_bytes() + CURL.encode()
    r = c.post(f"/api/v1/projects/{pid}/runs", **_b64(data, mode="rules"))
    assert r.status_code in (200, 202), r.text
    run = r.json()["run"]
    assert run["doc_name"] == "req.md"
    assert run["doc_hash"] == hashlib.sha256(data).hexdigest()  # раскодировано байт в байт


def test_base64_upload_keeps_all_checks(client):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "проверки"}).json()["id"]
    bad = c.post(f"/api/v1/projects/{pid}/runs", files={"file_b64": ("d.b64", b"%%% not base64 %%%", "text/plain")},
                 data={"filename": "req.md"})
    assert bad.status_code == 400 and "повреждён" in bad.json()["error"]["message"]
    exe = c.post(f"/api/v1/projects/{pid}/runs", **_b64(b"MZ\x90\x00", name="virus.exe"))
    assert exe.status_code == 400 and exe.json()["error"]["code"] == "unsupported"
    empty = c.post(f"/api/v1/projects/{pid}/runs", **_b64(b"   \n", name="doc.md"))
    assert empty.json()["error"]["code"] == "empty"
    big = c.post(f"/api/v1/projects/{pid}/runs", **_b64(b"a" * (10 * 1024 * 1024 + 1), name="doc.md"))
    assert big.status_code == 413
    none = c.post(f"/api/v1/projects/{pid}/runs", data={"mode": "rules"})
    assert none.status_code == 400 and none.json()["error"]["message"] == "Загрузите файл документа"
    # обычная загрузка работает как раньше
    plain = c.post(f"/api/v1/projects/{pid}/runs", files={"file": ("req.md", FIX.read_bytes(), "text/markdown")},
                   data={"mode": "rules"})
    assert plain.status_code in (200, 202)


def test_legacy_review_accepts_base64(client):
    r = client.post("/api/review", **_b64(FIX.read_bytes()))
    assert r.status_code == 200 and r.json()["job"]


def test_studio_sends_base64_and_explains_host_errors():
    s = (ROOT / "req_review" / "ui" / "templates" / "studio.html.j2").read_text(encoding="utf-8")
    assert 'fd.append("file",f)' not in s and "fileForm(f)" in s and '"file_b64"' in s
    assert "hostErr(r.status)" in s and '||"Ошибка"' not in s  # ответ хостинга без JSON — понятный текст, не «Ошибка»


def test_project_cards_translated_to_kazakh():
    s = (ROOT / "req_review" / "ui" / "templates" / "studio.html.j2").read_text(encoding="utf-8")
    kk = s[s.index("const KK={"):s.index("function tr(s)")]
    for ru in ("пока без проверок", "загрузите первую версию", "Новая версия · сравнение с прошлой"):
        assert f'"{ru}":"' in kk, ru
    assert r'[/^версий: (\d+) · (.+)$/,"нұсқалар: $1 · $2"]' in s
    assert r'[/^критичных: (\d+)$/,"критикалық: $1"]' in s
