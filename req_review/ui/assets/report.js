/* ReqLens — интерактивный отчёт (структура «AI-агент», светлая зелёная тема). Ванильный JS, без зависимостей.
   Модули: ядро и разделы — здесь; «Граф» (3D/2D) — в report-graph.js и использует window.RL. */
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("data").textContent);
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ic = (n, s = 18) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;
  const SEV = {
    critical: { label: "Критичный", icon: "alert", color: "#D64545" },
    major: { label: "Существенный", icon: "alert", color: "#B7791F" },
    minor: { label: "Незначительный", icon: "chat", color: "#B8A532" },
    ok: { label: "Без замечаний", icon: "check", color: "#1F9D55" },
  };
  const ORDER = { critical: 0, major: 1, minor: 2, ok: 3 };
  const EARS = { ubiquitous: "постоянное", event: "по событию", state: "по состоянию", unwanted: "нежелательное поведение", optional: "опциональное", complex: "составное" };
  const CONF = { high: ["высокая", "sev-ok"], medium: ["средняя", "chip-brand"], low: ["низкая", ""] };
  const REDUCED = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const EMBED = /(?:^|[?&])embed=studio(?:&|$)/.test(location.search);
  const chip = (s, txt) => `<span class="chip sev-${s}">${ic(SEV[s].icon, 13)}${esc(txt || SEV[s].label)}</span>`;
  const scoreColor = (v) => (v >= 80 ? "var(--ok-accent)" : v >= 50 ? "var(--major-accent)" : "var(--critical-accent)");
  const deltaChip = (d) => `<span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? "▲ +" : "▼ "}${d}</span>`;
  const reqById = Object.fromEntries(D.reqs.map((r) => [r.rid, r]));
  const label = (r) => (r.doc_id ? `${r.rid} · ${r.doc_id}` : r.rid);
  const totalFindings = Object.keys(D.findings).length;
  const reqFindings = Object.values(D.findings).filter((f) => f.kind === "req").length;
  const cleanReqs = D.reqs.filter((r) => !r.findings.length).length;
  const totalMarks = Object.values(D.marks).reduce((a, m) => a + m.length, 0);
  const P = D.passport;
  const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const num = (v, suffix = "") => `<span data-count="${v}">${v}</span>${suffix}`;
  // ---- схема 2.2 (RAG): основания, категории, шаблоны, покрытие процесса — всё необязательно
  const BASIS_FINDINGS = Object.values(D.findings).filter((f) => (f.basis || []).length);
  const HAS_BASIS = BASIS_FINDINGS.length > 0;
  const COV_OK = D.coverage ? D.coverage.steps.filter((s) => s.rids.length).length : 0;
  const CATS = [...new Set(D.reqs.map((r) => r.category).filter(Boolean))];
  const BIG_DOC = D.lines.length > 1200, BIG_TABLE = D.reqs.length > 300;

  // ------------------------------------------------------------ тема, печать, тосты
  function currentTheme() { return document.documentElement.dataset.theme || "light"; }
  function setThemeBtn() { const d = currentTheme() === "dark"; $("#btn-theme").innerHTML = ic(d ? "sun" : "moon") + `<span>${d ? "Светлая тема" : "Тёмная тема"}</span>`; }
  function toggleTheme() {
    const t = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("reqlens-theme", t); } catch (e) { /* storage недоступен */ }
    setThemeBtn();
    document.dispatchEvent(new CustomEvent("reqlens:theme", { detail: t }));
  }
  $("#btn-theme").onclick = toggleTheme; setThemeBtn();
  $("#btn-print").onclick = () => window.print();
  $("#burger").onclick = () => $("#sidebar").classList.toggle("open");
  let toastT;
  function toast(msg) { const t = $("#toast"); t.innerHTML = ic("check", 16) + esc(msg); t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2200); }
  function copy(text, msg) {
    const done = () => toast(msg || "Скопировано");
    const fallback = () => { const ta = document.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); done(); } catch (e) { toast("Не удалось скопировать"); } ta.remove(); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }
  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: (type || "text/plain") + ";charset=utf-8" }));
    a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    toast("Файл сохранён: " + name);
  }
  const base = String(P.document || "report").replace(/[^\wа-яё\- ]+/gi, "").trim().slice(0, 40).replace(/\s+/g, "_") || "report";

  // ------------------------------------------------------------ Gherkin: подсветка и файл tests.feature
  const G_HEAD = /^(\s*)(Функция|Функционал|Свойство|Сценарий|Структура сценария|Шаблон сценария|Предыстория|Контекст|Примеры|Feature|Scenario Outline|Scenario|Background|Examples)(:)/;
  const G_STEP = /^(\s*)(Дано|Допустим|Пусть|Когда|Если|Тогда|То|Затем|И|А|Но|Также|Given|When|Then|And|But)(?=\s|$)/;
  function gherkinLine(line) {
    if (/^\s*#/.test(line)) return `<span class="g-com">${esc(line)}</span>`;
    if (/^\s*@/.test(line)) return line.replace(/\S+/g, (t) => `<span class="g-tag">${esc(t)}</span>`);
    let head = "", rest = line, m;
    if ((m = rest.match(G_HEAD))) { head = `${m[1]}<span class="g-head">${esc(m[2] + m[3])}</span>`; rest = rest.slice(m[0].length); }
    else if ((m = rest.match(G_STEP))) { head = `${m[1]}<span class="g-kw">${esc(m[2])}</span>`; rest = rest.slice(m[0].length); }
    const body = rest.split(/("[^"]*"|«[^»]*»|<[^<>\s]+>|\d+(?:[.,]\d+)?|\|)/g).map((t, i) => {
      if (!(i % 2)) return esc(t);
      if (t === "|") return `<span class="g-pipe">|</span>`;
      if (t[0] === "<") return `<span class="g-ph">${esc(t)}</span>`;
      if (/^\d/.test(t)) return `<span class="g-num">${esc(t)}</span>`;
      return `<span class="g-str">${esc(t)}</span>`;
    }).join("");
    return head + body;
  }
  const hasScenario = (g) => /^\s*(Сценарий|Структура сценария|Scenario)/m.test(g);
  const scenarioTitle = (r) => `${label(r)} — ${short(r.text.replace(/\s+/g, " "), 80)}`;
  function scenarioText(r, indent = "") {
    const g = (r.test.gherkin || "").trim();
    const body = hasScenario(g) ? g : `Сценарий: ${scenarioTitle(r)}\n` + g.split("\n").map((l) => "  " + l.trim()).join("\n");
    return body.split("\n").map((l) => indent + l).join("\n");
  }
  function gherkinHTML(r) { return scenarioText(r).split("\n").map(gherkinLine).join("\n"); }
  function gherkin(g) { return String(g || "").split("\n").map(gherkinLine).join("\n"); }
  function featureFile() {
    const ok = D.reqs.filter((r) => r.test.possible === true), bad = D.reqs.filter((r) => r.test.possible === false);
    const out = ["# language: ru", `# Сгенерировано ReqLens · ${P.agent_version} · ${P.started}`, `# Документ: ${P.document}`,
      `# Тестируемо ${D.scores.tests_ok} из ${D.scores.tests_total} требований`, "", `Функция: Приёмочные тесты — ${P.document}`, ""];
    ok.forEach((r) => { out.push(`  # ${label(r)}${r.section ? " · " + r.section : ""} · ${r.location}`); out.push(scenarioText(r, "  ")); out.push(""); });
    if (bad.length) {
      out.push("  # ---- Тест составить невозможно (доказательство непроверяемости) ----");
      bad.forEach((r) => out.push(`  # ${label(r)}: ${r.test.reason}${r.test.blocker ? ` · мешает «${r.test.blocker}»` : ""}`));
    }
    return out.join("\n") + "\n";
  }
  // ------------------------------------------------------------ вопросы аналитику (.md)
  const refLinks = (ref) => esc(ref).replace(/\b(R-\d+)\b/g, (m) => (reqById[m] ? `<a href="#${m}" data-go-req="${m}">${m}</a>` : m)).replace(/\b(S-\d+)\b/g, (m) => (D.findings[m] ? `<a href="#${m}" data-open="${m}">${m}</a>` : m));
  function questionsMD() {
    const groups = {}; D.questions.forEach((q) => (groups[q.section || "Без раздела"] = groups[q.section || "Без раздела"] || []).push(q));
    let n = 0;
    const lines = [`# Вопросы аналитику — ${P.document}`, "", `_Сформировано ReqLens (${P.agent_version}, ${P.started}). Закройте вопросы до начала разработки._`, ""];
    Object.entries(groups).forEach(([sec, qs]) => { lines.push(`## ${sec}`, ""); qs.forEach((q) => lines.push(`${++n}. **[${q.ref}]** _${SEV[q.severity] ? SEV[q.severity].label : q.severity}_ — ${q.text}`)); lines.push(""); });
    return lines.join("\n");
  }
  const DL = {
    md: () => download(`${base}_report.md`, D.report_md || "", "text/markdown"),
    json: () => download(`${base}_data.json`, JSON.stringify(D, null, 2), "application/json"),
    fixed: () => download(`${base}_requirements_fixed.md`, D.fixed_text || "", "text/markdown"),
    feature: () => download("tests.feature", featureFile(), "text/plain"),
    questions: () => download(`${base}_questions.md`, questionsMD(), "text/markdown"),
  };

  // ------------------------------------------------------------ глобальные действия (делегирование)
  document.addEventListener("click", (e) => {
    const inPop = e.target.closest("#hlpop");
    if (!inPop && !e.target.closest("mark.hl")) hidePop(true);
    if (e.target.closest("[data-pop-close]")) { hidePop(true, true); return; }
    const c = e.target.closest("[data-copy]"); if (c) { e.stopPropagation(); copy(c.dataset.copy, c.dataset.msg); return; }
    const d = e.target.closest("[data-dl]"); if (d) { e.preventDefault(); DL[d.dataset.dl](); return; }
    if (inPop && e.target.closest("[data-go-req],[data-go-doc],[data-open]")) hidePop(true);
    const r = e.target.closest("[data-go-req]"); if (r) { e.preventDefault(); closeDrawer(); goReq(r.dataset.goReq); return; }
    const g = e.target.closest("[data-go-doc]"); if (g) { e.preventDefault(); closeDrawer(); goDocReq(g.dataset.goDoc); return; }
    const l = e.target.closest("[data-go-line]"); if (l) { e.preventDefault(); closeDrawer(); goLine(+l.dataset.goLine); return; }
    const v = e.target.closest("[data-go-view]"); if (v) { e.preventDefault(); closeDrawer(); show(v.dataset.goView); return; }
    const f = e.target.closest("[data-open]"); if (f) { e.preventDefault(); openFinding(f.dataset.open, f); }
  });

  // ------------------------------------------------------------ анимации появления и счётчики
  function animateIn(el) {
    if (REDUCED) return;
    $$(".kpi,.card,.agent,.mini,.tcase", el).slice(0, 18).forEach((c, i) => {
      c.style.setProperty("--d", Math.min(i, 12) * 35 + "ms"); c.classList.add("rise");
      c.addEventListener("animationend", () => c.classList.remove("rise"), { once: true });
    });
    $$("[data-count]", el).forEach(countUp);
  }
  function countUp(node) {
    const to = parseFloat(node.dataset.count); if (!isFinite(to) || to === 0) return;
    const dec = String(node.dataset.count).includes(".") ? 1 : 0, t0 = performance.now(), dur = 900;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), v = to * (1 - Math.pow(1 - k, 3)); node.textContent = v.toFixed(dec); if (k < 1) requestAnimationFrame(step); else node.textContent = node.dataset.count; };
    node.textContent = (0).toFixed(dec); requestAnimationFrame(step);
  }

  // ------------------------------------------------------------ декоративная «сфера агента» (детерминированная)
  function sphere(w, h, n, seed, opts = {}) {
    let s = seed; const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    const cx = w * (opts.cx || 0.52), cy = h * 0.5, R = Math.min(w, h) * (opts.r || 0.38);
    const fx = cx - R * 0.72, fy = cy + R * 0.05;
    const col = opts.color || "var(--brand)";
    let lines = "", dots = "";
    const ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const rr = R * Math.sqrt((i + 0.5) / n) * (0.92 + rnd() * 0.12);
      const a = i * ga + (opts.twist || 0);
      const squash = opts.broken && rnd() < 0.35 ? 0.6 + rnd() * 0.3 : 1;
      const x = cx + Math.cos(a) * rr * (0.78 + 0.22 * Math.abs(Math.sin(a))) * squash, y = cy + Math.sin(a) * rr * squash;
      const edge = rr / R;
      const op = (0.25 + edge * 0.7).toFixed(2);
      dots += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.7 + edge * 1.3).toFixed(2)}" fill="${col}" opacity="${op}"/>`;
      if (i % (opts.lineEvery || 4) === 0 && edge > 0.45) lines += `<line x1="${fx.toFixed(1)}" y1="${fy.toFixed(1)}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${col}" stroke-width=".5" opacity="${(0.12 + edge * 0.25).toFixed(2)}"/>`;
    }
    for (let i = 0; i < n / 8; i++) { const a = rnd() * 6.28, d = R * (1.05 + rnd() * 0.35); dots += `<circle cx="${(cx + Math.cos(a) * d).toFixed(1)}" cy="${(cy + Math.sin(a) * d).toFixed(1)}" r="${(0.6 + rnd()).toFixed(2)}" fill="${col}" opacity=".35"/>`; }
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${lines}${dots}<circle cx="${fx}" cy="${fy}" r="3.5" fill="${col}"/><circle cx="${fx}" cy="${fy}" r="10" fill="${col}" opacity=".15"/></svg>`;
  }

  // ------------------------------------------------------------ навигация (сайдбар)
  const VIEWS = [
    { id: "overview", label: "Обзор", icon: "grid" },
    { id: "reqs", label: "Требования", icon: "list", count: D.reqs.length },
    { id: "doc", label: "Документ", icon: "file", count: totalMarks || "" },
    { id: "graph", label: "Граф", icon: "cube", count: D.graph.edges.length || "" },
    { id: "set", label: "Проверка набора", icon: "layers", count: D.set.length || "" },
    { id: "tests", label: "Тесты", icon: "flask", count: D.scores.tests_total ? `${D.scores.tests_ok}/${D.scores.tests_total}` : "" },
    { id: "fixes", label: "Исправления", icon: "wand", count: D.changes.length || "" },
    ...(HAS_BASIS ? [{ id: "kb", label: "База знаний", icon: "book", count: BASIS_FINDINGS.length }] : []),
    ...(D.coverage ? [{ id: "coverage", label: "Покрытие процесса", icon: "layers", count: `${COV_OK}/${D.coverage.steps.length}` }] : []),
    { id: "trace", label: "Трассировка", icon: "trace" },
    { id: "export", label: "Экспорт", icon: "download" },
  ];
  const RENDER = {}, ONSHOW = {}, ONHIDE = {};
  const rendered = {};
  let active = null;
  $("#nav").innerHTML = VIEWS.map((v, i) => `<button class="nav-item" type="button" data-view="${v.id}" aria-keyshortcuts="${i + 1}">${ic(v.icon)}<span>${v.label}</span>${v.count !== undefined && v.count !== "" ? `<span class="count">${v.count}</span>` : ""}</button>`).join("");
  $("#views").innerHTML = VIEWS.map((v) => `<section class="view" id="view-${v.id}" aria-label="${v.label}"></section>`).join("");
  $("#nav").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) { show(b.dataset.view); history.replaceState(null, "", "#" + b.dataset.view); $("#sidebar").classList.remove("open"); } });
  function renderView(id) {
    if (rendered[id] || !RENDER[id]) return false;
    RENDER[id]($("#view-" + id)); rendered[id] = true; return true;
  }
  function show(id) {
    if (!RENDER[id]) id = "overview";
    const fresh = renderView(id);
    if (active && active !== id && ONHIDE[active]) ONHIDE[active]();
    hidePop(true);
    active = id;
    $$("#nav .nav-item").forEach((b) => (b.dataset.view === id ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + id));
    $("#pagehead").classList.toggle("compact", id !== "overview");
    if (fresh) animateIn($("#view-" + id));
    if (ONSHOW[id]) ONSHOW[id]();
  }

  // ------------------------------------------------------------ шапка страницы
  function renderHead() {
    $("#top-model").innerHTML = ic("cpu", 13) + esc(P.model);
    $("#pagehead").innerHTML = `<div class="grow">
        <div class="caption">Отчёт о проверке требований</div>
        <h1 class="display" style="margin-top:6px">${esc(P.document)}</h1>
        <div class="meta"><span>${ic("clock", 14)}${esc(P.started)}</span><span>${ic("cpu", 14)}${esc(P.model)}</span>
          <span>${ic("id", 14)}${esc(P.agent_version)}</span><span>${ic("shield", 14)}${esc(P.mode)}</span></div></div>
      <div class="row wrap no-print">
        ${EMBED ? "" : `<button class="btn btn-primary" id="btn-run">${ic("play", 16)}Запустить проверку</button>`}
        <button class="btn btn-outline" data-dl="md">${ic("download", 16)}Скачать отчёт</button></div>`;
    const run = $("#btn-run");
    if (run) run.onclick = () => {
      $("#drawer-title").textContent = "Запустить проверку";
      $("#drawer-body").innerHTML = `<p class="muted">Агент работает локально. Чтобы проверить документ заново или другой файл:</p>
        <div><div class="caption" style="margin-bottom:8px">Из командной строки</div>
        <pre class="code">python review.py ${esc(P.file)} reports/report.md --open</pre>
        <button class="btn btn-sm btn-outline" style="margin-top:8px" data-copy="python review.py ${esc(P.file)} reports/report.md --open">${ic("copy", 14)}Скопировать команду</button></div>
        <div><div class="caption" style="margin-bottom:8px">В браузере — ReqLens Studio</div>
        <pre class="code">python -m req_review.web</pre>
        <a class="btn btn-sm btn-primary" style="margin-top:8px" href="http://localhost:8000/" target="_blank" rel="noopener">${ic("arrow-up-right", 14)}Открыть Studio (localhost:8000)</a></div>`;
      openDrawer(run);
    };
  }
  // AI-ассистент живёт в Studio (нужен сервер с моделью); в статическом отчёте — подсказка
  if (EMBED) $("#btn-ai").hidden = true;
  $("#btn-ai").onclick = () => {
    $("#drawer-title").textContent = "AI-ассистент";
    $("#drawer-body").innerHTML = `<div class="ai-teaser"><span class="logo-mark">${ic("bot", 20)}</span>
        <div><div class="h3">Доступно в ReqLens Studio</div><p class="small muted" style="margin-top:4px">Ассистенту нужен сервер: он отвечает по данным этого отчёта и при необходимости спрашивает модель. Статический HTML работает офлайн и вопросов не отправляет.</p></div></div>
      <div><div class="caption" style="margin-bottom:8px">Примеры вопросов</div><div class="row wrap">
        ${["Почему " + (worstReq() ? worstReq().rid : "R-001") + " критичное?", "Что исправить первым?", "Какие есть противоречия?", "Сколько требований тестируемо?"].map((q) => `<span class="chip chip-outline">${esc(q)}</span>`).join("")}</div></div>
      <div><div class="caption" style="margin-bottom:8px">Запуск</div><pre class="code">python -m req_review.web</pre>
        <a class="btn btn-sm btn-primary" style="margin-top:8px" href="http://localhost:8000/" target="_blank" rel="noopener">${ic("arrow-up-right", 14)}Открыть Studio</a></div>`;
    openDrawer($("#btn-ai"));
  };
  const BKIND = { standard: ["Стандарт", "book"], law: ["Закон РК", "shield"], template: ["Шаблон", "file"] };
  function basisHTML(f, compact) {
    const bs = f.basis || []; if (!bs.length) return "";
    return `<div class="basis"><div class="caption">${ic("book", 13)} Основание</div>${bs.map((b) => `<div class="basis-item">
        <span class="chip basis-${b.kind}">${ic(BKIND[b.kind][1], 13)}${BKIND[b.kind][0]}</span>
        <div class="grow"><div class="small"><b>${esc(b.source)}</b>${b.clause ? ` · ${b.kind === "template" ? "" : "п. "}${esc(b.clause)}` : ""}</div>
          <div class="small muted" style="margin-top:2px">«${esc(compact ? short(b.quote, 170) : b.quote)}»${b.paraphrase ? ` <span class="faint">— пересказ своими словами</span>` : ""}</div>
          ${b.url ? `<a class="small" href="${esc(b.url)}" target="_blank" rel="noopener noreferrer">${ic("arrow-up-right", 12)} официальный текст</a>` : ""}</div></div>`).join("")}</div>`;
  }
  // компактная строка основания для таблицы: источник и пункт, полный текст — в карточке
  const basisLine = (f) => ((f.basis || []).length ? `<div class="small faint" style="margin-top:4px">${ic("book", 12)} Основание: ${f.basis.map((b) => esc(b.source + (b.clause ? " · " + b.clause : ""))).join("; ")}</div>` : "");
  // контекст модели: весь документ в каждом запросе или RAG — только релевантные фрагменты (длинные документы)
  const ctxChip = () => (P.context_mode ? `<span class="chip ${P.context_mode === "rag" ? "chip-brand" : "chip-outline"}" title="${P.context_mode === "rag" ? "в запрос попадают только релевантные фрагменты документа и базы знаний" : "весь документ передаётся в каждом запросе"}">${ic("layers", 13)}контекст: ${P.context_mode === "rag" ? `RAG${P.context_chunks ? ` · ${P.context_chunks} фрагм.` : ""}` : "полный"}</span>` : "");
  function worstReq() { return D.reqs.slice().sort((a, b) => ORDER[a.worst] - ORDER[b.worst] || a.score - b.score)[0]; }

  // ------------------------------------------------------------ Обзор
  function kpi(lbl, numHTML, sub, hero, go, tone) {
    return `<article class="kpi ${hero ? "kpi-hero" : ""}">
      <div class="row between"><span class="lbl">${esc(lbl)}</span>
        <button class="arrow-btn" aria-label="${esc(lbl)}: подробнее" data-go-view="${go}">${ic("arrow-up-right", 16)}</button></div>
      <div class="kpi-num"${tone ? ` style="color:${tone}"` : ""}>${numHTML}</div>
      <div class="sub">${sub}</div></article>`;
  }
  const TRACE_ST = { ok: ["ok", "check", "готово"], warn: ["warn", "alert", "предупреждение"], err: ["err", "x", "ошибка"], skip: ["skip", "pause", "пропущен"] };
  function traceHTML() {
    return `<ol class="trace">${D.trace.map((s) => { const m = TRACE_ST[s.status] || TRACE_ST.ok; return `<li class="${m[0]}">
      <time>${esc(s.clock || "—")}</time><span class="dot" aria-hidden="true">${ic(m[1], 12)}</span>
      <div><div class="t">${esc(s.title)}<span class="sr-only"> — ${m[2]}</span></div>
      <div class="d">${esc(s.detail)}${s.dur != null ? ` · ${s.dur} с` : ""}</div></div></li>`; }).join("")}</ol>`;
  }
  function priorities(n) {
    const items = [];
    D.set.forEach((fid) => { const f = D.findings[fid]; if (f.severity !== "minor") items.push([ORDER[f.severity] * 2, f, `${fid} · ${f.cname}`]); });
    D.reqs.forEach((r) => { const f = r.findings.map((id) => D.findings[id]).sort((a, b) => ORDER[a.severity] - ORDER[b.severity])[0]; if (f && f.severity !== "minor") items.push([ORDER[f.severity] * 2 + 1, f, `${label(r)} · ${f.cname}`]); });
    return items.sort((a, b) => a[0] - b[0]).slice(0, n);
  }
  function verdictHTML(compact) {
    const v = D.verdict, cls = { critical: "v-critical", major: "v-major", ok: "v-ok" }[v.level], icn = { critical: "x", major: "alert", ok: "check" }[v.level];
    const pr = priorities(compact ? 4 : 8);
    return `<div class="card" id="verdict"><div class="card-title">${ic("check")}<span class="h2">Итог: можно ли начинать разработку</span></div>
      <div class="verdict-card"><span class="verdict-badge ${cls}">${ic(icn, 20)}${esc(v.title)}</span>
        <div class="grow"><div class="h3">${esc(v.headline)}</div><p class="small muted" style="margin-top:4px">${esc(v.text)}</p></div></div>
      ${pr.length ? `<div class="caption" style="margin:20px 0 8px">Исправить в первую очередь</div>
        <ol style="margin:0;padding-left:20px" class="small">${pr.map(([, f, t]) => `<li style="margin:8px 0"><a href="#" data-open="${f.fid}"><b>${esc(t)}</b></a> — ${esc(f.fix)}</li>`).join("")}</ol>` : `<p class="small muted" style="margin-top:16px">Обязательных исправлений нет.</p>`}</div>`;
  }
  function setSummaryHTML() {
    return `<div class="card"><div class="card-title">${ic("layers")}<span class="h2 grow">Проверка набора целиком</span>
        <button class="btn btn-sm btn-ghost" data-go-view="set">Подробнее ${ic("arrow-right", 14)}</button></div>
      ${D.set_criteria.map((c) => `<div class="row between" style="padding:9px 0;border-top:1px dashed var(--border)">
        <div class="grow"><div class="small" style="font-weight:600">${esc(c.name)}</div><div class="small faint">${esc(c.ref)}</div></div>
        ${c.count ? chip(c.worst, `${c.count} замеч.`) : chip("ok", "нарушений нет")}</div>`).join("")}</div>`;
  }
  // «Профиль качества»: горизонтальные полосы с полными названиями; серые — в порядке, цветные — по тяжести
  function profileHTML() {
    const rows = D.scores.radar_req.map((r) => {
      const fs = Object.values(D.findings).filter((f) => f.kind === "req" && f.criterion === r.key);
      const worst = fs.length ? fs.reduce((a, f) => (ORDER[f.severity] < ORDER[a] ? f.severity : a), "minor") : "ok";
      const nreq = new Set(fs.map((f) => f.rid)).size;
      const name = r.name.replace(/\s*\(.*\)/, "");
      const col = worst === "ok" ? "var(--neutral-bar)" : SEV[worst].color;
      const st = worst === "ok" ? "в порядке" : `${SEV[worst].label.toLowerCase()}: ${nreq} треб.`;
      return `<div class="prof-row" title="${esc(r.name)} — ${r.v}% требований без нарушений · ${esc(st)}">
        <span class="small${worst === "ok" ? " muted" : ""}" style="font-weight:${worst === "ok" ? 400 : 600}">${esc(name)}</span>
        <div class="bar"><i style="width:${Math.max(3, r.v)}%;background:${col}"></i></div>
        <span class="small" style="text-align:right">${worst === "ok" ? `<span class="muted">${r.v}%</span>` : `${ic(SEV[worst].icon, 12)} ${r.v}%`}</span></div>`;
    }).join("");
    return `<div class="card prof"><div class="card-title">${ic("spark")}<span class="h2 grow">Профиль качества</span>
        <span class="small muted">доля требований без нарушений</span></div>
      <div class="prof-rows">${rows}</div>
      <div class="legend small muted"><span><i style="background:var(--neutral-bar)"></i>в порядке</span><span><i style="background:${SEV.minor.color}"></i>незначительные</span>
        <span><i style="background:${SEV.major.color}"></i>существенные</span><span><i style="background:${SEV.critical.color}"></i>критичные</span></div></div>`;
  }
  // Ошибки модели (лимит API, нет ключа): честно показываем, что часть проверок неполная
  function errorBanner() {
    const failed = D.reqs.filter((r) => !r.llm_checked), errSteps = D.trace.filter((t) => t.status === "err");
    if (!failed.length && !errSteps.length) return "";
    return `<div class="banner-err" role="alert">${ic("alert", 18)}<div><b>Часть проверок выполнена без модели.</b>
      ${failed.length ? `Модель не ответила по ${failed.length} требованиям (${failed.slice(0, 5).map((r) => `<a href="#${r.rid}" data-go-req="${r.rid}">${esc(r.rid)}</a>`).join(", ")}${failed.length > 5 ? "…" : ""}) — для них показаны только срабатывания правил.` : ""}
      ${errSteps.map((s) => esc(s.title) + ": " + esc(s.detail)).join(" · ")}
      <div class="small" style="margin-top:4px">Частые причины: исчерпан лимит API (429) или не задан ключ в .env. Повторный прогон возьмёт готовые ответы из кэша и дозапросит остальные.</div></div></div>`;
  }
  function renderOverview(el) {
    const s = D.scores;
    const failedSteps = D.trace.filter((t) => t.status === "err").length;
    const agentStatus = failedSteps ? ["st-fail", "x", "ОШИБКА · часть шагов"] : ["st-done", "check", "ЗАВЕРШЁН"];
    const setCrit = D.set.filter((f) => D.findings[f].severity === "critical").length;
    const tPct = s.tests_total ? Math.round((100 * s.tests_ok) / s.tests_total) : 0;
    const crit = D.counts.critical;
    el.innerHTML = `${errorBanner()}
      <div class="grid g-4">
        ${kpi("Всего требований", num(D.reqs.length), `<b>${D.split_method === "ids" ? "ID" : "R"}</b>нарезка ${D.split_method === "ids" ? "по ID документа" : "с номерами агента"}`, true, "reqs")}
        ${kpi("Нарушений", num(totalFindings), `<b>${reqFindings}</b>по требованиям · <b>${D.set.length}</b>по набору`, false, "doc")}
        ${kpi("Критичных", num(crit), `${ic("alert", 14)}непроверяемые, противоречивые, неполные`, false, "reqs", crit ? "var(--critical)" : "var(--ok)")}
        ${kpi("Без замечаний", num(cleanReqs), `<b>${Math.round((100 * cleanReqs) / Math.max(1, D.reqs.length))}%</b>из ${D.reqs.length} требований`, false, "reqs", "var(--ok)")}
      </div>
      <div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(280px,360px);margin-top:16px;align-items:stretch" id="ov-grid">
        <div class="col-fill" style="min-width:0">
          <article class="agent" aria-label="Агент проверки требований">
            <span class="status ${agentStatus[0]}">${ic(agentStatus[1], 12)}${agentStatus[2]}</span>
            <div class="vis">${sphere(320, 260, 520, 7)}</div>
            <div class="info">
              <div class="row between"><div><div class="h2">Агент проверки требований</div>
                <div class="small muted">${esc(P.document)}</div></div><span class="chip chip-outline">${ic("cpu", 13)}${esc(P.calls)} обращений</span></div>
              <div class="metrics">
                <div class="metric"><div class="kpi-num">${num(s.readiness, "%")}</div><div class="small muted">готовность документа ${D.rescore ? deltaChip(D.rescore.readiness_after - D.rescore.readiness_before) : ""}</div></div>
                <div class="metric"><div class="kpi-num" style="color:var(--text)">${num(s.doc)}<span class="h3 faint">/100</span></div><div class="small muted">балл качества</div></div>
                <div class="metric"><div class="kpi-num" style="color:var(--text)">${esc(P.duration_s)}<span class="h3 faint"> с</span></div><div class="small muted">время прогона</div></div>
              </div>
              <div class="row wrap" style="gap:8px">${ctxChip()}${P.tokens_per_call ? `<span class="chip chip-outline">${ic("cpu", 13)}~${Number(P.tokens_per_call).toLocaleString("ru-RU")} токенов на запрос</span>` : ""}
              </div>
              <p class="small muted">Статическое ревью по ISO/IEC/IEEE 29148 §5.2.5–5.2.6 и IEEE 830 §4.3: нарезка, проверка каждого требования, тест-проба, проверка набора${P.critic ? ", критик-агент" : ""}.</p>
            </div>
            <div class="foot"><span class="live"><i></i>${esc(P.profile.toUpperCase())}</span><span class="small muted grow">${esc(P.model)} · ${esc(P.agent_version)}</span>
              <button class="btn btn-sm btn-ghost" data-go-view="export">${ic("download", 14)}Артефакты</button></div>
          </article>
          <div class="mini-agents">
            <article class="mini"><div class="vis">${sphere(110, 150, 140, 3, { r: 0.34, lineEvery: 6, color: setCrit ? "var(--critical-accent)" : "var(--brand)", broken: !!setCrit })}</div>
              <div class="body"><span class="status ${setCrit ? "st-fail" : D.set.length ? "st-warn" : "st-done"}" style="align-self:flex-start">${ic(setCrit ? "x" : D.set.length ? "alert" : "check", 11)}${setCrit ? "КОНФЛИКТЫ" : D.set.length ? "ЗАМЕЧАНИЯ" : "ЧИСТО"}</span>
                <div class="h3">Проверка набора</div><div class="small muted">${D.set.length} замечаний · балл набора ${s.set}/100</div>
                <div class="row wrap" style="margin-top:auto;gap:4px"><button class="btn btn-sm btn-ghost" data-go-view="set">Открыть ${ic("arrow-right", 14)}</button><button class="btn btn-sm btn-ghost" data-go-view="graph">${ic("cube", 14)}Граф</button></div></div></article>
            <article class="mini"><div class="vis">${sphere(110, 150, 140, 11, { r: 0.34, lineEvery: 6, color: "var(--brand-light)" })}</div>
              <div class="body"><span class="status ${tPct >= 80 ? "st-done" : "st-warn"}" style="align-self:flex-start">${ic("flask", 11)}ТЕСТ-ПРОБА ${tPct}%</span>
                <div class="h3">Приёмочные тесты</div><div class="small muted">${s.tests_ok} из ${s.tests_total} требований можно проверить тестом</div>
                <button class="btn btn-sm btn-ghost" style="align-self:flex-start;margin-top:auto" data-go-view="tests">Открыть ${ic("arrow-right", 14)}</button></div></article>
          </div>
          ${profileHTML()}
        </div>
        <div class="col-fill">
          <div class="card"><div class="card-title">${ic("trace")}<span class="h2 grow">Трассировка агента</span><span class="chip chip-brand">${D.trace.filter((t) => t.status !== "skip").length}/${D.trace.length}</span></div>${traceHTML()}</div>
          ${D.changes.length ? `<div class="card" style="display:flex;gap:14px;align-items:center"><span class="logo-mark" style="border-radius:14px;flex:none">${ic("wand")}</span>
            <div class="grow"><div class="caption">Исправленный документ</div><div class="small muted">${D.changes.length} формулировок исправлено${D.rescore ? ` · балл ${D.rescore.before} → ${D.rescore.after}` : ""}</div></div>
            <button class="btn btn-round" data-go-view="fixes" aria-label="Открыть исправления">${ic("arrow-right", 16)}</button></div>` : ""}
          ${setSummaryHTML()}
        </div>
      </div>
      <div class="section-title"><h2 class="h1">Требования</h2><div class="row"><span class="small muted hide-sm">${D.reqs.length} шт.</span>
        <button class="btn btn-sm btn-outline" data-go-view="reqs">Все фильтры ${ic("arrow-right", 14)}</button></div></div>
      ${D.reqs.length > 50 ? `<p class="small muted" style="margin-bottom:8px">Показаны 20 требований с наименьшим баллом из ${D.reqs.length} — полный список в разделе «Требования».</p>${reqTable(D.reqs.slice().sort((a, b) => a.score - b.score).slice(0, 20), "ov")}` : reqTable(D.reqs, "ov")}
      <div style="margin-top:16px">${verdictHTML(true)}</div>`;
    wireTable(el);
  }

  // ------------------------------------------------------------ таблица требований (Health Status)
  function critDots(r) {
    return `<div class="crit-dots" aria-label="Критерии">${D.criteria.map((c, i) => {
      const fs = r.findings.map((id) => D.findings[id]).filter((x) => x.criterion === c.key);
      const s = fs.length ? fs.reduce((a, x) => (ORDER[x.severity] < ORDER[a] ? x.severity : a), "minor") : "ok";
      const tip = `${i + 1}. ${c.name}: ${s === "ok" ? "в порядке" : SEV[s].label.toLowerCase()}`;
      return `<i title="${esc(tip)}" style="background:${s === "ok" ? "var(--neutral-bar)" : SEV[s].color}"></i>`;
    }).join("")}</div>`;
  }
  // нейтральный вид для «чистых» требований: серый круг 100 и бейдж без заливки
  const statusChip = (s) => (s === "ok" ? `<span class="chip chip-neutral">${ic("check", 13)}Без замечаний</span>` : chip(s));
  const ring = (v) => `<div class="mini-ring" style="--v:${v};--c:${v >= 100 ? "var(--neutral-bar)" : scoreColor(v)}"><span${v >= 100 ? ' style="color:var(--text-2);font-weight:600"' : ""}>${v}</span></div>`;
  const critLegend = () => `<div class="crit-legend small muted" aria-label="Легенда колонки «Критерии»">
    <span><b>Критерии</b> (слева направо): ${D.criteria.map((c, i) => `${i + 1}. ${esc(c.name.replace(/\s*\(.*\)/, ""))}`).join(" · ")}</span>
    <span class="row" style="gap:12px"><span><i style="background:var(--neutral-bar)"></i>в порядке</span><span><i style="background:${SEV.minor.color}"></i>незначит.</span><span><i style="background:${SEV.major.color}"></i>существ.</span><span><i style="background:${SEV.critical.color}"></i>критичное</span><span>· наведите на квадратик</span></span></div>`;
  function expandHTML(r) {
    const t = r.test;
    return `<div class="inner stack">
      <div><div class="caption" style="margin-bottom:6px">Цитата из документа · <a href="#L${r.line}" data-go-doc="${r.rid}">${esc(r.location)} — показать в документе</a></div><div class="quote">${esc(r.text)}</div></div>
      ${r.note ? `<div class="small" style="color:var(--major)">${ic("alert", 14)} ${esc(r.note)}</div>` : ""}
      ${r.findings.length ? `<div>${r.findings.map((id) => { const f = D.findings[id]; return `<div class="finding" data-open="${id}" tabindex="0">
        ${chip(f.severity)}<div><div class="f-title">${esc(f.cname)} <span class="faint small">· ${esc(f.cref)}</span></div>
        <div class="small muted" style="margin-top:2px">«${esc(f.quote)}» — ${esc(f.problem)}</div>
        <div class="small" style="margin-top:4px"><b>Как исправить:</b> ${esc(f.fix)}</div>${basisLine(f)}</div></div>`; }).join("")}</div>` : `<div class="small" style="color:var(--ok)">${ic("check", 14)} Нарушений не найдено.</div>`}
      ${r.rewrite && r.findings.length ? `<div class="row" style="padding:12px 16px;border-radius:14px;background:var(--ok-soft)">
        <div class="grow small"><b style="color:var(--ok)">Предлагаемая правка:</b> ${esc(r.rewrite)}</div>
        <button class="btn btn-sm btn-outline" data-copy="${esc(r.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}Копировать</button></div>` : ""}
      ${t.possible === true ? `<details class="more"><summary>${ic("flask", 14)} Тест-проба: приёмочный тест составлен</summary><pre class="code gherkin" style="margin-top:8px">${gherkinHTML(r)}</pre></details>`
        : t.possible === false ? `<div class="small" style="color:var(--critical)">${ic("flask", 14)} <b>Тест составить невозможно:</b> ${esc(t.reason)} — мешает «${esc(t.blocker)}»</div>` : ""}
    </div>`;
  }
  function reqTable(rows, key) {
    if (!rows.length) return empty("Ничего не найдено", "Измените фильтры или запрос.");
    return `${critLegend()}<div class="table-wrap"><table class="tbl" data-tbl="${key}"><thead><tr>
      <th scope="col">ID в отчёте</th><th scope="col">ID в документе</th><th scope="col">Краткая формулировка</th>
      <th scope="col" title="${esc(D.criteria.map((c, i) => `${i + 1}. ${c.name}`).join("\n"))}">Критерии ⓘ</th><th scope="col">Балл</th><th scope="col">Статус</th><th scope="col"><span class="sr-only">Действия</span></th></tr></thead>
      <tbody>${tableRows(rows.slice(0, BIG_TABLE ? TCHUNK : rows.length), key)}${BIG_TABLE && rows.length > TCHUNK ? moreRow(key, rows) : ""}</tbody></table></div>`;
  }
  const TCHUNK = 120, TBL = {};
  function moreRow(key, rows) {
    TBL[key] = { rows, n: TCHUNK };
    return `<tr class="more-rows" data-more="${key}"><td colspan="7"><button class="btn btn-sm btn-outline" type="button" data-more-btn="${key}">Показать ещё (${rows.length - TCHUNK})</button> <span class="small faint">большой документ: строки дорисовываются при прокрутке</span></td></tr>`;
  }
  function moreRows(key, upto) {
    const t = TBL[key], tr = t && $(`tr.more-rows[data-more="${key}"]`); if (!tr) return;
    const n2 = Math.min(t.rows.length, Math.max(upto || 0, t.n + TCHUNK));
    tr.insertAdjacentHTML("beforebegin", tableRows(t.rows.slice(t.n, n2), key)); t.n = n2;
    if (t.n >= t.rows.length) tr.remove(); else $("button", tr).textContent = `Показать ещё (${t.rows.length - t.n})`;
  }
  // автодогрузка, когда строка «Показать ещё» приближается к экрану
  const moreIO = window.IntersectionObserver ? new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) moreRows(e.target.dataset.more); }), { rootMargin: "600px 0px" }) : null;
  function armMore(el) { if (moreIO) $$("tr.more-rows", el).forEach((x) => moreIO.observe(x)); }
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-more-btn]"); if (b) moreRows(b.dataset.moreBtn); });
  function tableRows(rows, key) {
    return `${rows.map((r) => `<tr class="rrow" data-rid="${r.rid}" id="row-${key}-${r.rid}">
        <td><b>${esc(r.rid)}</b></td><td>${r.doc_id ? `<span class="chip chip-brand">${esc(r.doc_id)}</span>` : `<span class="small faint">присвоен агентом</span>`}</td>
        <td style="min-width:260px;max-width:460px">${esc(short(r.text, 120))}${r.category ? `<div style="margin-top:6px"><span class="chip chip-outline cat-chip">${ic("layers", 12)}${esc(r.category)}</span></div>` : ""}</td>
        <td>${critDots(r)}</td>
        <td>${ring(r.score)}</td>
        <td>${statusChip(r.worst)}</td>
        <td><div class="row" style="gap:6px;justify-content:flex-end"><button class="btn btn-sm btn-ghost btn-icon" data-go-doc="${r.rid}" aria-label="Показать ${esc(r.rid)} в документе" title="Показать в документе">${ic("file", 15)}</button>
          <button class="btn btn-sm btn-outline" data-exp="${r.rid}" aria-expanded="false" aria-controls="exp-${key}-${r.rid}">Подробнее ${ic("chevron", 14)}</button></div></td></tr>
        <tr class="exp" id="exp-${key}-${r.rid}" hidden><td colspan="7">${expandHTML(r)}</td></tr>`).join("")}`;
  }
  function wireTable(el) {
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-exp]") || (e.target.closest("tr.rrow") && !e.target.closest("a,button") ? e.target.closest("tr.rrow").querySelector("[data-exp]") : null);
      if (!b) return;
      const tr = b.closest("tr"), exp = tr.nextElementSibling, open = exp.hidden;
      exp.hidden = !open; tr.classList.toggle("open", open); b.setAttribute("aria-expanded", open);
      b.innerHTML = (open ? "Свернуть " : "Подробнее ") + ic("chevron", 14);
    });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { const f = e.target.closest("[data-open]"); if (f) openFinding(f.dataset.open, f); } });
  }
  function expandRow(rid, key) {
    const b = $(`#row-${key}-${CSS.escape(rid)} [data-exp]`);
    if (b && b.getAttribute("aria-expanded") !== "true") b.click();
    return $(`#row-${key}-${CSS.escape(rid)}`);
  }

  // ------------------------------------------------------------ Требования: фильтры + таблица
  const qstate = { q: "", sev: "all", crit: "", section: "", cat: "", sort: "order" };
  let reqUpdate = () => {};
  function renderReqs(el) {
    const sections = [...new Set(D.reqs.map((r) => r.section).filter(Boolean))];
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Требования</h2>
        <button class="btn btn-sm btn-outline" data-go-view="doc">${ic("file", 14)}Открыть документ</button></div>
      <div class="toolbar" id="req-filters">
        <div class="seg" role="group" aria-label="Серьёзность">${["all", "critical", "major", "minor", "ok"].map((k) => `<button data-sev="${k}" aria-pressed="${k === "all"}">${k === "all" ? "Все" : SEV[k].label}</button>`).join("")}</div>
        <select class="input" id="fcrit" style="width:auto" aria-label="Критерий"><option value="">Все критерии</option>${D.criteria.map((c) => `<option value="${c.key}">${esc(c.name)}</option>`).join("")}</select>
        ${sections.length > 1 ? `<select class="input" id="fsec" style="width:auto;max-width:240px" aria-label="Раздел"><option value="">Все разделы</option>${sections.map((s) => `<option>${esc(s)}</option>`).join("")}</select>` : ""}
        ${CATS.length ? `<select class="input" id="fcat" style="width:auto;max-width:220px" aria-label="Категория"><option value="">Все категории</option>${CATS.map((c) => `<option>${esc(c)}</option>`).join("")}</select>` : ""}
        <div class="seg" role="group" aria-label="Сортировка"><button data-sort="order" aria-pressed="true">По порядку</button><button data-sort="score" aria-pressed="false">Сначала худшие</button></div>
        <span class="small faint" id="req-count" aria-live="polite"></span></div>
      <div id="req-body"></div>`;
    const upd = () => {
      let rs = D.reqs.filter((r) => {
        if (qstate.sev !== "all" && r.worst !== qstate.sev) return false;
        if (qstate.crit && !r.crit.includes(qstate.crit)) return false;
        if (qstate.section && r.section !== qstate.section) return false;
        if (qstate.cat && r.category !== qstate.cat) return false;
        if (qstate.q) {
          const hay = (r.rid + " " + (r.doc_id || "") + " " + r.text + " " + r.findings.map((id) => D.findings[id].quote + " " + D.findings[id].problem).join(" ")).toLowerCase();
          if (!hay.includes(qstate.q.toLowerCase())) return false;
        }
        return true;
      });
      if (qstate.sort === "score") rs = rs.slice().sort((a, b) => a.score - b.score);
      $("#req-count").textContent = `Показано ${rs.length} из ${D.reqs.length}`;
      $("#req-body").innerHTML = reqTable(rs, "rq"); armMore($("#req-body"));
    };
    $$("[data-sev]", el).forEach((b) => b.onclick = () => { qstate.sev = b.dataset.sev; $$("[data-sev]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $$("[data-sort]", el).forEach((b) => b.onclick = () => { qstate.sort = b.dataset.sort; $$("[data-sort]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $("#fcrit", el).onchange = (e) => { qstate.crit = e.target.value; upd(); };
    if ($("#fsec", el)) $("#fsec", el).onchange = (e) => { qstate.section = e.target.value; upd(); };
    if ($("#fcat", el)) $("#fcat", el).onchange = (e) => { qstate.cat = e.target.value; upd(); };
    wireTable($("#req-body", el));
    reqUpdate = upd;
    upd();
  }
  function resetReqFilters() {
    Object.assign(qstate, { q: "", sev: "all", crit: "", section: "", cat: "" }); $("#gsearch").value = "";
    $$("#view-reqs [data-sev]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.sev === "all"));
    if ($("#fcrit")) $("#fcrit").value = ""; if ($("#fsec")) $("#fsec").value = ""; if ($("#fcat")) $("#fcat").value = "";
    reqUpdate();
  }
  function goReq(rid) {
    if (!reqById[rid]) return;
    show("reqs");
    if (!$(`#row-rq-${CSS.escape(rid)}`)) resetReqFilters();
    if (!$(`#row-rq-${CSS.escape(rid)}`) && TBL.rq) moreRows("rq", TBL.rq.rows.findIndex((x) => x.rid === rid) + 1);
    const tr = expandRow(rid, "rq");
    if (tr) {
      tr.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
      tr.classList.remove("flash"); void tr.offsetWidth; tr.classList.add("flash");
    }
    history.replaceState(null, "", "#" + rid);
  }
  $("#gsearch").addEventListener("input", (e) => { show("reqs"); qstate.q = e.target.value; reqUpdate(); });

  // ------------------------------------------------------------ Документ: подсветка как в проверке орфографии
  const md_ = (s) => esc(s).replace(/(\*\*|__|^\s*[-*•]\s|\|)/g, '<span class="md">$1</span>');
  const lineReq = {}, reqAt = {};
  D.reqs.forEach((r) => {
    if (!r.line) return;
    (reqAt[r.line] = reqAt[r.line] || []).push(r);
    for (let n = r.line; n <= (r.line_end || r.line); n++) if (!lineReq[n] || ORDER[r.worst] < ORDER[lineReq[n].worst]) lineReq[n] = r;
  });
  function lineHTML(l) {
    const ms = D.marks[l.n] || [], t = l.t;
    if (!ms.length) return md_(t) || "&nbsp;";
    let out = "", pos = 0;
    ms.forEach(([s, e, fid, sev, kind]) => {
      if (s < pos) return;
      const f = D.findings[fid];
      out += md_(t.slice(pos, s)) + `<mark class="hl ${sev} ${kind === "set" ? "set" : ""}" data-f="${fid}" data-sev="${sev}" tabindex="0" aria-label="${esc(SEV[sev].label)} замечание: ${esc(f.cname)}">${md_(t.slice(s, e))}</mark>`;
      pos = e;
    });
    return out + md_(t.slice(pos));
  }
  const docFilter = { critical: true, major: true, minor: true, set: true };
  function lineRow(l) {
    const r = lineReq[l.n], starts = reqAt[l.n] || [];
    return `<div class="ln ${l.h ? "h" : ""} ${r && !l.h ? "in-req w-" + r.worst : ""}" id="L${l.n}" ${r ? `data-rid="${r.rid}"` : ""}><span class="n">${l.n}</span><span class="t">${lineHTML(l)}</span><span class="rq">${starts.map((x) => `<button class="ln-req" data-go-req="${x.rid}" title="${esc(label(x))}: открыть в таблице">${x.worst !== "ok" ? ic(SEV[x.worst].icon, 11) : ic("check", 11)}${esc(x.doc_id || x.rid)}</button>`).join("")}</span></div>`;
  }
  // виртуализация: заглушки высотой с чанк, содержимое появляется при приближении к экрану
  const CH = 200, lineIdx = {}; D.lines.forEach((l, i) => (lineIdx[l.n] = i));
  const filled = {};
  function docChunks() {
    let out = ""; for (let c = 0; c * CH < D.lines.length; c++) out += `<div class="doc-chunk" data-c="${c}" style="min-height:${Math.min(CH, D.lines.length - c * CH) * 26}px"></div>`; return out;
  }
  function fillChunk(c) {
    if (filled[c]) return; const box = $(`.doc-chunk[data-c="${c}"]`); if (!box) return;
    filled[c] = true; box.innerHTML = D.lines.slice(c * CH, (c + 1) * CH).map(lineRow).join(""); box.style.minHeight = "";
    $$("mark.hl", box).forEach((m) => { const off = !docFilter[m.dataset.sev] || (m.classList.contains("set") && !docFilter.set); m.classList.toggle("off", off); m.tabIndex = off ? -1 : 0; });
  }
  function ensureLine(n) { if (BIG_DOC && lineIdx[n] != null) fillChunk(Math.floor(lineIdx[n] / CH)); }
  const MARKS = Object.entries(D.marks).flatMap(([n, ms]) => ms.map((m) => ({ n: +n, s: m[0], fid: m[2], sev: m[3], set: m[4] === "set" }))).sort((a, b) => a.n - b.n || a.s - b.s);
  function renderDoc(el) {
    const setMarks = Object.values(D.marks).reduce((a, ms) => a + ms.filter((m) => m[4] === "set").length, 0);
    const cnt = (k) => Object.values(D.marks).reduce((a, ms) => a + ms.filter((m) => m[3] === k && m[4] === "req").length, 0);
    el.innerHTML = `<div class="section-title" style="margin-top:0"><div><h2 class="h1">Документ</h2>
        <p class="small muted" style="margin-top:4px">${esc(P.document)} · ${D.lines.length} строк · ${totalMarks} подсвеченных фрагментов</p></div>
        <div class="row no-print"><button class="btn btn-sm btn-outline btn-icon" id="mk-prev" aria-label="Предыдущий дефект (K)" title="Предыдущий дефект (K)">${ic("chevron", 15)}</button>
          <button class="btn btn-sm btn-outline btn-icon" id="mk-next" aria-label="Следующий дефект (J)" title="Следующий дефект (J)" style="transform:none">${ic("chevron", 15)}</button></div></div>
      <div class="toolbar no-print" role="group" aria-label="Показывать замечания">${["critical", "major", "minor"].filter((k) => cnt(k)).map((k) => `<button class="pill" aria-pressed="true" data-docf="${k}"><span class="u-sample u-${k}" aria-hidden="true">abc</span>${SEV[k].label} · ${cnt(k)}</button>`).join("")}
        ${setMarks ? `<button class="pill" aria-pressed="true" data-docf="set"><span class="u-sample u-set" aria-hidden="true">abc</span>Набор · ${setMarks}</button>` : ""}
        <span class="grow"></span><span class="small faint hide-sm">Наведите или нажмите на подчёркнутое · <span class="kbd">J</span> <span class="kbd">K</span> — следующий / предыдущий</span></div>
      ${D.lines.length ? `<div class="docview"><div class="doc" id="doc">${BIG_DOC ? docChunks() : D.lines.map(lineRow).join("")}</div>
      <div class="minimap no-print" id="minimap" aria-hidden="true"><span class="mm-view" id="mm-view"></span></div></div>` : empty("Текст документа недоступен", "Документ не содержит текстовых строк.")}
      <div class="legend small muted"><span><span class="u-sample u-critical">волна</span> критичный</span><span><span class="u-sample u-major">волна</span> существенный</span><span><span class="u-sample u-minor">точки</span> незначительный</span><span><span class="u-sample u-set">штрих</span> замечание к набору</span><span>· полоса слева — требование и его худший статус, значок справа — переход к таблице</span></div>`;
    if (!D.lines.length) return;
    const total = D.lines.length;
    const mm = $("#minimap", el);
    mm.insertAdjacentHTML("beforeend", Object.entries(D.marks).flatMap(([n, ms]) => ms.map((m) => `<i class="${m[3]} ${m[4] === "set" ? "set" : ""}" style="top:${(100 * (n - 1)) / total}%" data-line="${n}" data-f="${m[2]}" title="Строка ${n}: ${esc(D.findings[m[2]].cname)}"></i>`)).join(""));
    mm.onclick = (e) => {
      const i = e.target.closest("i[data-line]");
      if (i) { goLine(+i.dataset.line); const mk = $(`#doc mark.hl[data-f="${CSS.escape(i.dataset.f)}"]`); if (mk) setTimeout(() => showPop(mk, true), REDUCED ? 0 : 380); return; }
      const r = mm.getBoundingClientRect(), doc = $("#doc"), k = (e.clientY - r.top) / r.height;
      window.scrollTo({ top: doc.getBoundingClientRect().top + scrollY + k * doc.offsetHeight - innerHeight / 2, behavior: REDUCED ? "auto" : "smooth" });
    };
    $$("[data-docf]", el).forEach((b) => b.onclick = () => {
      const k = b.dataset.docf; docFilter[k] = !docFilter[k]; b.setAttribute("aria-pressed", docFilter[k]);
      $$("#doc mark.hl", el).forEach((m) => { const off = !docFilter[m.dataset.sev] || (m.classList.contains("set") && !docFilter.set); m.classList.toggle("off", off); m.tabIndex = off ? -1 : 0; });
      $$("#minimap i", el).forEach((m) => { const sev = m.classList[0]; m.style.display = docFilter[sev] && (!m.classList.contains("set") || docFilter.set) ? "" : "none"; });
    });
    $("#mk-next", el).onclick = () => stepMark(1); $("#mk-prev", el).onclick = () => stepMark(-1);
    if (BIG_DOC) {
      const io = window.IntersectionObserver ? new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) fillChunk(+e.target.dataset.c); }), { rootMargin: "1500px 0px" }) : null;
      $$(".doc-chunk", el).forEach((x) => (io ? io.observe(x) : fillChunk(+x.dataset.c)));
    }
    wirePop($("#doc", el));
    // подсветка требования при наведении на строку
    $("#doc", el).addEventListener("mouseover", (e) => { const ln = e.target.closest(".ln[data-rid]"); hoverReq(ln ? ln.dataset.rid : null); });
    $("#doc", el).addEventListener("mouseleave", () => hoverReq(null));
  }
  let hovered = null;
  function hoverReq(rid) {
    if (rid === hovered) return; hovered = rid;
    $$("#doc .ln.hov").forEach((x) => x.classList.remove("hov"));
    if (rid) $$(`#doc .ln[data-rid="${CSS.escape(rid)}"]`).forEach((x) => x.classList.add("hov"));
  }
  function updateMinimap() {
    const doc = $("#doc"), v = $("#mm-view"); if (!doc || !v || active !== "doc") return;
    const r = doc.getBoundingClientRect(), h = doc.offsetHeight || 1;
    const top = Math.max(0, Math.min(1, -r.top / h)), size = Math.min(1, innerHeight / h);
    v.style.top = top * 100 + "%"; v.style.height = Math.max(4, size * 100) + "%";
  }
  let mmRaf = 0;
  window.addEventListener("scroll", () => { if (!mmRaf) mmRaf = requestAnimationFrame(() => { mmRaf = 0; updateMinimap(); }); }, { passive: true });
  ONSHOW.doc = updateMinimap;
  function flashLines(a, b) {
    for (let n = a; n <= b; n++) { const l = $("#L" + n); if (l) { l.classList.remove("flash"); void l.offsetWidth; l.classList.add("flash"); } }
  }
  function goLine(n) {
    show("doc"); ensureLine(n);
    const l = $("#L" + n); if (!l) return;
    l.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
    flashLines(n, n);
  }
  function goDocReq(rid) {
    const r = reqById[rid]; if (!r) return;
    show("doc"); ensureLine(r.line); ensureLine(r.line_end || r.line);
    const l = $("#L" + r.line); if (!l) return;
    l.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
    flashLines(r.line, r.line_end || r.line);
    history.replaceState(null, "", "#L" + r.line);
  }
  let markIdx = -1;
  function stepMark(dir) {
    show("doc");
    // порядок дефектов берём из данных, а не из DOM: в большом документе не все строки отрисованы
    const ms = MARKS.filter((x) => docFilter[x.sev] && (!x.set || docFilter.set)); if (!ms.length) return;
    const act = $("#doc mark.hl.active"), cur = act ? ms.findIndex((x) => x.fid === act.dataset.f && x.n === +act.closest(".ln").id.slice(1)) : -1;
    markIdx = ((cur >= 0 ? cur : markIdx) + dir + ms.length) % ms.length;
    ensureLine(ms[markIdx].n);
    const m = $(`#L${ms[markIdx].n} mark.hl[data-f="${CSS.escape(ms[markIdx].fid)}"]`); if (!m) return;
    m.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
    m.focus({ preventScroll: true });
    showPop(m, true);
  }

  // ------------------------------------------------------------ карточка замечания у фрагмента (поповер)
  const pop = $("#hlpop");
  let popMark = null, popPinned = false, popT = 0;
  function popHTML(fid) {
    const f = D.findings[fid];
    const where = f.kind === "req" ? `<a href="#${f.rid}" data-go-req="${f.rid}">${esc(label(reqById[f.rid]))}</a> · ${esc(f.location || "")}`
      : `Набор: ${f.refs.map((x) => (reqById[x.rid] ? `<a href="#${x.rid}" data-go-req="${x.rid}">${esc(x.label)}</a>` : "документ")).join(", ")}`;
    return `<div class="row wrap" style="gap:6px">${chip(f.severity)}<span class="chip chip-outline" title="${esc(f.cref)}">${esc(f.cref)}</span></div>
      <button class="btn btn-sm btn-ghost btn-icon" data-pop-close aria-label="Закрыть карточку">${ic("x", 14)}</button>
      <div class="pop-title">${esc(f.cname)}</div>
      <div class="small muted">${where}</div>
      <p class="small">${esc(f.problem)}</p>
      <div class="small"><b>Как исправить:</b> ${esc(f.fix)}</div>
      ${f.rewrite ? `<div class="pop-rw"><div class="caption" style="color:var(--ok)">Предложенная правка</div><p class="small" style="margin-top:4px">${esc(f.rewrite)}</p></div>` : ""}
      ${basisHTML(f, true)}
      <div class="row wrap" style="gap:6px">
        ${f.rewrite ? `<button class="btn btn-sm btn-primary" data-copy="${esc(f.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}Копировать правку</button>` : ""}
        <button class="btn btn-sm btn-outline" data-open="${fid}">Подробнее</button>
        ${f.kind === "req" ? `<button class="btn btn-sm btn-ghost" data-go-req="${f.rid}">${ic("list", 14)}В таблице</button>` : ""}</div>`;
  }
  function placePop(m) {
    const r = m.getBoundingClientRect(), w = Math.min(380, innerWidth - 24);
    pop.style.width = w + "px";
    const left = Math.max(12, Math.min(innerWidth - w - 12, r.left));
    const ph = pop.offsetHeight, below = innerHeight - r.bottom;
    const top = below > ph + 16 || r.top < ph + 16 ? r.bottom + 8 : r.top - ph - 8;
    pop.style.left = left + scrollX + "px"; pop.style.top = top + scrollY + "px";
  }
  function showPop(m, pin) {
    clearTimeout(popT);
    if (!m || m.classList.contains("off")) return;
    $$("mark.hl.active").forEach((x) => x.classList.remove("active")); m.classList.add("active");
    if (popMark !== m) { pop.innerHTML = popHTML(m.dataset.f); popMark = m; }
    popPinned = popPinned && popMark === m ? true : !!pin;
    pop.classList.toggle("pinned", popPinned);
    pop.hidden = false; placePop(m);
  }
  function hidePop(force, refocus) {
    clearTimeout(popT);
    if (!popMark || (popPinned && !force)) return;
    const m = popMark;
    pop.hidden = true; popMark = null; popPinned = false; m.classList.remove("active");
    if (refocus) m.focus({ preventScroll: true });
  }
  function wirePop(root) {
    const canHover = window.matchMedia && matchMedia("(hover: hover)").matches;
    root.addEventListener("mouseover", (e) => {
      const m = e.target.closest("mark.hl:not(.off)"); if (!m || !canHover || popPinned) return;
      clearTimeout(popT); popT = setTimeout(() => showPop(m, false), 120);
    });
    root.addEventListener("mouseout", (e) => { if (e.target.closest("mark.hl") && !popPinned) { clearTimeout(popT); popT = setTimeout(() => { if (!pop.matches(":hover")) hidePop(); }, 220); } });
    root.addEventListener("click", (e) => { const m = e.target.closest("mark.hl:not(.off)"); if (m) { e.preventDefault(); showPop(m, true); } });
    root.addEventListener("focusin", (e) => { const m = e.target.closest("mark.hl"); if (m && !popPinned) showPop(m, false); });
    root.addEventListener("keydown", (e) => {
      const m = e.target.closest("mark.hl"); if (!m) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showPop(m, true); const b = $("button:not([data-pop-close])", pop); if (b) b.focus(); }
    });
  }
  pop.addEventListener("mouseleave", () => { if (!popPinned) { popT = setTimeout(() => hidePop(), 220); } });
  pop.addEventListener("mouseenter", () => clearTimeout(popT));
  pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); hidePop(true, true); } });
  window.addEventListener("resize", () => { if (popMark) placePop(popMark); });

  // ------------------------------------------------------------ Drawer
  let lastFocus = null;
  function openDrawer(from) {
    hidePop(true);
    lastFocus = from || document.activeElement;
    $("#drawer").classList.add("open"); $("#overlay").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawer-close").focus({ preventScroll: true });
  }
  function closeDrawer() {
    if (!$("#drawer").classList.contains("open")) return;
    $("#drawer").classList.remove("open"); $("#overlay").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true");
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  }
  $("#drawer-close").onclick = closeDrawer; $("#overlay").onclick = closeDrawer;
  function openFinding(fid, from) {
    const f = D.findings[fid]; if (!f) return;
    $$("mark.hl.active").forEach((m) => m.classList.remove("active")); $$(`mark.hl[data-f="${CSS.escape(fid)}"]`).forEach((m) => m.classList.add("active"));
    const conf = CONF[f.confidence];
    const where = f.kind === "req"
      ? `<a href="#" data-go-req="${f.rid}">${esc(label(reqById[f.rid]))}</a> · ${esc(f.location)}${f.line ? ` · <a href="#" data-go-line="${f.line}">строка ${f.line}</a>` : ""}`
      : f.refs.map((x) => (x.rid !== "DOC" && reqById[x.rid] ? `<a href="#" data-go-req="${x.rid}">${esc(x.label)}</a>` : "документ")).join(", ");
    $("#drawer-title").textContent = f.kind === "set" ? `${f.fid} · ${f.cname}` : f.cname;
    $("#drawer-body").innerHTML = `<div class="row wrap">${chip(f.severity)}<span class="chip chip-outline">${esc(f.cref)}</span>
        ${conf ? `<span class="chip ${conf[1]}">${ic("shield", 13)}уверенность: ${conf[0]}</span>` : ""}<span class="chip">${esc(f.source)}</span></div>
      <div class="small muted">${where}</div>
      ${f.kind === "req" ? `<div><div class="caption" style="margin-bottom:6px">Цитата из документа</div><div class="quote">«${esc(f.quote)}»</div></div>`
        : `<div><div class="caption" style="margin-bottom:6px">Цитаты</div>${f.refs.map((x) => `<div class="quote" style="margin-bottom:8px"><b>${esc(x.label)}:</b> «${esc(x.quote)}»</div>`).join("")}</div>`}
      <div><div class="caption" style="margin-bottom:6px">Нарушенный критерий</div><p><b>${esc(f.cname)}</b> — ${esc(f.cref)}</p></div>
      <div><div class="caption" style="margin-bottom:6px">Объяснение</div><p>${esc(f.problem)}</p></div>
      <div><div class="caption" style="margin-bottom:6px">Как исправить</div><p>${esc(f.fix)}</p></div>
      ${basisHTML(f, false)}
      ${f.rewrite ? `<div class="card" style="padding:16px;background:var(--ok-soft);border-color:transparent"><div class="row between"><div class="caption" style="color:var(--ok)">Предложенная правка</div>
        <button class="btn btn-sm btn-outline" data-copy="${esc(f.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}Копировать</button></div><p style="margin-top:8px">${esc(f.rewrite)}</p></div>` : ""}
      ${f.critic ? `<div class="small muted">${ic("shield", 14)} Критик: ${esc(f.critic)}</div>` : ""}
      ${f.kind === "set" && D.graph.edges.length ? `<button class="btn btn-sm btn-outline" data-go-view="graph">${ic("cube", 14)}Показать на графе</button>` : ""}`;
    openDrawer(from);
  }

  // ------------------------------------------------------------ Проверка набора
  const subActive = { set: "findings", trace: "steps" };
  function subTabs(view, tabs) {
    return `<div class="tabs" role="tablist">${tabs.map((t) => `<button class="tab" role="tab" data-sub="${view}:${t[0]}" aria-selected="${subActive[view] === t[0]}">${ic(t[2], 15)}${t[1]}${t[3] !== undefined ? `<span class="count">${t[3]}</span>` : ""}</button>`).join("")}</div>`;
  }
  function wireSub(el, view) {
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-sub]"); if (!b) return;
      const [, id] = b.dataset.sub.split(":"); subActive[view] = id;
      $$("[data-sub]", el).forEach((x) => x.setAttribute("aria-selected", x === b));
      $$(".panel", el).forEach((p) => p.classList.toggle("active", p.dataset.panel === id));
    });
  }
  function radarSVG(items, size = 300) {
    const n = items.length, c = size / 2, R = size / 2 - 64;
    const pt = (i, v) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / n; return [c + Math.cos(a) * R * v, c + Math.sin(a) * R * v]; };
    let g = "";
    [0.25, 0.5, 0.75, 1].forEach((k) => { g += `<polygon points="${items.map((_, i) => pt(i, k).join(",")).join(" ")}" fill="none" stroke="var(--border)"/>`; });
    items.forEach((_, i) => { const [x, y] = pt(i, 1); g += `<line x1="${c}" y1="${c}" x2="${x}" y2="${y}" stroke="var(--border)"/>`; });
    g += `<polygon points="${items.map((it, i) => pt(i, Math.max(0.02, it.v / 100)).join(",")).join(" ")}" fill="color-mix(in srgb,var(--brand) 18%,transparent)" stroke="var(--brand)" stroke-width="2" stroke-linejoin="round"/>`;
    items.forEach((it, i) => {
      const [x, y] = pt(i, Math.max(0.02, it.v / 100)); g += `<circle cx="${x}" cy="${y}" r="3.5" fill="var(--brand)"><title>${esc(it.name)}: ${it.v}%</title></circle>`;
      const [lx, ly] = pt(i, 1.2), anchor = Math.abs(lx - c) < 8 ? "middle" : lx > c ? "start" : "end";
      const w = it.name.replace(/\s*\(.*\)/, "").split(" "), ls = w.length > 1 && it.name.length > 14 ? [w.slice(0, Math.ceil(w.length / 2)).join(" "), w.slice(Math.ceil(w.length / 2)).join(" ")] : [w.join(" ")];
      g += `<text x="${lx}" y="${ly - (ls.length - 1) * 6}" text-anchor="${anchor}" dominant-baseline="middle">${ls.map((l, k) => `<tspan x="${lx}" dy="${k ? 12 : 0}">${esc(l)}</tspan>`).join("")}</text>`;
    });
    return `<svg class="radar" viewBox="-56 -6 ${size + 112} ${size + 12}" role="img" aria-label="Профиль по критериям">${g}</svg>`;
  }
  const KINDS = { contradiction: "Противоречие", duplicate: "Дублирование", terminology: "Терминология", gap: "Пропуск", dependency: "Зависимость", structure: "Структура", other: "Прочее" };
  function renderSet(el) {
    const list = D.set.map((fid) => { const f = D.findings[fid]; return `<article class="card" style="padding:20px">
      <div class="row wrap"><b>${fid}</b><span class="chip chip-outline">${esc(KINDS[f.set_kind] || f.set_kind)}</span>${chip(f.severity)}<span class="chip">${esc(f.cname)}</span>
        <span class="grow"></span><button class="btn btn-sm btn-ghost" data-open="${fid}">Подробнее ${ic("arrow-right", 14)}</button></div>
      ${(f.values || []).length ? `<div class="row wrap" style="gap:8px;margin-top:12px" aria-label="Конфликтующие значения">${ic("alert", 14)}<span class="small" style="font-weight:600">Числовой конфликт:</span>
        ${f.values.map((v) => `<span class="chip sev-critical" title="${esc(v.quote)}"><b>${esc(v.label)}</b>&nbsp;${esc(v.value)}</span>`).join('<span class="small muted">vs</span>')}</div>` : ""}
      <p style="margin:10px 0">${esc(f.problem)}</p>
      ${f.refs.map((x) => `<div class="quote small" style="margin-top:6px">${x.rid !== "DOC" && reqById[x.rid] ? `<a href="#" data-go-req="${x.rid}"><b>${esc(x.label)}</b></a>` : "<b>документ</b>"}: «${esc(x.quote)}»${x.line ? ` · <a href="#L${x.line}" data-go-line="${x.line}">строка ${x.line}</a>` : ""}</div>`).join("")}
      <p class="small muted" style="margin-top:10px"><b>Как исправить:</b> ${esc(f.fix)}</p>${basisLine(f)}</article>`; }).join("");
    const d = D.domain, g = D.glossary;
    const st = { covered: ["ok", "покрыта"], partial: ["major", "частично"], missing: ["critical", "не покрыта"] };
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Проверка набора целиком</h2><div class="row wrap"><span class="chip chip-brand">балл набора ${D.scores.set}/100</span>
        <button class="btn btn-sm btn-outline" data-go-view="graph">${ic("cube", 14)}Граф связей</button></div></div>
      <div class="grid" style="grid-template-columns:minmax(0,360px) minmax(0,1fr);align-items:start;margin-bottom:16px" id="set-top">
        <div class="card"><div class="card-title">${ic("spark")}<span class="h2">Профиль набора</span></div>${radarSVG(D.scores.radar_set, 300)}
          <p class="small faint">ISO/IEC/IEEE 29148 §5.2.6 и IEEE 830 §4.3.</p></div>
        <div class="grid g-2" style="align-content:start">${D.set_criteria.map((c) => `<div class="card" style="padding:16px">
          <div class="row between"><span class="caption">${esc(c.ref)}</span>${c.count ? chip(c.worst, `${c.count}`) : chip("ok", "ок")}</div>
          <div class="h3" style="margin:6px 0 2px">${esc(c.name)}</div><p class="small muted">${esc(c.desc)}</p></div>`).join("")}</div></div>
      ${subTabs("set", [["findings", "Замечания", "alert", D.set.length], ["domain", "Финтех-полнота", "bank", d ? d.coverage + "%" : undefined], ["glossary", "Глоссарий", "book", g ? g.terms.length : undefined]])}
      <div class="panel ${subActive.set === "findings" ? "active" : ""}" data-panel="findings"><div class="stack">${list || empty("Нарушений на уровне набора нет", "Противоречий, дублей и пропусков не найдено.")}</div></div>
      <div class="panel" data-panel="domain">${d ? `<div class="card" style="margin-bottom:16px"><div class="row wrap" style="gap:24px"><div><div class="caption">${esc(d.name)}</div><div class="kpi-num">${d.coverage}%</div><div class="small muted">покрытие чек-листа</div></div>
          <div class="grow small muted">${esc(d.disclaimer)}</div></div></div>
        <div class="grid g-3">${d.areas.map((a) => `<div class="card" style="padding:16px"><div class="row between"><b class="small">${esc(a.title)}</b>${chip(st[a.status][0], st[a.status][1])}</div>
          ${a.quotes.length ? a.quotes.map((q) => `<div class="quote small" style="margin-top:8px">«${esc(q)}»</div>`).join("") : `<p class="small muted" style="margin-top:8px">${ic("chat", 14)} ${esc(a.question)}</p>`}</div>`).join("")}</div>` : empty("Домен отключён", "Запустите с --domain fintech.")}</div>
      <div class="panel" data-panel="glossary">${g ? `${g.synonyms.map((s) => `<div class="card" style="padding:14px 18px;background:var(--major-soft);border-color:transparent;margin-bottom:10px">${ic("alert", 14)} <b>Разнобой терминов:</b> ${s.terms.map((t) => `<span class="chip chip-outline">${esc(t)}</span>`).join(" ")} → «${esc(s.preferred)}». <span class="small muted">${esc(s.problem)}</span></div>`).join("")}
        <div class="table-wrap"><table class="tbl"><thead><tr><th>Термин</th><th>Определение</th><th>Упоминаний</th><th>Требования</th></tr></thead><tbody>
        ${g.terms.map((t) => `<tr><td><b>${esc(t.term)}</b></td><td>${t.defined ? esc(t.definition) : chip("major", "не определён")}</td><td>${t.count}</td><td class="small">${t.reqs.slice(0, 8).map((r) => `<a href="#" data-go-req="${r}">${esc(reqById[r] ? reqById[r].doc_id || r : r)}</a>`).join(", ")}</td></tr>`).join("")}</tbody></table></div>` : empty("Нет данных", "Глоссарий не построен.")}</div>`;
    wireSub(el, "set");
  }

  // ------------------------------------------------------------ Тесты: Gherkin-сценарии по требованиям
  const tstate = { f: "all", q: "" };
  function renderTests(el) {
    const s = D.scores, ok = D.reqs.filter((r) => r.test.possible === true), bad = D.reqs.filter((r) => r.test.possible === false), none = D.reqs.filter((r) => r.test.possible == null);
    const N = D.reqs.length || 1, pct = s.tests_total ? Math.round((100 * s.tests_ok) / s.tests_total) : 0;
    el.innerHTML = `<div class="section-title" style="margin-top:0"><div><h2 class="h1">Тест-кейсы</h2>
        <p class="small muted" style="margin-top:4px">Агент пытается написать приёмочный сценарий Gherkin к каждому требованию. Не получилось — это доказательство непроверяемости.</p></div>
        <div class="row wrap no-print">${ok.length ? `<button class="btn btn-sm btn-outline" data-copy="${esc(featureFile())}" data-msg="Сценарии скопированы">${ic("copy", 14)}Скопировать все</button>
          <button class="btn btn-sm btn-primary" data-dl="feature">${ic("download", 14)}Скачать tests.feature</button>` : ""}</div></div>
      ${!ok.length && !bad.length ? empty("Тест-проба не выполнялась", "Запустите прогон без флага --no-tests — агент составит сценарии Gherkin.") : `
      <div class="grid g-3" style="margin-bottom:16px">
        <article class="kpi kpi-hero"><span class="lbl">Тестируемо</span><div class="kpi-num">${num(s.tests_ok)}<span class="h2" style="opacity:.85"> из ${s.tests_total}</span></div><div class="sub">${pct}% требований можно проверить приёмочным тестом</div></article>
        <article class="kpi"><span class="lbl">Тест составить невозможно</span><div class="kpi-num" style="color:${bad.length ? "var(--critical)" : "var(--ok)"}">${num(bad.length)}</div><div class="sub">${ic("flask", 14)}доказательство непроверяемости</div></article>
        <article class="kpi"><span class="lbl">Без тест-пробы</span><div class="kpi-num" style="color:var(--text-2)">${num(none.length)}</div><div class="sub">${ic("pause", 14)}модель не ответила или проба выключена</div></article></div>
      <div class="card" style="padding:16px 20px;margin-bottom:16px"><div class="row between wrap"><span class="small" style="font-weight:600">Покрытие «тестируемо ${s.tests_ok} из ${s.tests_total}»</span><span class="small muted">${pct}%</span></div>
        <div class="cov" role="img" aria-label="Тестируемо ${ok.length}, непроверяемо ${bad.length}, без пробы ${none.length}">
          <i class="cov-ok" style="width:${(100 * ok.length) / N}%"></i><i class="cov-bad" style="width:${(100 * bad.length) / N}%"></i><i class="cov-none" style="width:${(100 * none.length) / N}%"></i></div>
        <div class="legend small muted" style="margin-top:10px"><span><i style="background:var(--ok-accent)"></i>${ic("check", 12)} тестируемо · ${ok.length}</span><span><i style="background:var(--critical-accent)"></i>${ic("x", 12)} непроверяемо · ${bad.length}</span><span><i style="background:var(--neutral-bar)"></i>${ic("pause", 12)} без пробы · ${none.length}</span></div></div>
      <div class="toolbar no-print">
        <div class="seg" role="group" aria-label="Фильтр тестов">${[["all", "Все", D.reqs.length], ["ok", "Тестируемые", ok.length], ["bad", "Непроверяемые", bad.length], ["none", "Без пробы", none.length]].map(([k, t, n]) => `<button data-tf="${k}" aria-pressed="${tstate.f === k}">${t} · ${n}</button>`).join("")}</div>
        <label class="search" style="max-width:320px"><span class="sr-only">Поиск по сценариям</span>${ic("search", 16)}<input id="tsearch" type="search" placeholder="Поиск по сценариям и ID…"></label>
        <span class="small faint" id="tcount" aria-live="polite"></span></div>
      <div class="grid g-2" id="tlist"></div>`}`;
    if (!ok.length && !bad.length) return;
    const card = (r) => {
      const t = r.test, st = t.possible === true ? `<span class="chip sev-ok">${ic("check", 13)}тестируемо</span>` : t.possible === false ? `<span class="chip sev-critical">${ic("x", 13)}непроверяемо</span>` : `<span class="chip chip-neutral">${ic("pause", 13)}без пробы</span>`;
      const blockF = t.possible === false ? r.findings.find((id) => D.findings[id].source === "тест-проба" || D.findings[id].criterion === "verifiable") : null;
      return `<article class="card tcase ${t.possible === true ? "" : t.possible === false ? "t-bad" : "t-none"}" data-rid="${r.rid}">
        <div class="row wrap" style="gap:8px"><a href="#${r.rid}" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a>${st}<span class="grow"></span>
          <button class="btn btn-sm btn-ghost btn-icon" data-go-doc="${r.rid}" aria-label="Показать ${esc(r.rid)} в документе" title="Показать в документе">${ic("file", 15)}</button>
          ${t.possible === true ? `<button class="btn btn-sm btn-ghost btn-icon" data-copy="${esc(scenarioText(r))}" data-msg="Сценарий скопирован" aria-label="Скопировать сценарий ${esc(r.rid)}" title="Скопировать сценарий">${ic("copy", 15)}</button>` : ""}</div>
        ${r.section ? `<div class="caption" style="margin-top:6px">${esc(r.section)}</div>` : ""}
        <p class="small muted" style="margin-top:6px">${esc(r.text)}</p>
        ${t.possible === true ? `<pre class="code gherkin" style="margin-top:10px">${gherkinHTML(r)}</pre>`
          : t.possible === false ? `<div class="small" style="margin-top:10px"><b>Почему:</b> ${esc(t.reason)}</div>
            ${t.blocker ? `<div class="quote small" style="margin-top:8px">Мешает: «${esc(t.blocker)}»</div>` : ""}
            ${r.rewrite ? `<div class="small" style="margin-top:8px;color:var(--ok)"><b>Чтобы стало тестируемым:</b> <span style="color:var(--text)">${esc(r.rewrite)}</span></div>` : ""}
            ${blockF ? `<button class="btn btn-sm btn-outline" style="margin-top:10px" data-open="${blockF}">Замечание ${ic("arrow-right", 14)}</button>` : ""}`
          : `<p class="small faint" style="margin-top:10px">${esc(r.note || "Тест-проба не выполнялась для этого требования.")}</p>`}</article>`;
    };
    const upd = () => {
      const q = tstate.q.toLowerCase();
      const rs = D.reqs.filter((r) => (tstate.f === "all" || (tstate.f === "ok" && r.test.possible === true) || (tstate.f === "bad" && r.test.possible === false) || (tstate.f === "none" && r.test.possible == null))
        && (!q || (r.rid + " " + (r.doc_id || "") + " " + r.text + " " + (r.test.gherkin || "")).toLowerCase().includes(q)));
      $("#tcount").textContent = `Показано ${rs.length} из ${D.reqs.length}`;
      $("#tlist").innerHTML = rs.map(card).join("") || `<div style="grid-column:1/-1">${empty("Ничего не найдено", "Измените фильтр или запрос.")}</div>`;
    };
    $$("[data-tf]", el).forEach((b) => b.onclick = () => { tstate.f = b.dataset.tf; $$("[data-tf]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $("#tsearch", el).oninput = (e) => { tstate.q = e.target.value; upd(); };
    upd();
  }

  // ------------------------------------------------------------ Исправления: diff было → стало, вопросы аналитику
  function diffSides(c) {
    const before = c.diff.filter((d) => d[0] !== "ins").map((d) => (d[0] === "del" ? `<del>${esc(d[1])}</del>` : esc(d[1]))).join(" ");
    const after = c.diff.filter((d) => d[0] !== "del").map((d) => (d[0] === "ins" ? `<ins>${esc(d[1])}</ins>` : esc(d[1]))).join(" ");
    return [before, after];
  }
  function compareHTML() {
    const c = D.compare; if (!c) return "";
    const lbl = { fixed: ["ok", "исправлено"], improved: ["ok", "улучшено"], new: ["major", "новые"], worse: ["critical", "хуже"], same: ["minor", "без изменений"] };
    return `<div class="card" style="margin-bottom:16px"><div class="card-title">${ic("compare")}<span class="h2 grow">Сравнение с предыдущей версией</span>
        <span class="chip chip-brand">средний балл ${c.score_before} → ${c.score_after}</span> ${deltaChip(c.score_after - c.score_before)}</div>
      <div class="row wrap">${Object.entries(c.counts).map(([k, n]) => `<span class="chip sev-${lbl[k][0]}">${esc(lbl[k][1])}: ${n}</span>`).join("")}${c.removed.length ? `<span class="chip chip-outline">удалено: ${c.removed.length}</span>` : ""}</div>
      <div class="table-wrap" style="margin-top:12px"><table class="tbl"><thead><tr><th>Требование</th><th>Статус</th><th>Балл до</th><th>Балл после</th></tr></thead><tbody>
      ${c.rows.filter((r) => r.status !== "same").map((r) => `<tr><td>${reqById[r.rid] ? `<a href="#${r.rid}" data-go-req="${r.rid}">${esc(r.rid)}${r.doc_id ? " · " + esc(r.doc_id) : ""}</a>` : esc(r.rid)}</td><td>${chip(lbl[r.status][0], lbl[r.status][1])}</td><td>${r.before == null ? "—" : r.before}</td><td>${r.after}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Изменений нет</td></tr>`}</tbody></table></div></div>`;
  }
  function patternHTML(r) {
    const p = r && r.rewrite_pattern; if (!p) return "";
    return `<div class="pattern"><div class="grow"><div class="small"><b>${ic("spark", 13)} По шаблону EARS${p.ears ? ` (${esc(EARS[p.ears] || p.ears)})` : ""}:</b> <code class="mono">${esc(p.template)}</code></div>
        <p class="small" style="margin-top:6px">${esc(p.text)}</p></div>
      <button class="btn btn-sm btn-primary" data-copy="${esc(p.text)}" data-msg="Формулировка по шаблону скопирована">${ic("wand", 14)}Применить шаблон</button></div>`;
  }
  function renderFixes(el) {
    const groups = {}; D.questions.forEach((q) => (groups[q.section || "Без раздела"] = groups[q.section || "Без раздела"] || []).push(q));
    const allFix = D.changes.map((c) => `${c.rid}${c.doc_id ? " (" + c.doc_id + ")" : ""}: ${c.after}`).join("\n\n");
    const allQ = D.questions.map((q, i) => `${i + 1}. [${q.ref}] ${q.text}`).join("\n");
    el.innerHTML = `<div class="section-title" style="margin-top:0"><div><h2 class="h1">Исправления</h2>
        <p class="small muted" style="margin-top:4px">Исходная и исправленная формулировка рядом: удалённое зачёркнуто, добавленное выделено зелёным.</p></div>
        <div class="row wrap no-print">${D.changes.length ? `<button class="btn btn-sm btn-outline" data-copy="${esc(allFix)}" data-msg="Все правки скопированы">${ic("copy", 14)}Скопировать все правки</button>
          <button class="btn btn-sm btn-primary" data-dl="fixed">${ic("download", 14)}Скачать исправленный документ</button>` : ""}</div></div>
      <div class="grid g-3" style="margin-bottom:16px">
        <article class="kpi kpi-hero"><span class="lbl">Исправлено формулировок</span><div class="kpi-num">${num(D.changes.length)}</div><div class="sub">из ${D.reqs.filter((r) => r.findings.length).length} требований с замечаниями</div></article>
        <article class="kpi"><span class="lbl">Балл документа</span><div class="kpi-num">${D.rescore ? `${D.rescore.before} <span class="h2 faint">→</span> <span style="color:var(--ok)">${num(D.rescore.after)}</span>` : num(D.scores.doc)}</div>
          <div class="sub">${D.rescore ? `${deltaChip(D.rescore.after - D.rescore.before)} после повторной проверки` : "повторная оценка — профиль full или --rescore"}</div></article>
        <article class="kpi"><span class="lbl">Вопросы аналитику</span><div class="kpi-num">${num(D.questions.length)}</div><div class="sub">${ic("chat", 14)}закрыть до начала разработки</div></article></div>
      ${compareHTML()}
      <div class="section-title"><h3 class="h2">Было → стало <span class="faint">(${D.changes.length})</span></h3></div>
      ${D.changes.length ? `<div class="stack">${D.changes.map((c) => { const [b, a] = diffSides(c), r = reqById[c.rid]; return `<article class="card fix-card">
        <div class="row wrap" style="gap:8px"><a href="#${c.rid}" data-go-req="${c.rid}"><b>${esc(c.rid)}${c.doc_id ? " · " + esc(c.doc_id) : ""}</b></a>${r ? statusChip(r.worst) : ""}${c.criteria.map((x) => `<span class="chip chip-outline">${esc(x)}</span>`).join("")}
          <span class="grow"></span>${r ? `<button class="btn btn-sm btn-ghost" data-go-doc="${c.rid}">${ic("file", 14)}<span class="hide-sm">В документе</span></button>` : ""}
          <button class="btn btn-sm btn-outline" data-copy="${esc(c.after)}" data-msg="Исправленная формулировка скопирована">${ic("copy", 14)}Скопировать</button></div>
        <div class="diff" style="margin-top:12px"><div class="side side-before"><div class="caption" style="margin-bottom:6px">${ic("x", 12)} Было${r ? ` · ${esc(r.location)}` : ""}</div>${b}</div>
          <div class="side side-after"><div class="caption" style="margin-bottom:6px;color:var(--ok)">${ic("check", 12)} Стало</div>${a}</div></div>${patternHTML(r)}</article>`; }).join("")}</div>`
        : empty("Исправлений нет", D.reqs.some((r) => r.findings.length) ? "Модель не предложила новых формулировок." : "Замечаний не найдено — исправлять нечего.")}
      <div class="section-title" id="questions"><h3 class="h2">Вопросы аналитику <span class="faint">(${D.questions.length})</span></h3>
        ${D.questions.length ? `<div class="row wrap no-print"><button class="btn btn-sm btn-outline" data-copy="${esc(allQ)}" data-msg="Вопросы скопированы">${ic("copy", 14)}Скопировать все</button>
          <button class="btn btn-sm btn-primary" data-dl="questions">${ic("download", 14)}Экспорт в .md</button></div>` : ""}</div>
      ${Object.entries(groups).map(([sec, qs]) => `<div class="card" style="margin-bottom:12px"><div class="caption" style="margin-bottom:8px">${esc(sec)}</div>${qs.map((q) => `<div class="row" style="align-items:flex-start;padding:10px 0;border-top:1px dashed var(--border)">${chip(q.severity)}<div class="grow"><b class="small">${refLinks(q.ref)}</b><p class="small" style="margin-top:2px">${esc(q.text)}</p></div><button class="btn btn-sm btn-ghost btn-icon" aria-label="Скопировать вопрос" data-copy="${esc(q.text)}">${ic("copy", 14)}</button></div>`).join("")}</div>`).join("") || empty("Вопросов нет", "Существенных неопределённостей не найдено.")}`;
  }

  // ------------------------------------------------------------ Трассировка: шаги агента и матрица
  function renderTrace(el) {
    const cell = (r, c) => { const fs = r.findings.map((id) => D.findings[id]).filter((x) => x.criterion === c.key); if (!fs.length) return `<td style="text-align:center"><span class="sr-only">в порядке</span><span style="color:var(--ok)">${ic("check", 14)}</span></td>`; const w = fs.reduce((a, x) => (ORDER[x.severity] < ORDER[a] ? x.severity : a), "minor"); return `<td style="text-align:center"><button class="chip sev-${w}" style="cursor:pointer;border:0" data-open="${fs[0].fid}" title="${esc(SEV[w].label)}">${ic(SEV[w].icon, 12)}${fs.length}</button></td>`; };
    const ears = {}; D.reqs.forEach((r) => { if (r.ears) ears[r.ears] = (ears[r.ears] || 0) + 1; });
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Трассировка</h2></div>
      ${subTabs("trace", [["steps", "Шаги агента", "trace", D.trace.length], ["matrix", "Матрица трассировки", "grid"]])}
      <div class="panel active" data-panel="steps"><div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:start" id="tr-grid">
        <div class="card"><div class="card-title">${ic("trace")}<span class="h2">Шаги агента</span></div>${traceHTML()}</div>
        <div class="stack"><div class="card"><div class="card-title">${ic("spark")}<span class="h2">Шаблоны EARS</span></div>
          ${Object.keys(ears).length ? Object.entries(ears).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<div class="bar-row"><span>${esc(EARS[k] || k)}</span><div class="bar"><i style="width:${(100 * n) / D.reqs.length}%"></i></div><span class="small muted">${n}</span></div>`).join("") : `<p class="small muted">Модель не определила шаблоны.</p>`}</div>
          <div class="card"><div class="card-title">${ic("shield")}<span class="h2">Контроль качества</span></div><dl class="kv">
            <dt>Отброшено цитат</dt><dd>${D.dropped.length}</dd><dt>Отклонено критиком</dt><dd>${D.rejected.length}</dd><dt>Без ответа модели</dt><dd>${D.reqs.filter((r) => !r.llm_checked).length}</dd></dl></div></div></div></div>
      <div class="panel" data-panel="matrix"><div class="table-wrap"><table class="tbl"><thead><tr><th>Требование</th>${D.criteria.map((c) => `<th style="text-align:center" title="${esc(c.ref)}">${esc(c.name.replace(/\s*\(.*\)/, ""))}</th>`).join("")}</tr></thead>
        <tbody>${D.reqs.map((r) => `<tr><td style="white-space:nowrap"><a href="#" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a></td>${D.criteria.map((c) => cell(r, c)).join("")}</tr>`).join("")}</tbody></table></div></div>`;
    wireSub(el, "trace");
  }

  // ------------------------------------------------------------ Экспорт и паспорт
  function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n\n+/).map((p) => `<p class="small" style="margin-bottom:10px">${p}</p>`).join(""); }
  function renderExport(el) {
    const files = [["md", "Отчёт (Markdown)", "Основной отчёт на русском по ТЗ", "file"], ["json", "Данные (JSON)", "Все результаты для интеграций", "layers"],
      ["fixed", "Исправленный документ", `${D.changes.length} исправленных формулировок`, "wand"], ["feature", "tests.feature", `${D.scores.tests_ok} сценариев Gherkin`, "flask"],
      ["questions", "Вопросы аналитику", `${D.questions.length} вопросов, Markdown`, "chat"]];
    const rows = [["Документ", P.document], ["Файл", `${P.file} (${P.format}${P.pages ? ", " + P.pages + " стр." : ""})`], ["SHA-256", P.sha256], ["Дата и время", P.started], ["Модель", P.model],
      ["Версия агента", P.agent_version], ["Профиль / режим", `${P.profile} · ${P.mode}`], ["Обращений к модели", `${P.calls} (повторов: ${P.retries})`],
      ...(P.context_mode ? [["Контекст модели", P.context_mode === "rag" ? `RAG — релевантные фрагменты${P.context_chunks ? ` (${P.context_chunks} на запрос)` : ""}` : "полный документ в каждом запросе"]] : []),
      ...(P.tokens_per_call ? [["Токенов на запрос", "~" + Number(P.tokens_per_call).toLocaleString("ru-RU")]] : []), ["Токены (вход / выход)", P.tokens_in ? `${P.tokens_in} / ${P.tokens_out}` : "—"],
      ["Длительность", P.duration_s + " с"], ["Способ нарезки", { ids: "по идентификаторам документа", modal: "по модальным формулировкам", llm: "моделью" }[P.split_method]],
      ["Критик-агент", P.critic ? "включён" : "выключен"], ["Отброшено неподтверждённых цитат", P.dropped], ["Отклонено критиком", P.rejected], ["Критерии", "ISO/IEC/IEEE 29148:2018 п. 5.2.5, 5.2.6; IEEE Std 830-1998 п. 4.3"]];
    const tbl = (title, items, cols) => items.length ? `<div class="section-title"><h3 class="h2">${title} <span class="faint">(${items.length})</span></h3></div><div class="table-wrap"><table class="tbl"><thead><tr>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${items.map((d) => `<tr>${cols.map((c) => `<td class="small">${esc(d[c[1]])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Экспорт</h2></div>
      <div class="grid g-files">${files.map((f, i) => `<article class="kpi ${i === 0 ? "kpi-hero" : ""}"><div class="row between"><span class="lbl">${f[1]}</span>${ic(f[3], 20)}</div>
        <div class="sub" style="margin:12px 0">${esc(f[2])}</div><button class="btn btn-sm ${i === 0 ? "btn-outline" : "btn-primary"}" style="align-self:flex-start" data-dl="${f[0]}">${ic("download", 14)}Скачать</button></article>`).join("")}</div>
      <div class="grid g-2" style="margin-top:24px;align-items:start">
        <div class="card"><div class="card-title">${ic("id")}<span class="h2">Паспорт прогона</span></div><dl class="kv">${rows.map((r) => `<dt>${r[0]}</dt><dd ${r[0] === "SHA-256" ? 'class="mono"' : ""}>${esc(r[1])}</dd>`).join("")}</dl></div>
        <div class="card"><div class="card-title">${ic("book")}<span class="h2">Методика оценки</span></div>${md(D.method)}
          ${D.notes.length ? `<div class="h3" style="margin:16px 0 8px">Примечания</div>${D.notes.map((n) => `<p class="small" style="color:var(--major)">${ic("alert", 14)} ${esc(n)}</p>`).join("")}` : ""}</div></div>
      ${tbl("Отброшенные замечания модели (цитата не найдена)", D.dropped, [["Где", "where"], ["Цитата модели", "quote"], ["Суть", "problem"]])}
      ${tbl("Отклонены критиком", D.rejected, [["Где", "where"], ["Цитата", "quote"], ["Суть", "problem"], ["Причина", "reason"]])}`;
  }

  function empty(title, text, iconName) {
    return `<div class="empty">${iconName ? `<span class="empty-ic">${ic(iconName, 28)}</span>` : `<svg class="ill" viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="18" y="10" width="64" height="76" rx="10"/><path d="M30 30h40M30 42h40M30 54h24"/><circle cx="82" cy="58" r="16" fill="var(--surface)"/><path d="m94 70 12 12"/></svg>`}
      <div class="h3" style="color:var(--text)">${esc(title)}</div><p class="small" style="margin-top:6px">${esc(text)}</p></div>`;
  }

  function renderKB(el) {
    const top = {}, bySrc = {};
    BASIS_FINDINGS.forEach((f) => f.basis.forEach((b) => {
      const k = b.source + "|" + b.clause, t = (top[k] = top[k] || { b, fids: new Set(), rids: new Set() });
      t.fids.add(f.fid); (f.kind === "req" ? [f.rid] : f.refs.map((x) => x.rid)).forEach((r) => reqById[r] && t.rids.add(r));
      (bySrc[b.source] = bySrc[b.source] || { kind: b.kind, n: 0, url: b.url }).n++;
    }));
    const rows = Object.values(top).sort((a, b) => b.fids.size - a.fids.size || b.rids.size - a.rids.size).slice(0, 10), max = rows.length ? rows[0].fids.size : 1;
    const laws = Object.values(bySrc).filter((x) => x.kind === "law").length, totalF = Object.keys(D.findings).length;
    el.innerHTML = `<div class="section-title" style="margin-top:0"><div><h2 class="h1">База знаний</h2>
        <p class="small muted" style="margin-top:4px">На какие нормы стандартов, законов РК и шаблонов опираются замечания. Каждое основание — фрагмент базы знаний с источником.</p></div></div>
      <div class="grid g-3" style="margin-bottom:16px">
        <article class="kpi kpi-hero"><span class="lbl">Замечаний с основанием</span><div class="kpi-num">${num(BASIS_FINDINGS.length)}<span class="h2" style="opacity:.85"> из ${totalF}</span></div><div class="sub">каждое — с источником и пунктом</div></article>
        <article class="kpi"><span class="lbl">Источников</span><div class="kpi-num">${num(Object.keys(bySrc).length)}</div><div class="sub">${ic("book", 14)}стандарты, законы, шаблоны</div></article>
        <article class="kpi"><span class="lbl">Законов РК</span><div class="kpi-num" style="color:${laws ? "var(--major)" : "var(--text-2)"}">${num(laws)}</div><div class="sub">${ic("shield", 14)}нормативные требования</div></article></div>
      <div class="card"><div class="card-title">${ic("spark")}<span class="h2 grow">Чаще всего нарушены</span><span class="small muted">топ-${rows.length} по числу замечаний</span></div>
        <ol class="kb-top">${rows.map((t, i) => `<li class="kb-row">
          <span class="kb-n">${i + 1}</span>
          <div class="grow" style="min-width:0"><div class="row wrap" style="gap:8px"><span class="chip basis-${t.b.kind}">${ic(BKIND[t.b.kind][1], 13)}${BKIND[t.b.kind][0]}</span><b class="small">${esc(t.b.source)}</b>${t.b.clause ? `<span class="small muted">· ${esc(t.b.clause)}</span>` : ""}</div>
            <div class="bar" style="margin-top:8px" aria-hidden="true"><i style="width:${Math.max(6, (100 * t.fids.size) / max)}%"></i></div>
            <details class="kb-reqs"><summary class="small">${t.fids.size} замеч. · ${t.rids.size} треб. — показать требования</summary>
              <div class="row wrap" style="gap:6px;margin-top:8px">${[...t.rids].map((r) => `<a class="chip chip-outline" href="#${r}" data-go-req="${r}">${esc(label(reqById[r]))}</a>`).join("")}
                ${[...t.fids].filter((x) => x.startsWith("S-")).map((x) => `<a class="chip chip-outline" href="#${x}" data-open="${x}">${x}</a>`).join("")}</div>
              <p class="small muted" style="margin-top:8px">«${esc(short(t.b.quote, 240))}»${t.b.paraphrase ? " — пересказ" : ""}${t.b.url ? ` · <a href="${esc(t.b.url)}" target="_blank" rel="noopener noreferrer">официальный текст</a>` : ""}</p></details></div>
          <b class="kb-count" aria-label="${t.fids.size} замечаний">${t.fids.size}</b></li>`).join("")}</ol></div>
      <div class="section-title"><h3 class="h2">Источники</h3></div>
      <div class="row wrap">${Object.entries(bySrc).sort((a, b) => b[1].n - a[1].n).map(([src, x]) => `<span class="chip basis-${x.kind}" style="height:auto;padding:6px 12px">${ic(BKIND[x.kind][1], 13)}${esc(src)} · ${x.n}${x.url ? ` <a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer" aria-label="Официальный текст: ${esc(src)}">${ic("arrow-up-right", 12)}</a>` : ""}</span>`).join("")}</div>`;
  }

  // ------------------------------------------------------------ U3: покрытие процесса — шаги и покрывающие требования
  function renderCoverage(el) {
    const c = D.coverage, n = c.steps.length;
    el.innerHTML = `<div class="section-title" style="margin-top:0"><div><h2 class="h1">Покрытие процесса</h2>
        <p class="small muted" style="margin-top:4px">${esc(c.process || "Бизнес-процесс")}: какие шаги описаны требованиями, а какие — нет.</p></div>
        <span class="chip ${COV_OK === n ? "sev-ok" : "sev-major"}">${ic(COV_OK === n ? "check" : "alert", 13)}покрыто ${COV_OK} из ${n} шагов</span></div>
      <div class="flowmap" role="list">${c.steps.map((s, i) => `<article class="flow-step ${s.rids.length ? "" : "gap"}" role="listitem">
          <div class="row" style="gap:8px"><span class="flow-n">${i + 1}</span><b class="small grow">${esc(s.title)}</b></div>
          ${s.rids.length ? `<div class="row wrap" style="gap:6px;margin-top:10px">${s.rids.filter((r) => reqById[r]).map((r) => { const q = reqById[r]; return `<a class="chip ${q.worst === "ok" ? "chip-neutral" : "sev-" + q.worst}" href="#${r}" data-go-req="${r}" title="${esc(short(q.text, 120))}">${ic(SEV[q.worst].icon, 12)}${esc(q.doc_id || r)}</a>`; }).join("")}</div>`
            : `<span class="chip sev-critical" style="margin-top:10px">${ic("x", 12)}не покрыто</span>${s.question ? `<p class="small" style="margin-top:8px">${ic("chat", 13)} <b>Вопрос аналитику:</b> ${esc(s.question)}</p>` : ""}`}
        </article>${i < n - 1 ? `<span class="flow-arrow" aria-hidden="true">${ic("arrow-right", 18)}</span>` : ""}`).join("")}</div>
      <div class="legend small muted"><span>${ic("check", 12)} цвет чипа — статус требования</span><span><span class="chip sev-critical" style="height:20px">не покрыто</span> — шаг процесса без требований: пропуск в наборе</span></div>`;
  }

  Object.assign(RENDER, { kb: renderKB, coverage: renderCoverage, overview: renderOverview, reqs: renderReqs, doc: renderDoc, set: renderSet, tests: renderTests, fixes: renderFixes, trace: renderTrace, export: renderExport });

  // ------------------------------------------------------------ горячие клавиши
  const KEYS = [["/", "поиск по требованиям"], ["J / K", "следующий / предыдущий дефект в документе"], ["T", "сменить тему"], ["Esc", "закрыть панель или карточку"], ["1–9", "разделы меню"], ["?", "эта подсказка"]];
  $("#btn-keys").onclick = () => {
    $("#drawer-title").textContent = "Горячие клавиши";
    $("#drawer-body").innerHTML = KEYS.map((k) => `<div class="row between" style="padding:10px 0;border-bottom:1px solid var(--border)"><span>${esc(k[1])}</span><span class="kbd">${esc(k[0])}</span></div>`).join("");
    openDrawer($("#btn-keys"));
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,select,textarea")) { if (e.key === "Escape") e.target.blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") { if (popMark) hidePop(true, true); else { closeDrawer(); $("#sidebar").classList.remove("open"); } }
    else if (e.target.closest("canvas")) return;
    else if (e.key === "/") { e.preventDefault(); $("#gsearch").focus(); }
    else if (e.key === "j" || e.key === "о") stepMark(1);
    else if (e.key === "k" || e.key === "л") stepMark(-1);
    else if (e.key === "t" || e.key === "е") toggleTheme();
    else if (e.key === "?") $("#btn-keys").click();
    else if (/^[1-9]$/.test(e.key) && VIEWS[+e.key - 1]) show(VIEWS[+e.key - 1].id);
  });
  window.addEventListener("beforeprint", () => {
    hidePop(true);
    VIEWS.forEach((v) => renderView(v.id));
    $$("[data-count]").forEach((n) => (n.textContent = n.dataset.count));
    document.dispatchEvent(new CustomEvent("reqlens:print"));
  });

  // ------------------------------------------------------------ API для модулей (report-graph.js) и старт
  window.RL = { D, $, $$, esc, ic, SEV, ORDER, KINDS, REDUCED, chip, statusChip, label, reqById, empty, toast, copy,
    show, goReq, goDocReq, goLine, openFinding, openDrawer, closeDrawer, RENDER, ONSHOW, ONHIDE, get active() { return active; } };
  function start() {
    renderHead();
    $("#footer").innerHTML = `Сформировано агентом ReqLens · ${esc(P.agent_version)} · ${esc(P.started)} · ISO/IEC/IEEE 29148:2018 · IEEE Std 830-1998`;
    const route = () => {
      const h = decodeURIComponent(location.hash.slice(1));
      if (reqById[h]) goReq(h);
      else if (/^L\d+$/.test(h)) goLine(+h.slice(1));
      else if (/^S-\d+$/.test(h) && D.findings[h]) { show("set"); openFinding(h); }
      else show(VIEWS.some((v) => v.id === h) ? h : "overview");
    };
    window.addEventListener("hashchange", route);
    route();
  }
  // модули подключаются следующими <script>; стартуем, когда все они выполнены
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else setTimeout(start, 0);
})();
