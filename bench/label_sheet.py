"""v15: ручная разметка точности — офлайн-лист с текстом требования рядом и перенос вердиктов людей по ключу строки.

Запуск:  python bench/label_sheet.py                          — собрать bench/label_sheet.html (замечания из
                                                                bench/unmatched.md) и bench/real/human_check.html
                                                                (находки отчёта для сдачи из bench/real/human_check.md)
         python bench/gold_score.py --labels labels.json      — перенести вердикты из «Сохранить» в .md по ключу
         python bench/gold_score.py --labels a.json b.json    — разметка двух человек (расхождения — показываются)

В листе для каждого замечания: документ, требование, строка документа с соседними строками (номера строк — как в
извлечённом тексте), цитата и формулировка агента, кнопки вердикта и комментарий. Замечания к одному месту документа
стоят рядом. Агент меток не ставит: в листе ничего не выбрано, «Сохранить» скачивает только то, что отметил человек,
а перенос отказывается принимать файл без имени разметчика или с одинаковыми метками на всех строках (--force — если
так и задумано).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

KEY = re.compile(r"[0-9a-f]{10}")
REAL_DOC = HERE / "real" / "notifications.md"
REPORT = ROOT / "reports" / "requirements-report.json"
SHEETS = {
    "unmatched": {"md": HERE / "unmatched.md", "html": HERE / "label_sheet.html", "download": "labels.json",
                  "verdicts": ["настоящий", "ложное", "спорно"],
                  "title": "Разметка точности: замечания, не совпавшие с эталоном",
                  "hint": "«настоящий» — дефект действительно есть в тексте (эталон его просто не содержит); «ложное» — "
                          "дефекта нет или он надуман; «спорно» — зависит от контекста, которого в документе нет."},
    "human_check": {"md": HERE / "real" / "human_check.md", "html": HERE / "real" / "human_check.html",
                    "download": "human_labels.json", "verdicts": ["да", "нет", "спорно"],
                    "title": "Ручная проверка находок отчёта для сдачи",
                    "hint": "«да» — настоящий дефект требований; «нет» — проблемы нет или она надумана; «спорно» — "
                            "зависит от контекста. Судите по тексту документа, не по вердикту модели."},
}
MIN_SAME = 10  # столько одинаковых меток подряд на всех строках — повод остановиться и спросить


# ---------------------------------------------------------------- таблицы .md


def md_rows(path: Path) -> list[list[str]]:
    """Строки таблицы с ключом в первой колонке: список ячеек (без крайних «|»)."""
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and KEY.fullmatch(cells[0]):
                out.append(cells)
    return out


def _verdict_of(cell: str, verdicts: list[str]) -> str:
    v = cell.strip().lower().replace("ё", "е")
    return next((w for w in verdicts if v.startswith(w.replace("ё", "е"))), "")


def _cell(verdict: str, comment: str) -> str:
    comment = " ".join(str(comment or "").split()).replace("|", "/").strip()
    return f"{verdict}: {comment}" if comment else verdict


# ---------------------------------------------------------------- текст документов


def _doc_lines(path: Path) -> list[str]:
    from req_review.reader import read_document

    try:
        return [ln.text for ln in read_document(path).lines]
    except Exception:  # документа нет (не собран bench/inject.py) — лист без контекста, но с формулировкой агента
        return []


def _norm(s: str) -> str:
    """Для поиска цитаты: без markdown (`, **, | таблиц), ё → е, пробелы схлопнуты, нижний регистр."""
    for a, b in (("ё", "е"), ("Ё", "Е"), ("**", ""), ("`", ""), ("|", " ")):
        s = s.replace(a, b)
    return " ".join(s.split()).lower()


def locate(lines: list[str], where: str, quote: str) -> list[int]:
    """Индексы строк документа, к которым относится замечание: по ID требований из «Где», иначе — по цитате."""
    hits: list[int] = []
    for rid in [w.strip() for w in where.split(",")]:
        if not rid or rid in ("DOC",) or re.fullmatch(r"[RS]-\d+", rid):
            continue  # R-xxx / S-xx — внутренние номера отчёта, в тексте документа их нет
        pat = re.compile(rf"(?<![\w-]){re.escape(rid)}(?![\w-])")
        i = next((n for n, ln in enumerate(lines) if pat.search(ln)), None)
        if i is not None and i not in hits:
            hits.append(i)
    if not hits:
        normed = [_norm(ln) for ln in lines]
        for part in [q for q in quote.split(" / ") if q.strip()][:3]:
            q = _norm(part)
            for size in (len(q), 60, 30):
                needle = q[:size]
                if len(needle) < 6:
                    break
                i = next((n for n, ln in enumerate(normed) if needle in ln), None)
                if i is not None:
                    if i not in hits:
                        hits.append(i)
                    break
    return hits[:3]


def context(lines: list[str], hits: list[int], around: int = 2) -> list[list]:
    """[[номер строки, текст, это та самая строка?], …] — найденные строки ± around соседних, без дублей."""
    keep: dict[int, bool] = {}
    for h in hits:
        for n in range(max(0, h - around), min(len(lines), h + around + 1)):
            keep[n] = keep.get(n, False) or n == h
    return [[n + 1, lines[n][:600], keep[n]] for n in sorted(keep) if lines[n].strip() or keep[n]]


# ---------------------------------------------------------------- данные листов


def _unmatched_items() -> dict[str, dict]:
    import gold_score

    items = []
    dp = HERE / "results_detail.json"
    if dp.exists():
        items += json.loads(dp.read_text(encoding="utf-8"))["items"]
    if REPORT.exists():
        items += gold_score.real_items(json.loads(REPORT.read_text(encoding="utf-8")))[1]
    return {gold_score._key(it["doc"], it["where"], it["problem"]): it for it in items}


def _doc_path(doc: str) -> Path | None:
    if doc == "organizers":
        return REAL_DOC
    gt = HERE / "ground_truth.json"
    if gt.exists():
        f = json.loads(gt.read_text(encoding="utf-8"))["documents"].get(doc, {}).get("file")
        return ROOT / f if f else None
    return None


def build_items(sheet: str) -> list[dict]:
    """Замечания листа в порядке документа: строки .md + полные формулировки и цитаты из прогона + контекст."""
    rows = md_rows(SHEETS[sheet]["md"])
    out = []
    if sheet == "unmatched":
        full = _unmatched_items()
        texts: dict[str, list[str]] = {}
        for cells in rows:
            key, doc, where = cells[0], cells[1], cells[2]
            it = full.get(key, {})
            if doc not in texts:
                p = _doc_path(doc)
                texts[doc] = _doc_lines(p) if p else []
            hits = locate(texts[doc], where, it.get("quote", ""))
            out.append({"key": key, "doc": doc, "where": where, "criterion": cells[3], "severity": cells[4],
                        "problem": it.get("problem") or cells[5], "quote": it.get("quote", ""), "req": "",
                        "anchor": hits[0] + 1 if hits else 0, "ctx": context(texts[doc], hits)})
    else:
        from verify_findings import items_of

        full = {it["key"]: it for it in items_of(json.loads(REPORT.read_text(encoding="utf-8")))} if REPORT.exists() else {}
        lines = _doc_lines(REAL_DOC)
        for cells in rows:
            key, where = cells[0], cells[1]
            it = full.get(key, {})
            hits = locate(lines, where, it.get("quote", ""))
            out.append({"key": key, "doc": "organizers", "where": where, "criterion": "", "severity": cells[2],
                        "problem": it.get("problem") or cells[3], "quote": it.get("quote", ""),
                        "req": it.get("text", ""), "anchor": hits[0] + 1 if hits else 0, "ctx": context(lines, hits)})
    order = {d: i for i, d in enumerate(dict.fromkeys(it["doc"] for it in out))}
    for it in out:  # замечания к одной строке документа — одна группа
        it["group"] = f"{it['doc']}#{it['anchor']}" if it["anchor"] else f"{it['doc']}|{it['where']}"
    out.sort(key=lambda it: (order[it["doc"]], it["anchor"] or 10 ** 6, it["where"]))
    return out


def build(sheet: str, out: Path | None = None) -> Path:
    cfg = SHEETS[sheet]
    items = build_items(sheet)
    data = {"sheet": sheet, "source": cfg["md"].relative_to(ROOT).as_posix(), "verdicts": cfg["verdicts"],
            "download": cfg["download"], "title": cfg["title"], "hint": cfg["hint"], "items": items,
            "id": hashlib.sha1("|".join(it["key"] for it in items).encode()).hexdigest()[:12]}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("__TITLE__", cfg["title"]).replace("__DATA__", payload)
    path = out or cfg["html"]
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------- перенос вердиктов


class LabelsError(ValueError):
    pass


def apply_labels(labels: dict, md_path: Path | None = None, overwrite: bool = False, force: bool = False) -> dict:
    """Вписать вердикты людей в .md по ключу строки. Пустой файл меток ничего не меняет. Возвращает сводку."""
    sheet = labels.get("sheet", "unmatched")
    if sheet not in SHEETS:
        raise LabelsError(f"неизвестный лист «{sheet}» — ожидаю {', '.join(SHEETS)}")
    cfg = SHEETS[sheet]
    path = md_path or cfg["md"]
    marks = {k: v for k, v in (labels.get("labels") or {}).items() if isinstance(v, dict) and v.get("verdict")}
    bad = sorted({v["verdict"] for v in marks.values()} - set(cfg["verdicts"]))
    if bad:
        raise LabelsError(f"вердикты {bad} не из списка {cfg['verdicts']} (лист {sheet})")
    rep = {"sheet": sheet, "md": path, "applied": 0, "updated": 0, "same": 0, "conflicts": [], "unknown": [],
           "labels": len(marks)}
    if not marks:
        return rep
    if not force and not str(labels.get("annotator", "")).strip():
        raise LabelsError("в файле меток не указано, кто размечал (поле «Кто размечает» в листе) — "
                          "вердикты переносятся только от человека; --force, если это так и задумано")
    if not force and len(marks) >= MIN_SAME and len({v["verdict"] for v in marks.values()}) == 1:
        raise LabelsError(f"все {len(marks)} меток одинаковые («{next(iter(marks.values()))['verdict']}») — "
                          "похоже не на ручную разметку; проверьте файл, --force — если так и есть")
    text = path.read_text(encoding="utf-8")
    seen = set()
    lines = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        key = cells[0] if len(cells) >= 2 and KEY.fullmatch(cells[0]) else None
        if key and key in marks:
            seen.add(key)
            new = _cell(marks[key]["verdict"], marks[key].get("comment", ""))
            old = cells[-1]
            if old == new:
                rep["same"] += 1
            elif not old:
                cells[-1] = new
                rep["applied"] += 1
            elif _verdict_of(old, cfg["verdicts"]) == marks[key]["verdict"] or overwrite:
                cells[-1] = new
                rep["updated"] += 1
            else:
                rep["conflicts"].append((key, old, new))
            line = "| " + " | ".join(cells) + " |"
        lines.append(line)
    rep["unknown"] = sorted(set(marks) - seen)
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return rep


def apply_files(paths: list[Path], overwrite: bool = False, force: bool = False, log=print) -> int:
    code = 0
    for p in paths:
        try:
            labels = json.loads(Path(p).read_text(encoding="utf-8"))
            rep = apply_labels(labels, overwrite=overwrite, force=force)
        except (OSError, json.JSONDecodeError, LabelsError) as e:
            log(f"{p}: не перенесено — {e}")
            code = 1
            continue
        who = labels.get("annotator", "") or "—"
        md = rep["md"].relative_to(ROOT).as_posix() if rep["md"].is_relative_to(ROOT) else rep["md"]
        log(f"{p} → {md} (размечал: {who}): меток {rep['labels']}, вписано "
            f"{rep['applied']}, уточнено {rep['updated']}, без изменений {rep['same']}, "
            f"расхождений {len(rep['conflicts'])}, нет такой строки {len(rep['unknown'])}")
        for key, old, new in rep["conflicts"]:
            log(f"  расхождение {key}: в файле «{old}», в метках «{new}» — оставлено как было (--overwrite — заменить)")
        for key in rep["unknown"][:10]:
            log(f"  нет строки с ключом {key} (файл пересобран после разметки?)")
    if code == 0:
        log("Дальше: python bench/gold_score.py --write — пересчитать точность, RESULTS.md и строку README.")
    return code


# ---------------------------------------------------------------- HTML


TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — ReqLens</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#14172b;--mute:#5b6180;--line:#dfe2ee;--hl:#fff4c2;--acc:#3b4cb6;
--yes:#1c8a5a;--no:#c0392b;--mid:#b7791f;--sel:#eef0fb}
@media (prefers-color-scheme:dark){:root{--bg:#0b0d1a;--card:#151830;--ink:#e8eaf6;--mute:#9aa0c3;--line:#2a2f52;
--hl:#4a3f12;--acc:#8e9bff;--yes:#3ccf8e;--no:#ff7a6b;--mid:#f0b453;--sel:#1f2346}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 20px}
.bar{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;max-width:1100px;margin:0 auto}
h1{font-size:17px;margin:0 12px 0 0}
.prog{font-weight:600}.prog small{color:var(--mute);font-weight:400}
.meter{flex:1 1 160px;height:8px;background:var(--line);border-radius:4px;overflow:hidden;min-width:120px}
.meter i{display:block;height:100%;width:0;background:var(--acc)}
label.f{color:var(--mute);font-size:13px;display:flex;gap:6px;align-items:center}
input[type=text],select{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
button{font:inherit;cursor:pointer;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:5px 12px}
button.main{background:var(--acc);border-color:var(--acc);color:#fff}
main{max-width:1100px;margin:0 auto;padding:16px 20px 80px}
.hint{color:var(--mute);margin:4px 0 16px}
.group{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:0 0 14px;overflow:hidden}
.ghead{padding:8px 14px;border-bottom:1px solid var(--line);font-size:13px;color:var(--mute);display:flex;gap:10px;flex-wrap:wrap}
.ghead b{color:var(--ink)}
.ctx{margin:0;padding:8px 0;border-bottom:1px solid var(--line);font:13px/1.45 ui-monospace,Consolas,monospace;overflow-x:auto}
.ctx div{padding:0 14px;white-space:pre-wrap;word-break:break-word}
.ctx div span{display:inline-block;width:3.2em;color:var(--mute);user-select:none}
.ctx div.on{background:var(--hl)}
.req{padding:8px 14px;border-bottom:1px solid var(--line);font-size:14px}
.noctx{padding:8px 14px;border-bottom:1px solid var(--line);color:var(--mute);font-size:13px}
.item{padding:10px 14px;border-top:1px dashed var(--line);outline:none}
.item:first-of-type{border-top:0}
.item:focus{background:var(--sel)}
.item.done{opacity:.72}
.meta{font-size:12px;color:var(--mute);margin-bottom:2px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 7px;margin-right:4px}
.chip.critical{border-color:var(--no);color:var(--no)}
.problem{margin:2px 0 4px}
.quote{font-size:13px;color:var(--mute);margin-bottom:6px}
.acts{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.acts button[aria-pressed=true].v0{background:var(--yes);border-color:var(--yes);color:#fff}
.acts button[aria-pressed=true].v1{background:var(--no);border-color:var(--no);color:#fff}
.acts button[aria-pressed=true].v2{background:var(--mid);border-color:var(--mid);color:#fff}
.acts input{flex:1 1 220px}
.keys{font-size:12px;color:var(--mute)}
.hidden{display:none}
</style>
</head>
<body>
<header><div class="bar">
<h1 id="title"></h1>
<span class="prog" id="prog"></span><span class="meter"><i id="meter"></i></span>
<label class="f">Кто размечает <input type="text" id="who" placeholder="имя или роль" size="14"></label>
<label class="f">Документ <select id="doc"><option value="">все</option></select></label>
<label class="f"><input type="checkbox" id="todo"> только неразмеченные</label>
<button class="main" id="save">Сохранить</button>
<button id="load">Загрузить…</button><input type="file" id="file" accept=".json,application/json" class="hidden">
</div></header>
<main>
<p class="hint" id="hint"></p>
<p class="hint keys">Клавиши на выделенном замечании: <b>1</b> / <b>2</b> / <b>3</b> — вердикт, <b>0</b> — снять,
<b>↓</b> / <b>↑</b> — следующее / предыдущее. Отметки сохраняются в этом браузере; «Сохранить» скачивает файл для
<code>python bench/gold_score.py --labels</code>.</p>
<div id="list"></div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("data").textContent);
  var STORE = "reqlens-labels:" + D.sheet + ":" + D.id;
  var S = {annotator: "", labels: {}};
  try { var saved = JSON.parse(localStorage.getItem(STORE) || "null"); if (saved && saved.labels) S = saved; } catch (e) {}
  function persist() { try { localStorage.setItem(STORE, JSON.stringify(S)); } catch (e) {} }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

  document.getElementById("title").textContent = D.title;
  document.getElementById("hint").textContent = D.hint + " Источник строк: " + D.source + ".";
  var who = document.getElementById("who");
  who.value = S.annotator || "";
  who.addEventListener("input", function () { S.annotator = who.value; persist(); });

  var docs = [];
  D.items.forEach(function (it) { if (docs.indexOf(it.doc) < 0) docs.push(it.doc); });
  var sel = document.getElementById("doc");
  docs.forEach(function (d) { var o = el("option", null, d); o.value = d; sel.appendChild(o); });

  var list = document.getElementById("list"), nodes = {}, groups = [], byGroup = {};
  D.items.forEach(function (it) {
    if (!byGroup[it.group]) { byGroup[it.group] = []; groups.push(it.group); }
    byGroup[it.group].push(it);
  });
  groups.forEach(function (g) {
    var items = byGroup[g], first = items[0];
    var box = el("section", "group"); box.dataset.doc = first.doc;
    var head = el("div", "ghead");
    head.appendChild(el("b", null, first.doc));
    var wheres = [];
    items.forEach(function (it) { if (wheres.indexOf(it.where) < 0) wheres.push(it.where); });
    head.appendChild(el("span", null, "где: " + wheres.join("; ")));
    if (first.anchor) head.appendChild(el("span", null, "строка " + first.anchor));
    head.appendChild(el("span", null, items.length > 1 ? items.length + " замечания к этому месту" : ""));
    box.appendChild(head);
    if (first.req) box.appendChild(el("div", "req", "Требование: " + first.req));
    if (first.ctx && first.ctx.length) {
      var pre = el("div", "ctx");
      first.ctx.forEach(function (c) {
        var row = el("div", c[2] ? "on" : null); row.appendChild(el("span", null, String(c[0]))); row.appendChild(document.createTextNode(c[1])); pre.appendChild(row);
      });
      box.appendChild(pre);
    } else {
      box.appendChild(el("div", "noctx", "Место в документе не найдено автоматически — смотрите цитату и сам документ."));
    }
    items.forEach(function (it) {
      var n = el("div", "item"); n.tabIndex = 0; n.dataset.key = it.key;
      var meta = el("div", "meta");
      if (it.severity) meta.appendChild(el("span", "chip " + it.severity, it.severity));
      if (it.criterion) meta.appendChild(el("span", "chip", it.criterion));
      meta.appendChild(el("span", null, "ключ " + it.key));
      n.appendChild(meta);
      n.appendChild(el("div", "problem", it.problem));
      if (it.quote) n.appendChild(el("div", "quote", "Цитата агента: «" + it.quote + "»"));
      var acts = el("div", "acts");
      D.verdicts.forEach(function (v, i) {
        var b = el("button", "v" + i, (i + 1) + " · " + v); b.type = "button"; b.dataset.v = v; b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", function () { setV(it.key, cur(it.key) === v ? "" : v); });
        acts.appendChild(b);
      });
      var c = el("input"); c.type = "text"; c.placeholder = "комментарий (необязательно)";
      c.addEventListener("input", function () { var l = S.labels[it.key] || {verdict: ""}; l.comment = c.value; S.labels[it.key] = l; persist(); });
      acts.appendChild(c);
      n.appendChild(acts);
      n.addEventListener("keydown", function (e) {
        if (e.target !== n) return;
        var k = e.key;
        if (k >= "1" && k <= String(D.verdicts.length)) { setV(it.key, D.verdicts[+k - 1]); move(n, 1); e.preventDefault(); }
        else if (k === "0") { setV(it.key, ""); e.preventDefault(); }
        else if (k === "ArrowDown" || k === "j") { move(n, 1); e.preventDefault(); }
        else if (k === "ArrowUp" || k === "k") { move(n, -1); e.preventDefault(); }
      });
      nodes[it.key] = {node: n, comment: c, box: box};
      box.appendChild(n);
    });
    list.appendChild(box);
  });

  function cur(key) { return (S.labels[key] || {}).verdict || ""; }
  function setV(key, v) {
    var l = S.labels[key] || {comment: ""}; l.verdict = v; S.labels[key] = l;
    if (!v && !l.comment) delete S.labels[key];
    persist(); paint(key); progress();
  }
  function paint(key) {
    var x = nodes[key]; if (!x) return;
    var v = cur(key);
    x.node.querySelectorAll("button[data-v]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.v === v)); });
    x.node.classList.toggle("done", !!v);
    x.comment.value = (S.labels[key] || {}).comment || "";
  }
  function visible(n) { return n.offsetParent !== null; }
  function move(n, dir) {
    var all = Array.prototype.slice.call(list.querySelectorAll(".item")).filter(visible);
    var i = all.indexOf(n), t = all[i + dir];
    if (t) { t.focus(); t.scrollIntoView({block: "center"}); }
  }
  function progress() {
    var done = 0, counts = {};
    D.items.forEach(function (it) { var v = cur(it.key); if (v) { done++; counts[v] = (counts[v] || 0) + 1; } });
    var p = document.getElementById("prog");
    p.textContent = "Размечено " + done + " из " + D.items.length + " ";
    p.appendChild(el("small", null, D.verdicts.map(function (v) { return v + " " + (counts[v] || 0); }).join(" · ")));
    document.getElementById("meter").style.width = (D.items.length ? 100 * done / D.items.length : 0) + "%";
    filter();
  }
  function filter() {
    var d = sel.value, todo = document.getElementById("todo").checked;
    Array.prototype.forEach.call(list.children, function (box) {
      var any = false;
      box.querySelectorAll(".item").forEach(function (n) {
        var show = !todo || !cur(n.dataset.key) || n === document.activeElement;
        n.classList.toggle("hidden", !show); any = any || show;
      });
      box.classList.toggle("hidden", (d && box.dataset.doc !== d) || !any);
    });
  }
  sel.addEventListener("change", filter);
  document.getElementById("todo").addEventListener("change", filter);

  document.getElementById("save").addEventListener("click", function () {
    if (!S.annotator.trim()) { alert("Укажите, кто размечает (имя или роль) — без этого метки не переносятся."); who.focus(); return; }
    var out = {sheet: D.sheet, source: D.source, annotator: S.annotator.trim(), saved_at: new Date().toISOString(),
               total: D.items.length, labels: {}};
    D.items.forEach(function (it) { var l = S.labels[it.key]; if (l && l.verdict) out.labels[it.key] = {verdict: l.verdict, comment: l.comment || ""}; });
    var blob = new Blob([JSON.stringify(out, null, 1)], {type: "application/json"});
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = D.download;
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  });
  var file = document.getElementById("file");
  document.getElementById("load").addEventListener("click", function () { file.click(); });
  file.addEventListener("change", function () {
    var f = file.files[0]; if (!f) return;
    f.text().then(function (t) {
      var j = JSON.parse(t);
      if (j.sheet && j.sheet !== D.sheet) { alert("Это файл другого листа: " + j.sheet); return; }
      var n = 0;
      Object.keys(j.labels || {}).forEach(function (k) { if (nodes[k] && j.labels[k].verdict) { S.labels[k] = j.labels[k]; n++; paint(k); } });
      if (!S.annotator && j.annotator) { S.annotator = j.annotator; who.value = j.annotator; }
      persist(); progress(); alert("Загружено меток: " + n);
    }).catch(function () { alert("Не удалось прочитать файл"); });
    file.value = "";
  });

  Object.keys(nodes).forEach(paint);
  progress();
})();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python bench/label_sheet.py")
    ap.add_argument("--sheet", choices=[*SHEETS, "all"], default="all", help="какой лист собрать (по умолчанию оба)")
    ap.add_argument("--apply", nargs="+", metavar="LABELS.json", help="перенести вердикты (то же, что gold_score.py --labels)")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.apply:
        return apply_files([Path(x) for x in a.apply], overwrite=a.overwrite, force=a.force)
    for sheet in (SHEETS if a.sheet == "all" else [a.sheet]):
        if not SHEETS[sheet]["md"].exists():
            print(f"нет {SHEETS[sheet]['md'].relative_to(ROOT).as_posix()} — пропускаю")
            continue
        p = build(sheet)
        n = len(md_rows(SHEETS[sheet]["md"]))
        print(f"{p.relative_to(ROOT).as_posix()}: {n} замечаний, {p.stat().st_size // 1024} КБ — откройте в браузере")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
