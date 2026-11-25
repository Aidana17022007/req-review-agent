/* ReqLens — интерактивный отчёт (структура «AI-агент», светлая зелёная тема). Ванильный JS, без зависимостей. */
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
  const chip = (s, txt) => `<span class="chip sev-${s}">${ic(SEV[s].icon, 13)}${esc(txt || SEV[s].label)}</span>`;
  const scoreColor = (v) => (v >= 80 ? "var(--ok-accent)" : v >= 50 ? "var(--major-accent)" : "var(--critical-accent)");
  const deltaChip = (d) => `<span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? "▲ +" : "▼ "}${d}</span>`;
  const reqById = Object.fromEntries(D.reqs.map((r) => [r.rid, r]));
  const label = (r) => (r.doc_id ? `${r.rid} · ${r.doc_id}` : r.rid);
  const totalFindings = Object.keys(D.findings).length;
  const reqFindings = Object.values(D.findings).filter((f) => f.kind === "req").length;
  const cleanReqs = D.reqs.filter((r) => !r.findings.length).length;
  const P = D.passport;

  // ------------------------------------------------------------ тема, печать, тосты
  function currentTheme() { return document.documentElement.dataset.theme || "light"; }
  function setThemeBtn() { const d = currentTheme() === "dark"; $("#btn-theme").innerHTML = ic(d ? "sun" : "moon") + `<span>${d ? "Светлая тема" : "Тёмная тема"}</span>`; }
  function toggleTheme() {
    const t = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("reqlens-theme", t); } catch (e) { /* storage недоступен */ }
    setThemeBtn();
  }
  $("#btn-theme").onclick = toggleTheme; setThemeBtn();
  $("#btn-print").onclick = () => window.print();
  $("#burger").onclick = () => $("#sidebar").classList.toggle("open");
  let toastT;
  function toast(msg) { const t = $("#toast"); t.innerHTML = ic("check", 16) + esc(msg); t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2200); }
  function copy(text, msg) {
    const done = () => toast(msg || "Скопировано");
    const fallback = () => { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); done(); } catch (e) { toast("Не удалось скопировать"); } ta.remove(); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }
  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: (type || "text/plain") + ";charset=utf-8" }));
    a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    toast("Файл сохранён: " + name);
  }
  const base = String(P.document || "report").replace(/[^\wа-яё\- ]+/gi, "").trim().slice(0, 40).replace(/\s+/g, "_") || "report";
  const DL = {
    md: () => download(`${base}_report.md`, D.report_md || "", "text/markdown"),
    json: () => download(`${base}_data.json`, JSON.stringify(D, null, 2), "application/json"),
    fixed: () => download(`${base}_requirements_fixed.md`, D.fixed_text || "", "text/markdown"),
    feature: () => download(`${base}_acceptance.feature`, D.reqs.filter((r) => r.test.possible).map((r) => `# ${label(r)}\n${r.test.gherkin}`).join("\n\n"), "text/plain"),
  };
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-copy]"); if (c) { e.stopPropagation(); copy(c.dataset.copy, c.dataset.msg); return; }
    const d = e.target.closest("[data-dl]"); if (d) { e.preventDefault(); DL[d.dataset.dl](); return; }
    const r = e.target.closest("[data-go-req]"); if (r) { e.preventDefault(); closeDrawer(); goReq(r.dataset.goReq); return; }
    const l = e.target.closest("[data-go-line]"); if (l) { e.preventDefault(); closeDrawer(); goLine(+l.dataset.goLine); return; }
    const v = e.target.closest("[data-go-view]"); if (v) { e.preventDefault(); show(v.dataset.goView); return; }
    const f = e.target.closest("[data-open]"); if (f) { e.preventDefault(); openFinding(f.dataset.open, f); }
  });

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
    { id: "set", label: "Проверка набора", icon: "layers", count: D.set.length || "" },
    { id: "trace", label: "Трассировка", icon: "trace" },
    { id: "export", label: "Экспорт", icon: "download" },
  ];
  const rendered = {};
  let active = null;
  $("#nav").innerHTML = VIEWS.map((v) => `<button class="nav-item" type="button" data-view="${v.id}">${ic(v.icon)}<span>${v.label}</span>${v.count !== undefined && v.count !== "" ? `<span class="count">${v.count}</span>` : ""}</button>`).join("");
  $("#views").innerHTML = VIEWS.map((v) => `<section class="view" id="view-${v.id}" aria-label="${v.label}"></section>`).join("");
  $("#nav").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) { show(b.dataset.view); history.replaceState(null, "", "#" + b.dataset.view); $("#sidebar").classList.remove("open"); } });
  function show(id) {
    if (!rendered[id]) { RENDER[id]($("#view-" + id)); rendered[id] = true; }
    active = id;
    $$("#nav .nav-item").forEach((b) => (b.dataset.view === id ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + id));
    if (id === "set" && subActive.set === "graph") drawGraph();
  }

  // ------------------------------------------------------------ шапка страницы
  function renderHead() {
    const v = D.verdict;
    $("#top-model").innerHTML = ic("cpu", 13) + esc(P.model);
    $("#pagehead").innerHTML = `<div class="grow">
        <div class="caption">Отчёт о проверке требований</div>
        <h1 class="display" style="margin-top:6px">${esc(P.document)}</h1>
        <div class="meta"><span>${ic("clock", 14)}${esc(P.started)}</span><span>${ic("cpu", 14)}${esc(P.model)}</span>
          <span>${ic("id", 14)}${esc(P.agent_version)}</span><span>${ic("shield", 14)}${esc(P.mode)}</span></div></div>
      <div class="row wrap no-print">
        <button class="btn btn-primary" id="btn-run">${ic("play", 16)}Запустить проверку</button>
        <button class="btn btn-outline" data-dl="md">${ic("download", 16)}Скачать отчёт</button></div>`;
    $("#btn-run").onclick = () => {
      $("#drawer-title").textContent = "Запустить проверку";
      $("#drawer-body").innerHTML = `<p class="muted">Агент работает локально. Чтобы проверить документ заново или другой файл:</p>
        <div><div class="caption" style="margin-bottom:8px">Из командной строки</div>
        <pre class="code">python review.py ${esc(P.file)} reports/report.md --open</pre>
        <button class="btn btn-sm btn-outline" style="margin-top:8px" data-copy="python review.py ${esc(P.file)} reports/report.md --open">${ic("copy", 14)}Скопировать команду</button></div>
        <div><div class="caption" style="margin-bottom:8px">В браузере — ReqLens Studio</div>
        <pre class="code">python -m req_review.web</pre>
        <a class="btn btn-sm btn-primary" style="margin-top:8px" href="http://localhost:8000/" target="_blank" rel="noopener">${ic("arrow-up-right", 14)}Открыть Studio (localhost:8000)</a></div>`;
      openDrawer($("#btn-run"));
    };
  }

  // ------------------------------------------------------------ Обзор
  function kpi(lbl, num, sub, hero, go, tone) {
    return `<article class="kpi ${hero ? "kpi-hero" : ""}">
      <div class="row between"><span class="lbl">${esc(lbl)}</span>
        <button class="arrow-btn" aria-label="${esc(lbl)}: подробнее" data-go-view="${go}">${ic("arrow-up-right", 16)}</button></div>
      <div class="kpi-num"${tone ? ` style="color:${tone}"` : ""}>${num}</div>
      <div class="sub">${sub}</div></article>`;
  }
  function traceHTML() {
    const map = { ok: ["ok", "check", "готово"], warn: ["warn", "alert", "предупреждение"], err: ["err", "x", "ошибка"], skip: ["skip", "pause", "пропущен"] };
    return `<ol class="trace">${D.trace.map((s) => { const m = map[s.status] || map.ok; return `<li class="${m[0]}">
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
  function renderOverview(el) {
    const s = D.scores, v = D.verdict;
    // статус прогона агента (не готовность документа): ЗАВЕРШЁН / ОШИБКА
    const failedSteps = D.trace.filter((t) => t.status === "err").length;
    const agentStatus = failedSteps ? ["st-fail", "x", "ОШИБКА · часть шагов"] : ["st-done", "check", "ЗАВЕРШЁН"];
    const setCrit = D.set.filter((f) => D.findings[f].severity === "critical").length;
    const tPct = s.tests_total ? Math.round((100 * s.tests_ok) / s.tests_total) : 0;
    const crit = D.counts.critical;
    const radar = s.radar_req;
    el.innerHTML = `
      <div class="grid g-4">
        ${kpi("Всего требований", D.reqs.length, `<b>${D.split_method === "ids" ? "ID" : "R"}</b>нарезка ${D.split_method === "ids" ? "по ID документа" : "с номерами агента"}`, true, "reqs")}
        ${kpi("Нарушений", totalFindings, `<b>${reqFindings}</b>по требованиям · <b>${D.set.length}</b>по набору`, false, "reqs")}
        ${kpi("Критичных", crit, `${ic("alert", 14)}непроверяемые, противоречивые, неполные`, false, "reqs", crit ? "var(--critical)" : "var(--ok)")}
        ${kpi("Без замечаний", cleanReqs, `<b>${Math.round((100 * cleanReqs) / Math.max(1, D.reqs.length))}%</b>из ${D.reqs.length} требований`, false, "reqs", "var(--ok)")}
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
                <div class="metric"><div class="kpi-num">${s.readiness}%</div><div class="small muted">готовность документа ${D.rescore ? deltaChip(D.rescore.readiness_after - D.rescore.readiness_before) : ""}</div></div>
                <div class="metric"><div class="kpi-num" style="color:var(--text)">${s.doc}<span class="h3 faint">/100</span></div><div class="small muted">балл качества</div></div>
                <div class="metric"><div class="kpi-num" style="color:var(--text)">${esc(P.duration_s)}<span class="h3 faint"> с</span></div><div class="small muted">время прогона</div></div>
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
                <button class="btn btn-sm btn-ghost" style="align-self:flex-start;margin-top:auto" data-go-view="set">Открыть ${ic("arrow-right", 14)}</button></div></article>
            <article class="mini"><div class="vis">${sphere(110, 150, 140, 11, { r: 0.34, lineEvery: 6, color: "var(--brand-light)" })}</div>
              <div class="body"><span class="status ${tPct >= 80 ? "st-done" : "st-warn"}" style="align-self:flex-start">${ic("flask", 11)}ТЕСТ-ПРОБА ${tPct}%</span>
                <div class="h3">Приёмочные тесты</div><div class="small muted">${s.tests_ok} из ${s.tests_total} требований можно проверить тестом</div>
                <button class="btn btn-sm btn-ghost" style="align-self:flex-start;margin-top:auto" data-go-view="trace">Открыть ${ic("arrow-right", 14)}</button></div></article>
          </div>
          ${profileHTML()}
        </div>
        <div class="col-fill">
          <div class="card"><div class="card-title">${ic("trace")}<span class="h2 grow">Трассировка агента</span><span class="chip chip-brand">${D.trace.filter((t) => t.status !== "skip").length}/${D.trace.length}</span></div>${traceHTML()}</div>
          ${D.changes.length ? `<div class="card" style="display:flex;gap:14px;align-items:center"><span class="logo-mark" style="border-radius:14px;flex:none">${ic("wand")}</span>
            <div class="grow"><div class="caption">Исправленный документ</div><div class="small muted">${D.changes.length} формулировок исправлено${D.rescore ? ` · балл ${D.rescore.before} → ${D.rescore.after}` : ""}</div></div>
            <button class="btn btn-round" data-dl="fixed" aria-label="Скачать исправленный документ">${ic("download", 16)}</button></div>` : ""}
          ${setSummaryHTML()}
        </div>
      </div>
      <div class="section-title"><h2 class="h1">Требования</h2><div class="row"><span class="small muted hide-sm">${D.reqs.length} шт.</span>
        <button class="btn btn-sm btn-outline" data-go-view="reqs">Все фильтры ${ic("arrow-right", 14)}</button></div></div>
      ${reqTable(D.reqs, "ov")}
      <div style="margin-top:16px">${verdictHTML(true)}</div>`;
    wireTable(el);
  }

  // ------------------------------------------------------------ таблица требований (Health Status)
  function critDots(r) {
    return `<div class="crit-dots" aria-label="Критерии">${D.criteria.map((c) => {
      const fs = r.findings.map((id) => D.findings[id]).filter((x) => x.criterion === c.key);
      const s = fs.length ? fs.reduce((a, x) => (ORDER[x.severity] < ORDER[a] ? x.severity : a), "minor") : "ok";
      const tip = `${D.criteria.indexOf(c) + 1}. ${c.name}: ${s === "ok" ? "в порядке" : SEV[s].label.toLowerCase()}`;
      return `<i title="${esc(tip)}" style="background:${s === "ok" ? "var(--neutral-bar)" : SEV[s].color}"></i>`;
    }).join("")}</div>`;
  }
  // нейтральный вид для «чистых» требований: серый круг 100 и бейдж без заливки
  const statusChip = (s) => (s === "ok" ? `<span class="chip chip-neutral">${ic("check", 13)}Без замечаний</span>` : chip(s));
  const ring = (v) => `<div class="mini-ring" style="--v:${v};--c:${v >= 100 ? "var(--neutral-bar)" : scoreColor(v)}"><span${v >= 100 ? ' style="color:var(--text-2);font-weight:600"' : ""}>${v}</span></div>`;
  const critLegend = () => `<div class="crit-legend small muted" aria-label="Легенда колонки «Критерии»">
    <span><b>Критерии</b> (слева направо): ${D.criteria.map((c, i) => `${i + 1}. ${esc(c.name.replace(/\s*\(.*\)/, ""))}`).join(" · ")}</span>
    <span class="row" style="gap:12px"><span><i style="background:var(--neutral-bar)"></i>в порядке</span><span><i style="background:${SEV.minor.color}"></i>незначит.</span><span><i style="background:${SEV.major.color}"></i>существ.</span><span><i style="background:${SEV.critical.color}"></i>критичное</span><span>· наведите на квадратик</span></span></div>`;
  function gherkin(g) { return esc(g).replace(/^(\s*)(Дано|Когда|Тогда|И|Но|Given|When|Then|And|But)(:?)/gm, "$1<b>$2$3</b>"); }
  function expandHTML(r) {
    const t = r.test;
    return `<div class="inner stack">
      <div><div class="caption" style="margin-bottom:6px">Цитата из документа · <a href="#L${r.line}" data-go-line="${r.line}">${esc(r.location)}</a></div><div class="quote">${esc(r.text)}</div></div>
      ${r.note ? `<div class="small" style="color:var(--major)">${ic("alert", 14)} ${esc(r.note)}</div>` : ""}
      ${r.findings.length ? `<div>${r.findings.map((id) => { const f = D.findings[id]; return `<div class="finding" data-open="${id}" tabindex="0">
        ${chip(f.severity)}<div><div class="f-title">${esc(f.cname)} <span class="faint small">· ${esc(f.cref)}</span></div>
        <div class="small muted" style="margin-top:2px">«${esc(f.quote)}» — ${esc(f.problem)}</div>
        <div class="small" style="margin-top:4px"><b>Как исправить:</b> ${esc(f.fix)}</div></div></div>`; }).join("")}</div>` : `<div class="small" style="color:var(--ok)">${ic("check", 14)} Нарушений не найдено.</div>`}
      ${r.rewrite && r.findings.length ? `<div class="row" style="padding:12px 16px;border-radius:14px;background:var(--ok-soft)">
        <div class="grow small"><b style="color:var(--ok)">Предлагаемая правка:</b> ${esc(r.rewrite)}</div>
        <button class="btn btn-sm btn-outline" data-copy="${esc(r.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}Копировать</button></div>` : ""}
      ${t.possible === true ? `<details class="more"><summary>${ic("flask", 14)} Тест-проба: приёмочный тест составлен</summary><pre class="code gherkin" style="margin-top:8px">${gherkin(t.gherkin)}</pre></details>`
        : t.possible === false ? `<div class="small" style="color:var(--critical)">${ic("flask", 14)} <b>Тест составить невозможно:</b> ${esc(t.reason)} — мешает «${esc(t.blocker)}»</div>` : ""}
    </div>`;
  }
  function reqTable(rows, key) {
    if (!rows.length) return empty("Ничего не найдено", "Измените фильтры или запрос.");
    return `${critLegend()}<div class="table-wrap"><table class="tbl" data-tbl="${key}"><thead><tr>
      <th scope="col">ID в отчёте</th><th scope="col">ID в документе</th><th scope="col">Краткая формулировка</th>
      <th scope="col" title="${esc(D.criteria.map((c, i) => `${i + 1}. ${c.name}`).join("\n"))}">Критерии ⓘ</th><th scope="col">Балл</th><th scope="col">Статус</th><th scope="col"><span class="sr-only">Действия</span></th></tr></thead>
      <tbody>${rows.map((r) => `<tr class="rrow" data-rid="${r.rid}" id="row-${key}-${r.rid}">
        <td><b>${esc(r.rid)}</b></td><td>${r.doc_id ? `<span class="chip chip-brand">${esc(r.doc_id)}</span>` : `<span class="small faint">присвоен агентом</span>`}</td>
        <td style="min-width:260px;max-width:460px">${esc(r.text.length > 120 ? r.text.slice(0, 117) + "…" : r.text)}</td>
        <td>${critDots(r)}</td>
        <td>${ring(r.score)}</td>
        <td>${statusChip(r.worst)}</td>
        <td><button class="btn btn-sm btn-outline" data-exp="${r.rid}" aria-expanded="false" aria-controls="exp-${key}-${r.rid}">Подробнее ${ic("chevron", 14)}</button></td></tr>
        <tr class="exp" id="exp-${key}-${r.rid}" hidden><td colspan="7">${expandHTML(r)}</td></tr>`).join("")}</tbody></table></div>`;
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

  // ------------------------------------------------------------ Требования: фильтры + таблица / документ
  const qstate = { q: "", sev: "all", crit: "", section: "", sort: "order", mode: "table" };
  function renderReqs(el) {
    const sections = [...new Set(D.reqs.map((r) => r.section).filter(Boolean))];
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Требования</h2>
        <div class="seg" role="group" aria-label="Вид"><button data-mode="table" aria-pressed="true">${ic("list", 14)} Таблица</button><button data-mode="doc" aria-pressed="false">${ic("file", 14)} В документе</button></div></div>
      <div class="toolbar" id="req-filters">
        <div class="seg" role="group" aria-label="Серьёзность">${["all", "critical", "major", "minor", "ok"].map((k) => `<button data-sev="${k}" aria-pressed="${k === "all"}">${k === "all" ? "Все" : SEV[k].label}</button>`).join("")}</div>
        <select class="input" id="fcrit" style="width:auto" aria-label="Критерий"><option value="">Все критерии</option>${D.criteria.map((c) => `<option value="${c.key}">${esc(c.name)}</option>`).join("")}</select>
        ${sections.length > 1 ? `<select class="input" id="fsec" style="width:auto;max-width:240px" aria-label="Раздел"><option value="">Все разделы</option>${sections.map((s) => `<option>${esc(s)}</option>`).join("")}</select>` : ""}
        <div class="seg" role="group" aria-label="Сортировка"><button data-sort="order" aria-pressed="true">По порядку</button><button data-sort="score" aria-pressed="false">Сначала худшие</button></div>
        <span class="small faint" id="req-count"></span></div>
      <div id="req-body"></div><div id="doc-body" hidden></div>`;
    const upd = () => {
      let rs = D.reqs.filter((r) => {
        if (qstate.sev !== "all" && r.worst !== qstate.sev) return false;
        if (qstate.crit && !r.crit.includes(qstate.crit)) return false;
        if (qstate.section && r.section !== qstate.section) return false;
        if (qstate.q) {
          const hay = (r.rid + " " + (r.doc_id || "") + " " + r.text + " " + r.findings.map((id) => D.findings[id].quote + " " + D.findings[id].problem).join(" ")).toLowerCase();
          if (!hay.includes(qstate.q.toLowerCase())) return false;
        }
        return true;
      });
      if (qstate.sort === "score") rs = rs.slice().sort((a, b) => a.score - b.score);
      $("#req-count").textContent = `Показано ${rs.length} из ${D.reqs.length}`;
      $("#req-body").innerHTML = reqTable(rs, "rq");
    };
    $$("[data-sev]", el).forEach((b) => b.onclick = () => { qstate.sev = b.dataset.sev; $$("[data-sev]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $$("[data-sort]", el).forEach((b) => b.onclick = () => { qstate.sort = b.dataset.sort; $$("[data-sort]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $$("[data-mode]", el).forEach((b) => b.onclick = () => setMode(b.dataset.mode));
    $("#fcrit", el).onchange = (e) => { qstate.crit = e.target.value; upd(); };
    if ($("#fsec", el)) $("#fsec", el).onchange = (e) => { qstate.section = e.target.value; upd(); };
    wireTable($("#req-body", el));
    renderDocInto($("#doc-body", el));
    reqUpdate = upd;
    upd();
  }
  let reqUpdate = () => {};
  function setMode(m) {
    show("reqs"); qstate.mode = m;
    $$("#view-reqs [data-mode]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.mode === m));
    $("#req-body").hidden = m !== "table"; $("#req-filters").hidden = m !== "table"; $("#doc-body").hidden = m !== "doc";
  }
  function goReq(rid) {
    show("reqs"); setMode("table");
    if (!$(`#row-rq-${CSS.escape(rid)}`)) { qstate.q = ""; qstate.sev = "all"; qstate.crit = ""; qstate.section = ""; $("#gsearch").value = ""; reqUpdate(); }
    const tr = expandRow(rid, "rq");
    if (tr) { tr.scrollIntoView({ behavior: "smooth", block: "center" }); }
  }
  $("#gsearch").addEventListener("input", (e) => { show("reqs"); setMode("table"); qstate.q = e.target.value; reqUpdate(); });

  // ------------------------------------------------------------ документ с подсветкой (Grammarly)
  const md_ = (s) => esc(s).replace(/(\*\*|__|^\s*[-*•]\s|\|)/g, '<span class="md">$1</span>');
  function lineHTML(l) {
    const ms = D.marks[l.n] || [], t = l.t;
    if (!ms.length) return md_(t) || "&nbsp;";
    let out = "", pos = 0;
    ms.forEach(([s, e, fid, sev, kind]) => {
      if (s < pos) return;
      const f = D.findings[fid];
      out += md_(t.slice(pos, s)) + `<mark class="hl ${sev} ${kind === "set" ? "set" : ""}" data-f="${fid}" tabindex="0" title="${esc(SEV[sev].label)} · ${esc(f.cname)}: ${esc(f.problem).slice(0, 140)}">${md_(t.slice(s, e))}</mark>`;
      pos = e;
    });
    return out + md_(t.slice(pos));
  }
  const sevFilter = { critical: true, major: true, minor: true };
  function renderDocInto(el) {
    el.innerHTML = `<div class="toolbar no-print">${["critical", "major", "minor"].map((k) => `<button class="pill" aria-pressed="true" data-sevf="${k}">${ic(SEV[k].icon, 13)}${SEV[k].label} · ${D.counts[k]}</button>`).join("")}
        <span class="grow"></span><span class="small faint">Нажмите на подчёркнутый фрагмент · <span class="kbd">J</span> <span class="kbd">K</span> — следующий / предыдущий</span></div>
      <div class="docview"><div class="doc" id="doc">${D.lines.map((l) => `<div class="ln ${l.h ? "h" : ""}" id="L${l.n}"><span class="n">${l.n}</span><span class="t">${lineHTML(l)}</span></div>`).join("")}</div>
      <div class="minimap no-print" id="minimap" aria-hidden="true"></div></div>`;
    const total = D.lines.length || 1;
    $("#minimap", el).innerHTML = Object.entries(D.marks).map(([n, ms]) => { const w = ms.reduce((a, m) => (ORDER[m[3]] < ORDER[a] ? m[3] : a), "minor"); return `<i class="${w}" style="top:${(100 * (n - 1)) / total}%" data-line="${n}"></i>`; }).join("");
    $("#minimap", el).onclick = (e) => { const i = e.target.closest("i"); if (i) goLine(+i.dataset.line); };
    el.addEventListener("click", (e) => { const m = e.target.closest("mark.hl:not(.off)"); if (m) openFinding(m.dataset.f, m); });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { const m = e.target.closest("mark.hl"); if (m) openFinding(m.dataset.f, m); } });
    $$("[data-sevf]", el).forEach((b) => b.onclick = () => {
      const k = b.dataset.sevf; sevFilter[k] = !sevFilter[k]; b.setAttribute("aria-pressed", sevFilter[k]);
      $$("mark.hl." + k, el).forEach((m) => m.classList.toggle("off", !sevFilter[k]));
      $$("#minimap i." + k, el).forEach((m) => (m.style.display = sevFilter[k] ? "" : "none"));
    });
  }
  function goLine(n) {
    setMode("doc");
    const l = $("#L" + n); if (!l) return;
    l.scrollIntoView({ behavior: "smooth", block: "center" });
    l.classList.remove("flash"); void l.offsetWidth; l.classList.add("flash");
  }
  let markIdx = -1;
  function stepMark(dir) {
    setMode("doc");
    const ms = $$("#doc mark.hl:not(.off)"); if (!ms.length) return;
    markIdx = (markIdx + dir + ms.length) % ms.length;
    ms[markIdx].scrollIntoView({ behavior: "smooth", block: "center" }); openFinding(ms[markIdx].dataset.f, ms[markIdx]);
  }

  // ------------------------------------------------------------ Drawer
  let lastFocus = null;
  function openDrawer(from) {
    lastFocus = from || document.activeElement;
    $("#drawer").classList.add("open"); $("#overlay").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawer-close").focus({ preventScroll: true });
  }
  function closeDrawer() {
    $("#drawer").classList.remove("open"); $("#overlay").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true");
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }
  $("#drawer-close").onclick = closeDrawer; $("#overlay").onclick = closeDrawer;
  function openFinding(fid, from) {
    const f = D.findings[fid]; if (!f) return;
    $$("mark.hl.active").forEach((m) => m.classList.remove("active")); $$(`mark.hl[data-f="${fid}"]`).forEach((m) => m.classList.add("active"));
    const conf = CONF[f.confidence];
    const where = f.kind === "req"
      ? `<a href="#" data-go-req="${f.rid}">${esc(label(reqById[f.rid]))}</a> · ${esc(f.location)}${f.line ? ` · <a href="#" data-go-line="${f.line}">строка ${f.line}</a>` : ""}`
      : f.refs.map((x) => (x.rid !== "DOC" ? `<a href="#" data-go-req="${x.rid}">${esc(x.label)}</a>` : "документ")).join(", ");
    $("#drawer-title").textContent = f.kind === "set" ? `${f.fid} · ${f.cname}` : f.cname;
    $("#drawer-body").innerHTML = `<div class="row wrap">${chip(f.severity)}<span class="chip chip-outline">${esc(f.cref)}</span>
        ${conf ? `<span class="chip ${conf[1]}">${ic("shield", 13)}уверенность: ${conf[0]}</span>` : ""}<span class="chip">${esc(f.source)}</span></div>
      <div class="small muted">${where}</div>
      ${f.kind === "req" ? `<div><div class="caption" style="margin-bottom:6px">Цитата из документа</div><div class="quote">«${esc(f.quote)}»</div></div>`
        : `<div><div class="caption" style="margin-bottom:6px">Цитаты</div>${f.refs.map((x) => `<div class="quote" style="margin-bottom:8px"><b>${esc(x.label)}:</b> «${esc(x.quote)}»</div>`).join("")}</div>`}
      <div><div class="caption" style="margin-bottom:6px">Нарушенный критерий</div><p><b>${esc(f.cname)}</b> — ${esc(f.cref)}</p></div>
      <div><div class="caption" style="margin-bottom:6px">Объяснение</div><p>${esc(f.problem)}</p></div>
      <div><div class="caption" style="margin-bottom:6px">Как исправить</div><p>${esc(f.fix)}</p></div>
      ${f.rewrite ? `<div class="card" style="padding:16px;background:var(--ok-soft);border-color:transparent"><div class="row between"><div class="caption" style="color:var(--ok)">Предложенная правка</div>
        <button class="btn btn-sm btn-outline" data-copy="${esc(f.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}Копировать</button></div><p style="margin-top:8px">${esc(f.rewrite)}</p></div>` : ""}
      ${f.critic ? `<div class="small muted">${ic("shield", 14)} Критик: ${esc(f.critic)}</div>` : ""}`;
    openDrawer(from);
  }

  // ------------------------------------------------------------ Проверка набора
  const subActive = { set: "findings", trace: "tests" };
  function subTabs(view, tabs) {
    return `<div class="tabs" role="tablist">${tabs.map((t) => `<button class="tab" role="tab" data-sub="${view}:${t[0]}" aria-selected="${subActive[view] === t[0]}">${ic(t[2], 15)}${t[1]}${t[3] !== undefined ? `<span class="count">${t[3]}</span>` : ""}</button>`).join("")}</div>`;
  }
  function wireSub(el, view) {
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-sub]"); if (!b) return;
      const [, id] = b.dataset.sub.split(":"); subActive[view] = id;
      $$("[data-sub]", el).forEach((x) => x.setAttribute("aria-selected", x === b));
      $$(".panel", el).forEach((p) => p.classList.toggle("active", p.dataset.panel === id));
      if (id === "graph") drawGraph();
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
  function renderSet(el) {
    const kinds = { contradiction: "Противоречие", duplicate: "Дублирование", terminology: "Терминология", gap: "Пропуск", dependency: "Зависимость", structure: "Структура", other: "Прочее" };
    const list = D.set.map((fid) => { const f = D.findings[fid]; return `<article class="card" style="padding:20px">
      <div class="row wrap"><b>${fid}</b><span class="chip chip-outline">${esc(kinds[f.set_kind] || f.set_kind)}</span>${chip(f.severity)}<span class="chip">${esc(f.cname)}</span>
        <span class="grow"></span><button class="btn btn-sm btn-ghost" data-open="${fid}">Подробнее ${ic("arrow-right", 14)}</button></div>
      <p style="margin:10px 0">${esc(f.problem)}</p>
      ${f.refs.map((x) => `<div class="quote small" style="margin-top:6px">${x.rid !== "DOC" ? `<a href="#" data-go-req="${x.rid}"><b>${esc(x.label)}</b></a>` : "<b>документ</b>"}: «${esc(x.quote)}»</div>`).join("")}
      <p class="small muted" style="margin-top:10px"><b>Как исправить:</b> ${esc(f.fix)}</p></article>`; }).join("");
    const d = D.domain, g = D.glossary;
    const st = { covered: ["ok", "покрыта"], partial: ["major", "частично"], missing: ["critical", "не покрыта"] };
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Проверка набора целиком</h2><span class="chip chip-brand">балл набора ${D.scores.set}/100</span></div>
      <div class="grid" style="grid-template-columns:minmax(0,360px) minmax(0,1fr);align-items:start;margin-bottom:16px" id="set-top">
        <div class="card"><div class="card-title">${ic("spark")}<span class="h2">Профиль набора</span></div>${radarSVG(D.scores.radar_set, 300)}
          <p class="small faint">ISO/IEC/IEEE 29148 §5.2.6 и IEEE 830 §4.3.</p></div>
        <div class="grid g-2" style="align-content:start">${D.set_criteria.map((c) => `<div class="card" style="padding:16px">
          <div class="row between"><span class="caption">${esc(c.ref)}</span>${c.count ? chip(c.worst, `${c.count}`) : chip("ok", "ок")}</div>
          <div class="h3" style="margin:6px 0 2px">${esc(c.name)}</div><p class="small muted">${esc(c.desc)}</p></div>`).join("")}</div></div>
      ${subTabs("set", [["findings", "Замечания", "alert", D.set.length], ["graph", "Граф связей", "graph", D.graph.edges.length], ["domain", "Финтех-полнота", "bank", d ? d.coverage + "%" : undefined], ["glossary", "Глоссарий", "book", g ? g.terms.length : undefined]])}
      <div class="panel ${subActive.set === "findings" ? "active" : ""}" data-panel="findings"><div class="stack">${list || empty("Нарушений на уровне набора нет", "Противоречий, дублей и пропусков не найдено.")}</div></div>
      <div class="panel" data-panel="graph"><p class="small muted" style="margin-bottom:12px">Узлы — требования (цвет — худшее замечание). Колёсико — масштаб, перетаскивание — сдвиг, клик — к требованию.</p>
        <div class="graph-wrap"><svg id="gsvg" role="img" aria-label="Граф связей требований"></svg>
        <div class="graph-legend"><span><i style="border-color:#D64545"></i>противоречие</span><span><i style="border-color:#3FA06B;border-top-style:dashed"></i>дубль</span><span><i style="border-color:var(--text-3)"></i>ссылка</span><span><i style="border-color:#1F6B45;border-top-width:1px"></i>термин</span></div></div></div>
      <div class="panel" data-panel="domain">${d ? `<div class="card" style="margin-bottom:16px"><div class="row wrap" style="gap:24px"><div><div class="caption">${esc(d.name)}</div><div class="kpi-num">${d.coverage}%</div><div class="small muted">покрытие чек-листа</div></div>
          <div class="grow small muted">${esc(d.disclaimer)}</div></div></div>
        <div class="grid g-3">${d.areas.map((a) => `<div class="card" style="padding:16px"><div class="row between"><b class="small">${esc(a.title)}</b>${chip(st[a.status][0], st[a.status][1])}</div>
          ${a.quotes.length ? a.quotes.map((q) => `<div class="quote small" style="margin-top:8px">«${esc(q)}»</div>`).join("") : `<p class="small muted" style="margin-top:8px">${ic("chat", 14)} ${esc(a.question)}</p>`}</div>`).join("")}</div>` : empty("Домен отключён", "Запустите с --domain fintech.")}</div>
      <div class="panel" data-panel="glossary">${g ? `${g.synonyms.map((s) => `<div class="card" style="padding:14px 18px;background:var(--major-soft);border-color:transparent;margin-bottom:10px">${ic("alert", 14)} <b>Разнобой терминов:</b> ${s.terms.map((t) => `<span class="chip chip-outline">${esc(t)}</span>`).join(" ")} → «${esc(s.preferred)}». <span class="small muted">${esc(s.problem)}</span></div>`).join("")}
        <div class="table-wrap"><table class="tbl"><thead><tr><th>Термин</th><th>Определение</th><th>Упоминаний</th><th>Требования</th></tr></thead><tbody>
        ${g.terms.map((t) => `<tr><td><b>${esc(t.term)}</b></td><td>${t.defined ? esc(t.definition) : chip("major", "не определён")}</td><td>${t.count}</td><td class="small">${t.reqs.slice(0, 8).map((r) => `<a href="#" data-go-req="${r}">${esc(reqById[r] ? reqById[r].doc_id || r : r)}</a>`).join(", ")}</td></tr>`).join("")}</tbody></table></div>` : empty("Нет данных", "Глоссарий не построен.")}</div>`;
    wireSub(el, "set");
  }

  // ------------------------------------------------------------ граф (force-directed, без библиотек)
  let graphDrawn = false;
  function drawGraph() {
    const svg = $("#gsvg"); if (!svg || graphDrawn || !svg.clientWidth) return; graphDrawn = true;
    const W = svg.clientWidth, H = svg.clientHeight || 560;
    const nodes = D.graph.nodes.map((n, i) => ({ ...n, x: W / 2 + Math.cos(i) * (100 + i * 6), y: H / 2 + Math.sin(i) * (100 + i * 6), vx: 0, vy: 0 }));
    const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
    const edges = D.graph.edges.filter((e) => e.source in idx && e.target in idx);
    for (let it = 0; it < 420; it++) {
      const al = 1 - it / 420;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy || 1, f = (2600 / d2) * al, d = Math.sqrt(d2); dx /= d; dy /= d;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
      edges.forEach((e) => { const a = nodes[idx[e.source]], b = nodes[idx[e.target]], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - 110) * 0.02 * al; a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f; });
      nodes.forEach((n) => { n.vx += (W / 2 - n.x) * 0.004 * al; n.vy += (H / 2 - n.y) * 0.006 * al; n.x += n.vx; n.y += n.vy; n.vx *= 0.6; n.vy *= 0.6; });
    }
    const col = { critical: "#D64545", major: "#B7791F", minor: "#B8A532", ok: "#1F9D55" };
    const est = { contradiction: 'stroke="#D64545" stroke-width="2.5"', duplicate: 'stroke="#3FA06B" stroke-width="2" stroke-dasharray="6 5"', dependency: 'stroke="var(--text-3)" stroke-width="1.5"', term: 'stroke="#1F6B45" stroke-width="1" opacity=".6"' };
    let g = `<g id="gview">`;
    edges.forEach((e) => { const a = nodes[idx[e.source]], b = nodes[idx[e.target]]; g += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" ${est[e.kind]}><title>${esc(e.title)}</title></line>`; });
    nodes.forEach((n) => { const r = 14 + Math.min(10, n.degree * 3); g += `<g class="node" data-rid="${n.id}" transform="translate(${n.x},${n.y})" tabindex="0" role="button" aria-label="${esc(n.label)}"><circle r="${r}" fill="${col[n.severity]}" opacity="${n.degree ? 1 : 0.55}"><title>${esc(n.label)}: ${esc(n.text)}</title></circle><text y="${r + 14}" text-anchor="middle">${esc(n.label)}</text></g>`; });
    svg.innerHTML = g + "</g>";
    let k = 1, tx = 0, ty = 0, drag = null; const view = $("#gview"), apply = () => view.setAttribute("transform", `translate(${tx},${ty}) scale(${k})`);
    svg.addEventListener("wheel", (e) => { e.preventDefault(); const nk = Math.min(4, Math.max(0.3, k * (e.deltaY < 0 ? 1.12 : 0.89))), r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top; tx = mx - ((mx - tx) * nk) / k; ty = my - ((my - ty) * nk) / k; k = nk; apply(); }, { passive: false });
    svg.addEventListener("pointerdown", (e) => { if (e.target.closest(".node")) return; drag = [e.clientX - tx, e.clientY - ty]; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener("pointermove", (e) => { if (drag) { tx = e.clientX - drag[0]; ty = e.clientY - drag[1]; apply(); } });
    svg.addEventListener("pointerup", () => (drag = null));
    svg.addEventListener("click", (e) => { const n = e.target.closest(".node"); if (n) goReq(n.dataset.rid); });
    svg.addEventListener("keydown", (e) => { if (e.key === "Enter") { const n = e.target.closest(".node"); if (n) goReq(n.dataset.rid); } });
  }

  // ------------------------------------------------------------ Трассировка: тесты, матрица, вопросы
  function renderTrace(el) {
    const ok = D.reqs.filter((r) => r.test.possible === true), bad = D.reqs.filter((r) => r.test.possible === false), s = D.scores;
    const pct = s.tests_total ? Math.round((100 * s.tests_ok) / s.tests_total) : 0;
    const groups = {}; D.questions.forEach((q) => (groups[q.section] = groups[q.section] || []).push(q));
    const allQ = D.questions.map((q, i) => `${i + 1}. [${q.ref}] ${q.text}`).join("\n");
    const cell = (r, c) => { const fs = r.findings.map((id) => D.findings[id]).filter((x) => x.criterion === c.key); if (!fs.length) return `<td style="text-align:center"><span class="sr-only">в порядке</span><span style="color:var(--ok)">${ic("check", 14)}</span></td>`; const w = fs.reduce((a, x) => (ORDER[x.severity] < ORDER[a] ? x.severity : a), "minor"); return `<td style="text-align:center"><button class="chip sev-${w}" style="cursor:pointer;border:0" data-open="${fs[0].fid}" title="${esc(SEV[w].label)}">${ic(SEV[w].icon, 12)}${fs.length}</button></td>`; };
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Трассировка</h2></div>
      <div class="grid g-3" style="margin-bottom:16px">
        <article class="kpi kpi-hero"><span class="lbl">Тест-проба</span><div class="kpi-num">${pct}%</div><div class="sub">${s.tests_ok} из ${s.tests_total} требований можно проверить тестом</div></article>
        <article class="kpi"><span class="lbl">Тест составить невозможно</span><div class="kpi-num" style="color:${bad.length ? "var(--critical)" : "var(--ok)"}">${bad.length}</div><div class="sub">${ic("flask", 14)}доказательство непроверяемости</div></article>
        <article class="kpi"><span class="lbl">Вопросы заказчику</span><div class="kpi-num">${D.questions.length}</div><div class="sub">${ic("chat", 14)}закрыть до начала разработки</div></article></div>
      ${subTabs("trace", [["tests", "Тест-кейсы", "flask", `${s.tests_ok}/${s.tests_total}`], ["matrix", "Матрица трассировки", "grid"], ["questions", "Вопросы заказчику", "chat", D.questions.length]])}
      <div class="panel active" data-panel="tests">
        ${bad.length ? `<div class="grid g-2" style="margin-bottom:16px">${bad.map((r) => `<div class="card"><div class="row"><a href="#" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a>${chip("critical", "непроверяемо")}</div>
          <p class="small muted" style="margin:8px 0">${esc(r.text)}</p><div class="small"><b>Почему:</b> ${esc(r.test.reason)}</div><div class="quote small" style="margin-top:8px">Мешает: «${esc(r.test.blocker)}»</div></div>`).join("")}</div>` : ""}
        ${ok.length ? `<div class="toolbar"><button class="btn btn-sm btn-outline" data-dl="feature">${ic("download", 14)}Скачать .feature</button></div>
          <div class="grid g-2">${ok.map((r) => `<div class="card"><div class="row"><a href="#" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a>${chip("ok", "тест есть")}</div><pre class="code gherkin" style="margin-top:10px">${gherkin(r.test.gherkin)}</pre></div>`).join("")}</div>` : ""}
        ${!ok.length && !bad.length ? empty("Тест-проба не выполнялась", "Запустите прогон без флага --no-tests.") : ""}</div>
      <div class="panel" data-panel="matrix"><div class="table-wrap"><table class="tbl"><thead><tr><th>Требование</th>${D.criteria.map((c) => `<th style="text-align:center" title="${esc(c.ref)}">${esc(c.name.replace(/\s*\(.*\)/, ""))}</th>`).join("")}</tr></thead>
        <tbody>${D.reqs.map((r) => `<tr><td style="white-space:nowrap"><a href="#" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a></td>${D.criteria.map((c) => cell(r, c)).join("")}</tr>`).join("")}</tbody></table></div></div>
      <div class="panel" data-panel="questions"><div class="toolbar"><span class="grow small muted">Сформированы из замечаний — отправьте до начала разработки.</span>
        <button class="btn btn-primary btn-sm" data-copy="${esc(allQ)}" data-msg="Вопросы скопированы">${ic("copy", 14)}Скопировать все</button></div>
        ${Object.entries(groups).map(([sec, qs]) => `<div class="card" style="margin-bottom:12px"><div class="caption" style="margin-bottom:8px">${esc(sec)}</div>${qs.map((q) => `<div class="row" style="align-items:flex-start;padding:10px 0;border-top:1px dashed var(--border)">${chip(q.severity)}<div class="grow"><b class="small">${esc(q.ref)}</b><p class="small" style="margin-top:2px">${esc(q.text)}</p></div><button class="btn btn-sm btn-ghost btn-icon" aria-label="Скопировать вопрос" data-copy="${esc(q.text)}">${ic("copy", 14)}</button></div>`).join("")}</div>`).join("") || empty("Вопросов нет", "Существенных неопределённостей не найдено.")}</div>`;
    wireSub(el, "trace");
  }

  // ------------------------------------------------------------ Экспорт и паспорт
  function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n\n+/).map((p) => `<p class="small" style="margin-bottom:10px">${p}</p>`).join(""); }
  function renderExport(el) {
    const files = [["md", "Отчёт (Markdown)", "Основной отчёт на русском по ТЗ", "file"], ["json", "Данные (JSON)", "Все результаты для интеграций", "layers"],
      ["fixed", "Исправленный документ", `${D.changes.length} исправленных формулировок`, "wand"], ["feature", "Приёмочные тесты", `${D.scores.tests_ok} сценариев Gherkin`, "flask"]];
    const rows = [["Документ", P.document], ["Файл", `${P.file} (${P.format}${P.pages ? ", " + P.pages + " стр." : ""})`], ["SHA-256", P.sha256], ["Дата и время", P.started], ["Модель", P.model],
      ["Версия агента", P.agent_version], ["Профиль / режим", `${P.profile} · ${P.mode}`], ["Обращений к модели", `${P.calls} (повторов: ${P.retries})`], ["Токены (вход / выход)", P.tokens_in ? `${P.tokens_in} / ${P.tokens_out}` : "—"],
      ["Длительность", P.duration_s + " с"], ["Способ нарезки", { ids: "по идентификаторам документа", modal: "по модальным формулировкам", llm: "моделью" }[P.split_method]],
      ["Критик-агент", P.critic ? "включён" : "выключен"], ["Отброшено неподтверждённых цитат", P.dropped], ["Отклонено критиком", P.rejected], ["Критерии", "ISO/IEC/IEEE 29148:2018 п. 5.2.5, 5.2.6; IEEE Std 830-1998 п. 4.3"]];
    const tbl = (title, items, cols) => items.length ? `<div class="section-title"><h3 class="h2">${title} <span class="faint">(${items.length})</span></h3></div><div class="table-wrap"><table class="tbl"><thead><tr>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${items.map((d) => `<tr>${cols.map((c) => `<td class="small">${esc(d[c[1]])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Экспорт</h2></div>
      <div class="grid g-4">${files.map((f, i) => `<article class="kpi ${i === 0 ? "kpi-hero" : ""}"><div class="row between"><span class="lbl">${f[1]}</span>${ic(f[3], 20)}</div>
        <div class="sub" style="margin:12px 0">${esc(f[2])}</div><button class="btn btn-sm ${i === 0 ? "btn-outline" : "btn-primary"}" style="align-self:flex-start" data-dl="${f[0]}">${ic("download", 14)}Скачать</button></article>`).join("")}</div>
      ${D.changes.length ? `<div class="section-title"><h3 class="h2">Было → стало ${D.rescore ? `<span class="chip chip-brand">балл ${D.rescore.before} → ${D.rescore.after}</span>` : ""}</h3></div>
        <div class="stack">${D.changes.map((c) => `<article class="card"><div class="row wrap"><a href="#" data-go-req="${c.rid}"><b>${esc(c.rid)}${c.doc_id ? " · " + esc(c.doc_id) : ""}</b></a>${c.criteria.map((x) => `<span class="chip chip-outline">${esc(x)}</span>`).join("")}
          <span class="grow"></span><button class="btn btn-sm btn-ghost" data-copy="${esc(c.after)}">${ic("copy", 14)}Копировать</button></div>
          <div class="diff" style="margin-top:12px"><div class="side"><div class="caption" style="margin-bottom:6px">Было</div>${c.diff.filter((d) => d[0] !== "ins").map((d) => (d[0] === "del" ? `<del>${esc(d[1])}</del>` : esc(d[1]))).join(" ")}</div>
          <div class="side"><div class="caption" style="margin-bottom:6px">Стало</div>${c.diff.filter((d) => d[0] !== "del").map((d) => (d[0] === "ins" ? `<ins>${esc(d[1])}</ins>` : esc(d[1]))).join(" ")}</div></div></article>`).join("")}</div>` : ""}
      <div class="grid g-2" style="margin-top:24px;align-items:start">
        <div class="card"><div class="card-title">${ic("id")}<span class="h2">Паспорт прогона</span></div><dl class="kv">${rows.map((r) => `<dt>${r[0]}</dt><dd ${r[0] === "SHA-256" ? 'class="mono"' : ""}>${esc(r[1])}</dd>`).join("")}</dl></div>
        <div class="card"><div class="card-title">${ic("book")}<span class="h2">Методика оценки</span></div>${md(D.method)}
          ${D.notes.length ? `<div class="h3" style="margin:16px 0 8px">Примечания</div>${D.notes.map((n) => `<p class="small" style="color:var(--major)">${ic("alert", 14)} ${esc(n)}</p>`).join("")}` : ""}</div></div>
      ${tbl("Отброшенные замечания модели (цитата не найдена)", D.dropped, [["Где", "where"], ["Цитата модели", "quote"], ["Суть", "problem"]])}
      ${tbl("Отклонены критиком", D.rejected, [["Где", "where"], ["Цитата", "quote"], ["Суть", "problem"], ["Причина", "reason"]])}`;
  }

  function empty(title, text) {
    return `<div class="empty"><svg class="ill" viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2"><rect x="18" y="10" width="64" height="76" rx="10"/><path d="M30 30h40M30 42h40M30 54h24"/><circle cx="82" cy="58" r="16" fill="var(--surface)"/><path d="m94 70 12 12"/></svg>
      <div class="h3" style="color:var(--text)">${esc(title)}</div><p class="small" style="margin-top:6px">${esc(text)}</p></div>`;
  }

  const RENDER = { overview: renderOverview, reqs: renderReqs, set: renderSet, trace: renderTrace, export: renderExport };

  // ------------------------------------------------------------ горячие клавиши
  const KEYS = [["/", "поиск по требованиям"], ["J / K", "следующий / предыдущий дефект в документе"], ["T", "сменить тему"], ["Esc", "закрыть панель"], ["1–5", "разделы меню"]];
  $("#btn-keys").onclick = () => {
    $("#drawer-title").textContent = "Горячие клавиши";
    $("#drawer-body").innerHTML = KEYS.map((k) => `<div class="row between" style="padding:10px 0;border-bottom:1px solid var(--border)"><span>${esc(k[1])}</span><span class="kbd">${esc(k[0])}</span></div>`).join("");
    openDrawer($("#btn-keys"));
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,select,textarea")) { if (e.key === "Escape") e.target.blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") { closeDrawer(); $("#sidebar").classList.remove("open"); }
    else if (e.key === "/") { e.preventDefault(); $("#gsearch").focus(); }
    else if (e.key === "j" || e.key === "о") stepMark(1);
    else if (e.key === "k" || e.key === "л") stepMark(-1);
    else if (e.key === "t" || e.key === "е") toggleTheme();
    else if (e.key === "?") $("#btn-keys").click();
    else if (/^[1-5]$/.test(e.key)) show(VIEWS[+e.key - 1].id);
  });
  window.addEventListener("beforeprint", () => VIEWS.forEach((v) => { if (!rendered[v.id]) { RENDER[v.id]($("#view-" + v.id)); rendered[v.id] = true; } }));

  // ------------------------------------------------------------ старт
  renderHead();
  $("#footer").innerHTML = `Сформировано агентом ReqLens · ${esc(P.agent_version)} · ${esc(P.started)} · ISO/IEC/IEEE 29148:2018 · IEEE Std 830-1998`;
  const route = () => {
    const h = decodeURIComponent(location.hash.slice(1));
    if (reqById[h]) goReq(h); else if (/^L\d+$/.test(h)) goLine(+h.slice(1)); else show(VIEWS.some((v) => v.id === h) ? h : "overview");
  };
  window.addEventListener("hashchange", route);
  route();
})();
