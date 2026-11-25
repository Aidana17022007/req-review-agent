/* ReqLens — интерактивный отчёт. Ванильный JS, без внешних зависимостей. */
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("data").textContent);
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ic = (n, s = 18) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;
  const SEV = {
    critical: { label: "Критичный", short: "критичных", color: "#E5484D" },
    major: { label: "Существенный", short: "существенных", color: "#F59E0B" },
    minor: { label: "Незначительный", short: "незначительных", color: "#EAB308" },
    ok: { label: "Без замечаний", short: "без замечаний", color: "#12B76A" },
  };
  const ORDER = { critical: 0, major: 1, minor: 2, ok: 3 };
  const EARS = { ubiquitous: "постоянное", event: "по событию", state: "по состоянию", unwanted: "нежелательное поведение", optional: "опциональное", complex: "составное" };
  const CONF = { high: ["Высокая", "sev-ok"], medium: ["Средняя", "chip-brand"], low: ["Низкая", ""] };
  const chip = (s, txt) => `<span class="chip sev-${s}"><span class="dot"></span>${esc(txt || SEV[s].label)}</span>`;
  const deltaChip = (d) => `<span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? "▲ +" : "▼ "}${d}</span>`;
  const scoreColor = (v) => (v >= 80 ? "var(--ok-accent)" : v >= 50 ? "var(--major-accent)" : "#E5484D");
  const reqById = Object.fromEntries(D.reqs.map((r) => [r.rid, r]));
  const label = (r) => (r.doc_id ? `${r.rid} · ${r.doc_id}` : r.rid);
  const totalFindings = Object.keys(D.findings).length;

  // ------------------------------------------------------------ тема
  const themeBtn = $("#btn-theme");
  function currentTheme() {
    const t = document.documentElement.dataset.theme;
    if (t) return t;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function setThemeIcon() { themeBtn.innerHTML = ic(currentTheme() === "dark" ? "sun" : "moon"); }
  function toggleTheme() {
    const t = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("reqlens-theme", t); } catch (e) { /* файл открыт без доступа к storage */ }
    setThemeIcon();
  }
  themeBtn.onclick = toggleTheme;
  setThemeIcon();
  $("#btn-print").onclick = () => window.print();

  // ------------------------------------------------------------ toast
  let toastT;
  function toast(msg) {
    const t = $("#toast");
    t.innerHTML = ic("check", 16) + esc(msg);
    t.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(() => t.classList.remove("show"), 2200);
  }
  function copy(text, msg) {
    const done = () => toast(msg || "Скопировано");
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
    function fallback() {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("Не удалось скопировать"); }
      ta.remove();
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (b) { e.stopPropagation(); copy(b.dataset.copy, b.dataset.msg); }
  });

  // ------------------------------------------------------------ hero
  function gauge(v) {
    const r = 100, len = Math.PI * r, off = len * (1 - v / 100);
    return `<div class="gauge" role="img" aria-label="Готовность к разработке ${v}%">
      <svg viewBox="0 0 240 140"><defs><linearGradient id="gg" x1="0" x2="1">
        <stop offset="0" stop-color="#E5484D"/><stop offset=".55" stop-color="#F59E0B"/><stop offset="1" stop-color="#12B76A"/></linearGradient></defs>
        <path d="M20 120 A100 100 0 0 1 220 120" fill="none" stroke="var(--surface-2)" stroke-width="18" stroke-linecap="round"/>
        <path class="arc" d="M20 120 A100 100 0 0 1 220 120" fill="none" stroke="url(#gg)" stroke-width="18" stroke-linecap="round"
          stroke-dasharray="${len}" stroke-dashoffset="${len}" data-off="${off}"/>
      </svg>
      <div class="g-val"><div class="g-num" style="color:${scoreColor(v)}">${v}<span style="font-size:22px">%</span></div>
      <div class="g-lbl">готовность к разработке</div></div></div>`;
  }
  function stat(lbl, v, extra, tone) {
    return `<div class="stat"><div class="caption">${esc(lbl)}</div><div class="v"${tone ? ` style="color:${tone}"` : ""}>${v}${extra || ""}</div></div>`;
  }
  function renderHero() {
    const s = D.scores, v = D.verdict, p = D.passport;
    const vcls = { critical: "sev-critical", major: "sev-major", ok: "sev-ok" }[v.level];
    const vic = { critical: "alert", major: "alert", ok: "check" }[v.level];
    let delta = "";
    if (D.rescore) delta = `<div class="row wrap" style="margin-top:16px"><span class="chip chip-brand">${ic("wand", 14)} после исправлений</span>
      <span class="h3">${D.rescore.before} → <span style="color:${D.rescore.after >= D.rescore.before ? "var(--ok)" : "var(--critical)"}">${D.rescore.after}</span></span>
      ${deltaChip(D.rescore.after - D.rescore.before)}</div>`;
    if (D.compare) {
      const d = D.compare.score_after - D.compare.score_before;
      delta += `<div class="row wrap" style="margin-top:12px"><span class="chip">к прошлой версии</span>
        <span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? "▲ +" : "▼ "}${d}</span>
        <span class="small muted">исправлено ${D.compare.counts.fixed}, новых ${D.compare.counts.new}, хуже ${D.compare.counts.worse}</span></div>`;
    }
    const crit = D.counts.critical, ready = s.ready.length;
    $("#hero").innerHTML = `<div class="hero-grid">
      <div>${gauge(s.readiness)}</div>
      <div>
        <div class="caption">Итог проверки</div>
        <h2 class="display" style="margin:8px 0 12px">${esc(v.title)}</h2>
        <span class="verdict ${vcls}">${ic(vic, 16)}${esc(v.text)}</span>
        ${delta}
        <div class="grid g-4" style="margin-top:24px">
          ${stat("Требований", D.reqs.length)}
          ${stat("Нарушений", totalFindings)}
          ${stat("Критичных", crit, "", crit ? "var(--critical)" : "var(--ok)")}
          ${stat("Готово к работе", ready, `<small>из ${D.reqs.length}</small>`)}
        </div>
      </div>
      <div class="passport-mini card" style="padding:16px 18px">
        <div class="row between"><div class="caption">Паспорт прогона</div>
          <span class="chip chip-brand">${esc(p.profile)}</span></div>
        <dl class="kv" style="grid-template-columns:96px 1fr;margin-top:12px">
          <dt>Балл документа</dt><dd><b style="font-size:18px">${s.doc}</b><span class="faint"> / 100</span></dd>
          <dt>Модель</dt><dd>${esc(p.model)}</dd>
          <dt>Агент</dt><dd>${esc(p.agent_version)}</dd>
          <dt>Дата</dt><dd>${esc(p.started)}</dd>
          <dt>Режим</dt><dd>${esc(p.mode)}</dd>
          <dt>SHA-256</dt><dd class="mono" title="${esc(p.sha256)}">${esc(String(p.sha256).slice(0, 16))}…</dd>
        </dl></div></div>`;
    requestAnimationFrame(() => setTimeout(() => { const a = $(".gauge .arc"); if (a) a.style.strokeDashoffset = a.dataset.off; }, 60));
  }

  // ------------------------------------------------------------ обзор: радар, тест-проба, цена дефекта
  function radar(items, size = 300) {
    const n = items.length, c = size / 2, R = size / 2 - 64;
    const pt = (i, v) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / n; return [c + Math.cos(a) * R * v, c + Math.sin(a) * R * v]; };
    let g = "";
    [0.25, 0.5, 0.75, 1].forEach((k) => { g += `<polygon points="${items.map((_, i) => pt(i, k).join(",")).join(" ")}" fill="none" stroke="var(--border)"/>`; });
    items.forEach((_, i) => { const [x, y] = pt(i, 1); g += `<line x1="${c}" y1="${c}" x2="${x}" y2="${y}" stroke="var(--border)"/>`; });
    const poly = items.map((it, i) => pt(i, Math.max(0.02, it.v / 100)).join(",")).join(" ");
    g += `<polygon points="${poly}" fill="color-mix(in srgb,var(--brand) 20%,transparent)" stroke="var(--brand)" stroke-width="2" stroke-linejoin="round"/>`;
    items.forEach((it, i) => {
      const [x, y] = pt(i, Math.max(0.02, it.v / 100));
      g += `<circle cx="${x}" cy="${y}" r="3.5" fill="var(--brand)"><title>${esc(it.name)}: ${it.v}%</title></circle>`;
      const [lx, ly] = pt(i, 1.2);
      const anchor = Math.abs(lx - c) < 8 ? "middle" : lx > c ? "start" : "end";
      const words = it.name.replace(/\s*\(.*\)/, "").split(" ");
      const lines = words.length > 1 && it.name.length > 14 ? [words.slice(0, Math.ceil(words.length / 2)).join(" "), words.slice(Math.ceil(words.length / 2)).join(" ")] : [words.join(" ")];
      g += `<text x="${lx}" y="${ly - (lines.length - 1) * 6}" text-anchor="${anchor}" dominant-baseline="middle">${lines.map((l, k) => `<tspan x="${lx}" dy="${k ? 12 : 0}">${esc(l)}</tspan>`).join("")}</text>`;
    });
    return `<svg class="radar" viewBox="-56 -6 ${size + 112} ${size + 12}" role="img" aria-label="Профиль качества по критериям">${g}</svg>`;
  }
  function renderOverview() {
    const s = D.scores;
    const tPct = s.tests_total ? Math.round((100 * s.tests_ok) / s.tests_total) : 0;
    const maxCost = Math.max(1, ...s.cost.map((c) => c[1]));
    const sevBars = ["critical", "major", "minor"].map((k) => {
      const n = D.counts[k], pct = totalFindings ? (100 * n) / totalFindings : 0;
      return `<div class="bar-row" style="grid-template-columns:120px 1fr 32px"><span>${chip(k)}</span><div class="bar"><i style="width:${pct}%;background:${SEV[k].color}"></i></div><b>${n}</b></div>`;
    }).join("");
    $("#overview").innerHTML = `
      <div class="card"><div class="card-title">${ic("spark")}<span class="h3">Профиль качества</span></div>
        ${radar(s.radar_req)}<p class="small faint">Доля требований без нарушений по каждому критерию ISO/IEC/IEEE 29148 §5.2.5.</p></div>
      <div class="card"><div class="card-title">${ic("flask")}<span class="h3">Тест-проба</span></div>
        <div class="row" style="align-items:baseline"><span class="display">${s.tests_ok}</span><span class="h3 faint">/ ${s.tests_total}</span>
        <span class="chip ${tPct >= 80 ? "sev-ok" : tPct >= 50 ? "sev-major" : "sev-critical"}">${tPct}%</span></div>
        <p class="small muted" style="margin:8px 0 16px">требований, для которых агент смог написать приёмочный тест Given/When/Then. Для остальных тест составить невозможно — это доказательство непроверяемости.</p>
        <div class="bar" style="height:10px"><i style="width:${tPct}%;background:var(--ok-accent)"></i></div>
        <div style="margin-top:24px">${sevBars}</div></div>
      <div class="card"><div class="card-title">${ic("bank")}<span class="h3">Цена дефекта</span></div>
        <p class="small muted" style="margin-bottom:12px">Сколько часов уйдёт на исправление найденных дефектов в зависимости от того, когда их обнаружат (ориентировочно).</p>
        ${s.cost.map((c, i) => `<div class="bar-row" style="grid-template-columns:150px 1fr 64px"><span class="small">${esc(c[0])}</span>
          <div class="bar"><i style="width:${Math.max(2, (100 * c[1]) / maxCost)}%;background:${i === 0 ? "var(--ok-accent)" : i === 3 ? "#E5484D" : "var(--major-accent)"}"></i></div>
          <b class="small" style="text-align:right">${c[1]} ч</b></div>`).join("")}
        <p class="small faint" style="margin-top:12px">Исправить сейчас в ~100 раз дешевле, чем после релиза.</p></div>`;
  }

  // ------------------------------------------------------------ вкладки
  const TABS = [
    { id: "doc", label: "Документ", icon: "file", count: totalFindings },
    { id: "reqs", label: "Требования", icon: "list", count: D.reqs.length },
    { id: "set", label: "Набор", icon: "layers", count: D.set.length },
    { id: "graph", label: "Граф", icon: "graph", count: D.graph.edges.length },
    { id: "tests", label: "Тесты", icon: "flask", count: `${D.scores.tests_ok}/${D.scores.tests_total}` },
    { id: "fixed", label: "Исправленный документ", icon: "wand", count: D.changes.length },
    { id: "questions", label: "Вопросы заказчику", icon: "chat", count: D.questions.length },
    { id: "domain", label: "Домен и глоссарий", icon: "bank", count: D.domain ? D.domain.coverage + "%" : "" },
    { id: "passport", label: "Паспорт", icon: "id", count: "" },
  ];
  const rendered = {};
  function renderTabs() {
    $("#tabs").innerHTML = TABS.map((t) => `<button class="tab" role="tab" id="tab-${t.id}" aria-controls="panel-${t.id}" aria-selected="false" data-tab="${t.id}">
      ${ic(t.icon, 16)}${esc(t.label)}${t.count !== "" ? `<span class="count">${esc(t.count)}</span>` : ""}</button>`).join("");
    $("#panels").innerHTML = TABS.map((t) => `<section class="panel" role="tabpanel" id="panel-${t.id}" aria-labelledby="tab-${t.id}"></section>`).join("");
    $("#tabs").addEventListener("click", (e) => { const b = e.target.closest(".tab"); if (b) { show(b.dataset.tab); history.replaceState(null, "", "#" + b.dataset.tab); } });
    $("#tabs").addEventListener("keydown", (e) => {
      if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
      const ids = TABS.map((t) => t.id), i = ids.indexOf(active);
      const n = ids[(i + (e.key === "ArrowRight" ? 1 : ids.length - 1)) % ids.length];
      show(n); $("#tab-" + n).focus();
    });
  }
  let active = null;
  function show(id) {
    if (!rendered[id]) { RENDER[id]($("#panel-" + id)); rendered[id] = true; }
    active = id;
    TABS.forEach((t) => {
      $("#tab-" + t.id).setAttribute("aria-selected", t.id === id);
      $("#tab-" + t.id).tabIndex = t.id === id ? 0 : -1;
      $("#panel-" + t.id).classList.toggle("active", t.id === id);
    });
    if (id === "graph") drawGraph();
  }

  // ------------------------------------------------------------ Документ
  // разметка Markdown в исходном тексте показывается приглушённо (смещения меток не меняются)
  const md_ = (s) => esc(s).replace(/(\*\*|__|^\s*[-*•]\s|\|)/g, '<span class="md">$1</span>');
  function lineHTML(l) {
    const ms = D.marks[l.n] || [];
    const t = l.t;
    if (!ms.length) return md_(t) || "&nbsp;";
    let out = "", pos = 0;
    ms.forEach(([s, e, fid, sev, kind]) => {
      if (s < pos) return;
      const f = D.findings[fid];
      out += md_(t.slice(pos, s)) + `<mark class="hl ${sev} ${kind === "set" ? "set" : ""}" data-f="${fid}" tabindex="0" title="${esc(f.cname)}: ${esc(f.problem).slice(0, 140)}">${md_(t.slice(s, e))}</mark>`;
      pos = e;
    });
    return out + md_(t.slice(pos));
  }
  const sevFilter = { critical: true, major: true, minor: true };
  function renderDoc(el) {
    el.innerHTML = `<div class="toolbar no-print">
        ${["critical", "major", "minor"].map((k) => `<button class="pill" aria-pressed="true" data-sev="${k}"><span class="chip sev-${k}" style="height:18px;padding:0 6px">${D.counts[k]}</span>${SEV[k].label}</button>`).join("")}
        <span class="grow"></span>
        <span class="small faint">Нажмите на подчёркнутый фрагмент · <span class="kbd">J</span> <span class="kbd">K</span> — следующий / предыдущий дефект</span></div>
      <div class="docview"><div class="doc" id="doc">${D.lines.map((l) => `<div class="ln ${l.h ? "h" : ""}" id="L${l.n}"><span class="n">${l.n}</span><span class="t">${lineHTML(l)}</span></div>`).join("")}</div>
      <div class="minimap no-print" id="minimap" aria-hidden="true"></div></div>`;
    const total = D.lines.length || 1;
    $("#minimap", el).innerHTML = Object.entries(D.marks).map(([n, ms]) => {
      const worst = ms.reduce((a, m) => (ORDER[m[3]] < ORDER[a] ? m[3] : a), "minor");
      return `<i class="${worst}" style="top:${(100 * (n - 1)) / total}%" data-line="${n}" title="Строка ${n}"></i>`;
    }).join("");
    $("#minimap", el).onclick = (e) => { const i = e.target.closest("i"); if (i) goLine(+i.dataset.line); };
    el.addEventListener("click", (e) => { const m = e.target.closest("mark.hl"); if (m) openFinding(m.dataset.f, m); });
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { const m = e.target.closest("mark.hl"); if (m) openFinding(m.dataset.f, m); } });
    $$(".pill[data-sev]", el).forEach((b) => b.onclick = () => {
      const k = b.dataset.sev; sevFilter[k] = !sevFilter[k]; b.setAttribute("aria-pressed", sevFilter[k]);
      $$("mark.hl." + k, el).forEach((m) => m.classList.toggle("off", !sevFilter[k]));
      $$("#minimap i." + k, el).forEach((m) => (m.style.display = sevFilter[k] ? "" : "none"));
    });
  }
  function goLine(n) {
    show("doc");
    const l = $("#L" + n);
    if (!l) return;
    l.scrollIntoView({ behavior: "smooth", block: "center" });
    l.classList.remove("flash"); void l.offsetWidth; l.classList.add("flash");
  }
  let markIdx = -1;
  function stepMark(dir) {
    show("doc");
    const ms = $$("#doc mark.hl:not(.off)");
    if (!ms.length) return;
    markIdx = (markIdx + dir + ms.length) % ms.length;
    const m = ms[markIdx];
    m.scrollIntoView({ behavior: "smooth", block: "center" });
    openFinding(m.dataset.f, m);
  }

  // ------------------------------------------------------------ Drawer
  let lastFocus = null;
  function openFinding(fid, from) {
    const f = D.findings[fid];
    if (!f) return;
    lastFocus = from || document.activeElement;
    $$("mark.hl.active").forEach((m) => m.classList.remove("active"));
    $$(`mark.hl[data-f="${fid}"]`).forEach((m) => m.classList.add("active"));
    const conf = CONF[f.confidence];
    let where;
    if (f.kind === "req") {
      const r = reqById[f.rid];
      where = `<a href="#${f.rid}" data-go-req="${f.rid}">${esc(label(r))}</a> · ${esc(f.location)}${f.line ? ` · <a href="#L${f.line}" data-go-line="${f.line}">строка ${f.line}</a>` : ""}`;
    } else {
      where = f.refs.map((x) => x.rid !== "DOC" ? `<a href="#${x.rid}" data-go-req="${x.rid}">${esc(x.label)}</a>` : "документ").join(", ");
    }
    $("#drawer-title").textContent = f.kind === "set" ? `${f.fid} · ${f.cname}` : f.cname;
    $("#drawer-body").innerHTML = `
      <div class="row wrap">${chip(f.severity)}<span class="chip">${esc(f.cref)}</span>
        ${conf ? `<span class="chip ${conf[1]}">${ic("shield", 13)}уверенность: ${conf[0]}</span>` : ""}
        <span class="chip">${esc(f.source)}</span></div>
      <div class="small muted">${where}</div>
      ${f.kind === "req" ? `<div><div class="caption" style="margin-bottom:6px">Цитата из документа</div><div class="quote">«${esc(f.quote)}»</div></div>`
        : `<div><div class="caption" style="margin-bottom:6px">Цитаты</div>${f.refs.map((x) => `<div class="quote" style="margin-bottom:8px"><b>${esc(x.label)}:</b> «${esc(x.quote)}»</div>`).join("")}</div>`}
      <div><div class="caption" style="margin-bottom:6px">Проблема</div><p>${esc(f.problem)}</p></div>
      <div><div class="caption" style="margin-bottom:6px">Как исправить</div><p>${esc(f.fix)}</p></div>
      ${f.rewrite ? `<div class="card" style="padding:14px;background:var(--ok-soft);border-color:transparent">
        <div class="row between"><div class="caption" style="color:var(--ok)">Предлагаемая формулировка</div>
        <button class="btn btn-sm btn-secondary" data-copy="${esc(f.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}Скопировать</button></div>
        <p style="margin-top:8px">${esc(f.rewrite)}</p></div>` : ""}
      ${f.critic ? `<div class="small muted">${ic("shield", 14)} Критик: ${esc(f.critic)}</div>` : ""}`;
    $("#drawer").classList.add("open"); $("#overlay").classList.add("open");
    $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawer-close").focus({ preventScroll: true });
  }
  function closeDrawer() {
    $("#drawer").classList.remove("open"); $("#overlay").classList.remove("open");
    $("#drawer").setAttribute("aria-hidden", "true");
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }
  $("#drawer-close").onclick = closeDrawer;
  $("#overlay").onclick = closeDrawer;
  document.addEventListener("click", (e) => {
    const r = e.target.closest("[data-go-req]");
    if (r) { e.preventDefault(); closeDrawer(); goReq(r.dataset.goReq); return; }
    const l = e.target.closest("[data-go-line]");
    if (l) { e.preventDefault(); closeDrawer(); goLine(+l.dataset.goLine); return; }
    const f = e.target.closest("[data-open]");
    if (f) { e.preventDefault(); openFinding(f.dataset.open, f); }
  });

  // ------------------------------------------------------------ Требования
  const qstate = { q: "", sev: "all", crit: "", section: "", sort: "order" };
  function reqCard(r) {
    const crits = D.criteria.map((c) => {
      const f = r.findings.map((id) => D.findings[id]).filter((x) => x.criterion === c.key);
      const s = f.length ? f.reduce((a, x) => (ORDER[x.severity] < ORDER[a] ? x.severity : a), "minor") : "ok";
      return `<span data-tip="${esc(c.name)}" style="display:inline-block;width:14px;height:14px;border-radius:4px;background:${s === "ok" ? "var(--ok-soft)" : SEV[s].color}"></span>`;
    }).join("");
    const t = r.test;
    let test = "";
    if (t.possible === true) test = `<details class="more" style="margin-top:12px"><summary>${ic("flask", 14)} Тест-проба: приёмочный тест составлен</summary>
      <pre class="code gherkin" style="margin-top:8px">${gherkin(t.gherkin)}</pre></details>`;
    else if (t.possible === false) test = `<div class="small" style="margin-top:12px;color:var(--critical)">${ic("flask", 14)} <b>Тест составить невозможно:</b> ${esc(t.reason)} — мешает «${esc(t.blocker)}»</div>`;
    return `<article class="card req" id="${r.rid}" data-rid="${r.rid}">
      <div class="req-head">
        <div class="score-ring" style="--v:${r.score};--c:${scoreColor(r.score)}" role="img" aria-label="Балл ${r.score}"><span>${r.score}</span></div>
        <div class="grow">
          <div class="row wrap"><span class="req-id">${esc(r.rid)}</span>${r.doc_id ? `<span class="chip chip-brand">${esc(r.doc_id)}</span>` : `<span class="chip">ID присвоен агентом</span>`}
            ${chip(r.worst)}${r.ears ? `<span class="chip">EARS: ${esc(EARS[r.ears] || r.ears)}</span>` : ""}</div>
          <div class="small faint" style="margin-top:4px"><a href="#L${r.line}" data-go-line="${r.line}">${esc(r.location)}</a></div>
        </div>
        <div class="row" style="gap:3px" aria-label="Профиль по критериям">${crits}</div>
      </div>
      <div class="quote" style="margin-top:14px">${esc(r.text)}</div>
      ${r.note ? `<div class="small" style="margin-top:8px;color:var(--major)">${esc(r.note)}</div>` : ""}
      ${r.findings.map((id) => { const f = D.findings[id]; return `<div class="finding" data-open="${id}" tabindex="0">
        <span class="chip sev-${f.severity}"><span class="dot"></span></span>
        <div><div class="f-title">${esc(f.cname)} <span class="faint small">· ${esc(f.cref)}</span></div>
        <div class="small muted">«${esc(f.quote)}» — ${esc(f.problem)}</div></div></div>`; }).join("")}
      ${r.rewrite && r.findings.length ? `<div class="row" style="margin-top:12px;padding:12px 14px;border-radius:12px;background:var(--ok-soft)">
        <div class="grow small"><b style="color:var(--ok)">Предлагаемая формулировка:</b> ${esc(r.rewrite)}</div>
        <button class="btn btn-sm btn-secondary" data-copy="${esc(r.rewrite)}" data-msg="Формулировка скопирована">${ic("copy", 14)}</button></div>` : ""}
      ${test}</article>`;
  }
  function gherkin(g) {
    return esc(g).replace(/^(\s*)(Дано|Когда|Тогда|И|Но|Given|When|Then|And|But)(:?)/gm, "$1<b>$2$3</b>");
  }
  function renderReqs(el) {
    const sections = [...new Set(D.reqs.map((r) => r.section).filter(Boolean))];
    el.innerHTML = `<div class="toolbar">
      <label class="search"><span class="sr-only">Поиск</span>${ic("search", 16)}<input id="q" type="search" placeholder="Поиск по тексту, ID, цитате…  ( / )"></label>
      <div class="seg" role="group" aria-label="Серьёзность">${["all", "critical", "major", "minor", "ok"].map((k) => `<button data-sev="${k}" aria-pressed="${k === "all"}">${k === "all" ? "Все" : SEV[k].label}</button>`).join("")}</div>
      <select class="input" id="fcrit" style="width:auto" aria-label="Критерий"><option value="">Все критерии</option>${D.criteria.map((c) => `<option value="${c.key}">${esc(c.name)}</option>`).join("")}</select>
      ${sections.length > 1 ? `<select class="input" id="fsec" style="width:auto;max-width:240px" aria-label="Раздел"><option value="">Все разделы</option>${sections.map((s) => `<option>${esc(s)}</option>`).join("")}</select>` : ""}
      <div class="seg" role="group" aria-label="Сортировка"><button data-sort="order" aria-pressed="true">По порядку</button><button data-sort="score" aria-pressed="false">Сначала худшие</button></div>
      </div><div id="req-count" class="small faint" style="margin-bottom:12px"></div><div class="stack" id="req-list"></div>`;
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
      $("#req-list").innerHTML = rs.length ? rs.map(reqCard).join("") : empty("Ничего не найдено", "Измените фильтры или запрос.");
    };
    $("#q", el).oninput = (e) => { qstate.q = e.target.value; upd(); };
    $$(".seg [data-sev]", el).forEach((b) => b.onclick = () => { qstate.sev = b.dataset.sev; $$(".seg [data-sev]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $$(".seg [data-sort]", el).forEach((b) => b.onclick = () => { qstate.sort = b.dataset.sort; $$(".seg [data-sort]", el).forEach((x) => x.setAttribute("aria-pressed", x === b)); upd(); });
    $("#fcrit", el).onchange = (e) => { qstate.crit = e.target.value; upd(); };
    if ($("#fsec", el)) $("#fsec", el).onchange = (e) => { qstate.section = e.target.value; upd(); };
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { const f = e.target.closest("[data-open]"); if (f) openFinding(f.dataset.open, f); } });
    upd();
  }
  function goReq(rid) {
    show("reqs");
    let el = $("#" + CSS.escape(rid));
    if (!el) { qstate.q = ""; qstate.sev = "all"; qstate.crit = ""; qstate.section = ""; rendered.reqs = false; show("reqs"); el = $("#" + CSS.escape(rid)); }
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "start" }); el.animate([{ boxShadow: "0 0 0 4px var(--brand-soft)" }, { boxShadow: "var(--shadow-sm)" }], { duration: 1600 }); }
  }
  function empty(title, text) {
    return `<div class="empty"><svg class="ill" viewBox="0 0 120 90" fill="none" stroke="currentColor" stroke-width="2"><rect x="18" y="10" width="64" height="76" rx="8"/><path d="M30 30h40M30 42h40M30 54h24"/><circle cx="82" cy="58" r="16" fill="var(--surface)"/><path d="m94 70 12 12"/></svg>
      <div class="h3" style="color:var(--text)">${esc(title)}</div><p class="small" style="margin-top:6px">${esc(text)}</p></div>`;
  }

  // ------------------------------------------------------------ Набор
  function renderSet(el) {
    const crit = D.set_criteria.map((c) => `<div class="card card-hover" style="padding:16px">
      <div class="row between"><span class="caption">${esc(c.ref)}</span>${c.count ? chip(c.worst, `${c.count} замеч.`) : chip("ok", "нарушений нет")}</div>
      <div class="h3" style="margin:8px 0 4px">${esc(c.name)}</div><p class="small muted">${esc(c.desc)}</p></div>`).join("");
    const list = D.set.map((fid) => {
      const f = D.findings[fid];
      const kinds = { contradiction: "Противоречие", duplicate: "Дублирование", terminology: "Терминология", gap: "Пропуск", dependency: "Зависимость", structure: "Структура", other: "Прочее" };
      return `<article class="card" style="padding:18px">
        <div class="row wrap"><b>${fid}</b><span class="chip">${esc(kinds[f.set_kind] || f.set_kind)}</span>${chip(f.severity)}<span class="chip">${esc(f.cname)}</span>
          <span class="grow"></span><button class="btn btn-sm btn-ghost" data-open="${fid}">Подробнее ${ic("arrow-right", 14)}</button></div>
        <p style="margin:10px 0">${esc(f.problem)}</p>
        ${f.refs.map((x) => `<div class="quote small" style="margin-top:6px">${x.rid !== "DOC" ? `<a href="#${x.rid}" data-go-req="${x.rid}"><b>${esc(x.label)}</b></a>` : "<b>документ</b>"}: «${esc(x.quote)}»</div>`).join("")}
        <p class="small muted" style="margin-top:10px"><b>Как исправить:</b> ${esc(f.fix)}</p></article>`;
    }).join("");
    el.innerHTML = `<div class="grid g-2" style="margin-bottom:24px;align-items:start">
        <div class="card"><div class="card-title">${ic("layers")}<span class="h3">Профиль набора</span></div>${radar(D.scores.radar_set, 320)}
          <p class="small faint">Оценка по критериям ISO/IEC/IEEE 29148 §5.2.6 и IEEE 830 §4.3. Балл набора: <b>${D.scores.set}</b>/100.</p></div>
        <div class="grid g-2" style="align-content:start">${crit}</div></div>
      <div class="h2" style="margin-bottom:16px">Замечания к набору <span class="faint">(${D.set.length})</span></div>
      <div class="stack">${list || empty("Нарушений на уровне набора нет", "Противоречий, дублей и пропусков не найдено.")}</div>`;
  }

  // ------------------------------------------------------------ Граф (force-directed, без библиотек)
  let graphDrawn = false;
  function renderGraph(el) {
    el.innerHTML = `<p class="small muted" style="margin-bottom:12px">Узлы — требования (цвет — худшее замечание, размер — число связей). Колёсико — масштаб, перетаскивание — сдвиг, клик по узлу — к требованию.</p>
      <div class="graph-wrap" id="gw"><svg id="gsvg" role="img" aria-label="Граф связей требований"></svg>
      <div class="graph-legend"><span><i style="border-color:#E5484D"></i>противоречие</span><span><i style="border-color:#8B5CF6;border-top-style:dashed"></i>дубль</span>
      <span><i style="border-color:var(--text-3)"></i>ссылка</span><span><i style="border-color:#0B5FFF;border-top-width:1px"></i>общий термин</span></div></div>`;
  }
  function drawGraph() {
    if (graphDrawn) return;
    const svg = $("#gsvg");
    if (!svg) return;
    graphDrawn = true;
    const W = svg.clientWidth || 1000, H = svg.clientHeight || 620;
    const nodes = D.graph.nodes.map((n, i) => ({ ...n, x: W / 2 + Math.cos(i) * (100 + i * 6), y: H / 2 + Math.sin(i) * (100 + i * 6), vx: 0, vy: 0 }));
    const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
    const edges = D.graph.edges.filter((e) => e.source in idx && e.target in idx);
    for (let it = 0; it < 420; it++) {
      const alpha = 1 - it / 420;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; let d2 = dx * dx + dy * dy || 1;
        const f = (2600 / d2) * alpha; const d = Math.sqrt(d2); dx /= d; dy /= d;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
      edges.forEach((e) => {
        const a = nodes[idx[e.source]], b = nodes[idx[e.target]]; const dx = b.x - a.x, dy = b.y - a.y; const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 110) * 0.02 * alpha; a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      });
      nodes.forEach((n) => { n.vx += (W / 2 - n.x) * 0.004 * alpha; n.vy += (H / 2 - n.y) * 0.006 * alpha; n.x += n.vx; n.y += n.vy; n.vx *= 0.6; n.vy *= 0.6; });
    }
    const col = { critical: "#E5484D", major: "#F59E0B", minor: "#EAB308", ok: "#12B76A" };
    const est = { contradiction: 'stroke="#E5484D" stroke-width="2.5"', duplicate: 'stroke="#8B5CF6" stroke-width="2" stroke-dasharray="6 5"', dependency: 'stroke="var(--text-3)" stroke-width="1.5"', term: 'stroke="#0B5FFF" stroke-width="1" opacity=".6"' };
    let g = `<g id="gview">`;
    edges.forEach((e) => { const a = nodes[idx[e.source]], b = nodes[idx[e.target]]; g += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" ${est[e.kind]}><title>${esc(e.title)}</title></line>`; });
    nodes.forEach((n) => {
      const r = 14 + Math.min(10, n.degree * 3);
      g += `<g class="node" data-rid="${n.id}" transform="translate(${n.x},${n.y})" tabindex="0" role="button" aria-label="${esc(n.label)}">
        <circle r="${r}" fill="${col[n.severity]}" opacity="${n.degree ? 1 : 0.55}"><title>${esc(n.label)}: ${esc(n.text)}</title></circle>
        <text y="${r + 14}" text-anchor="middle">${esc(n.label)}</text></g>`;
    });
    svg.innerHTML = g + "</g>";
    // зум и панорамирование
    let k = 1, tx = 0, ty = 0, drag = null;
    const view = $("#gview"), apply = () => view.setAttribute("transform", `translate(${tx},${ty}) scale(${k})`);
    svg.addEventListener("wheel", (e) => { e.preventDefault(); const nk = Math.min(4, Math.max(0.3, k * (e.deltaY < 0 ? 1.12 : 0.89))); const r = svg.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top; tx = mx - ((mx - tx) * nk) / k; ty = my - ((my - ty) * nk) / k; k = nk; apply(); }, { passive: false });
    svg.addEventListener("pointerdown", (e) => { if (e.target.closest(".node")) return; drag = [e.clientX - tx, e.clientY - ty]; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener("pointermove", (e) => { if (drag) { tx = e.clientX - drag[0]; ty = e.clientY - drag[1]; apply(); } });
    svg.addEventListener("pointerup", () => (drag = null));
    svg.addEventListener("click", (e) => { const n = e.target.closest(".node"); if (n) goReq(n.dataset.rid); });
    svg.addEventListener("keydown", (e) => { if (e.key === "Enter") { const n = e.target.closest(".node"); if (n) goReq(n.dataset.rid); } });
  }

  // ------------------------------------------------------------ Тесты
  function renderTests(el) {
    const ok = D.reqs.filter((r) => r.test.possible === true), bad = D.reqs.filter((r) => r.test.possible === false);
    const s = D.scores, pct = s.tests_total ? Math.round((100 * s.tests_ok) / s.tests_total) : 0;
    el.innerHTML = `<div class="card" style="margin-bottom:20px"><div class="row wrap" style="gap:24px">
        <div><div class="caption">Покрыто тест-пробой</div><div class="display">${s.tests_ok}<span class="h2 faint"> / ${s.tests_total}</span></div></div>
        <div class="grow"><div class="bar" style="height:12px"><i style="width:${pct}%;background:var(--ok-accent)"></i></div>
        <p class="small muted" style="margin-top:10px">Для каждого требования агент пытается написать приёмочный тест в формате Gherkin. Если тест составить нельзя, это объективное доказательство непроверяемости (ISO/IEC/IEEE 29148 §5.2.5 g).</p></div></div></div>
      ${bad.length ? `<div class="h2" style="margin:8px 0 14px">Тест составить невозможно <span class="faint">(${bad.length})</span></div>
        <div class="grid g-2">${bad.map((r) => `<div class="card" style="border-color:color-mix(in srgb,#E5484D 35%,var(--border))">
          <div class="row"><a href="#${r.rid}" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a>${chip("critical", "непроверяемо")}</div>
          <p class="small muted" style="margin:8px 0">${esc(r.text)}</p>
          <div class="small"><b>Почему:</b> ${esc(r.test.reason)}</div>
          <div class="quote small" style="margin-top:8px">Мешает: «${esc(r.test.blocker)}»</div></div>`).join("")}</div>` : ""}
      ${ok.length ? `<div class="h2" style="margin:28px 0 14px">Сгенерированные приёмочные тесты <span class="faint">(${ok.length})</span></div>
        <div class="toolbar"><button class="btn btn-secondary btn-sm" data-copy="${esc(ok.map((r) => `# ${label(r)}\n${r.test.gherkin}`).join("\n\n"))}" data-msg="Все тесты скопированы">${ic("copy", 14)}Скопировать все (.feature)</button></div>
        <div class="grid g-2">${ok.map((r) => `<div class="card"><div class="row"><a href="#${r.rid}" data-go-req="${r.rid}"><b>${esc(label(r))}</b></a>${chip("ok", "тест есть")}</div>
          <pre class="code gherkin" style="margin-top:10px">${gherkin(r.test.gherkin)}</pre></div>`).join("")}</div>` : ""}
      ${!ok.length && !bad.length ? empty("Тест-проба не выполнялась", "Запустите прогон без флага --no-tests.") : ""}`;
  }

  // ------------------------------------------------------------ Исправленный документ
  function renderFixed(el) {
    const blob = URL.createObjectURL(new Blob([D.fixed_text], { type: "text/markdown;charset=utf-8" }));
    const rs = D.rescore;
    el.innerHTML = `<div class="card" style="margin-bottom:20px;display:flex;gap:20px;align-items:center;flex-wrap:wrap">
        <div class="grow"><div class="h2">Исправленная версия документа</div>
        <p class="small muted" style="margin-top:6px">Агент заменил ${D.changes.length} проблемных формулировок предложенными; структура документа сохранена, у каждого исправления есть сноска. Это предложения для согласования с заказчиком.</p></div>
        ${rs ? `<div style="text-align:center"><div class="caption">Балл документа</div><div class="h1">${rs.before} <span class="faint">→</span> <span style="color:var(--ok)">${rs.after}</span></div>${deltaChip(rs.after - rs.before)}</div>` : `<div class="small faint" style="max-width:220px">Запустите с <span class="kbd">--rescore</span>, чтобы увидеть «было → стало» по повторной проверке.</div>`}
        <a class="btn btn-primary" href="${blob}" download="requirements_fixed.md">${ic("download", 16)}Скачать .md</a></div>
      <div class="stack">${D.changes.map((c) => `<article class="card">
        <div class="row wrap"><a href="#${c.rid}" data-go-req="${c.rid}"><b>${esc(c.rid)}${c.doc_id ? " · " + esc(c.doc_id) : ""}</b></a>${c.criteria.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}
          <span class="grow"></span><button class="btn btn-sm btn-ghost" data-copy="${esc(c.after)}">${ic("copy", 14)}Копировать</button></div>
        <div class="diff" style="margin-top:12px"><div class="side"><div class="caption" style="margin-bottom:6px">Было</div>${c.diff.filter((d) => d[0] !== "ins").map((d) => (d[0] === "del" ? `<del>${esc(d[1])}</del>` : esc(d[1]))).join(" ")}</div>
        <div class="side"><div class="caption" style="margin-bottom:6px">Стало</div>${c.diff.filter((d) => d[0] !== "del").map((d) => (d[0] === "ins" ? `<ins>${esc(d[1])}</ins>` : esc(d[1]))).join(" ")}</div></div></article>`).join("") || empty("Исправлений нет", "Модель не предложила новых формулировок.")}</div>`;
  }

  // ------------------------------------------------------------ Вопросы заказчику
  function renderQuestions(el) {
    const groups = {};
    D.questions.forEach((q) => (groups[q.section] = groups[q.section] || []).push(q));
    const all = D.questions.map((q, i) => `${i + 1}. [${q.ref}] ${q.text}`).join("\n");
    el.innerHTML = `<div class="toolbar"><div class="grow"><div class="h2">Вопросы заказчику и аналитику</div>
        <p class="small muted">Сформированы из замечаний: отправьте их до начала разработки, чтобы закрыть неопределённости.</p></div>
        <button class="btn btn-primary" data-copy="${esc(all)}" data-msg="Вопросы скопированы">${ic("copy", 16)}Скопировать все</button></div>
      ${Object.entries(groups).map(([sec, qs]) => `<div class="card" style="margin-bottom:16px"><div class="caption" style="margin-bottom:10px">${esc(sec)}</div>
        ${qs.map((q) => `<div class="row" style="align-items:flex-start;padding:10px 0;border-top:1px dashed var(--border)">${chip(q.severity, " ")}<div class="grow"><b class="small">${esc(q.ref)}</b><p class="small" style="margin-top:2px">${esc(q.text)}</p></div>
          <button class="btn btn-sm btn-ghost btn-icon" aria-label="Скопировать вопрос" data-copy="${esc(q.text)}">${ic("copy", 14)}</button></div>`).join("")}</div>`).join("") || empty("Вопросов нет", "Существенных неопределённостей не найдено.")}`;
  }

  // ------------------------------------------------------------ Домен и глоссарий
  function renderDomain(el) {
    const d = D.domain, g = D.glossary;
    const st = { covered: ["ok", "покрыта"], partial: ["major", "частично"], missing: ["critical", "не покрыта"] };
    el.innerHTML = (d ? `<div class="card" style="margin-bottom:20px"><div class="row wrap" style="gap:24px">
        <div><div class="caption">${esc(d.name)}</div><div class="display">${d.coverage}%</div><div class="small faint">покрытие доменного чек-листа</div></div>
        <div class="grow small muted">${esc(d.disclaimer)}</div></div></div>
      <div class="grid g-3" style="margin-bottom:32px">${d.areas.map((a) => `<div class="card card-hover" style="padding:16px">
        <div class="row between"><b class="small">${esc(a.title)}</b>${chip(st[a.status][0], st[a.status][1])}</div>
        ${a.quotes.length ? a.quotes.map((q) => `<div class="quote small" style="margin-top:8px">«${esc(q)}»</div>`).join("") : `<p class="small muted" style="margin-top:8px">${ic("chat", 14)} ${esc(a.question)}</p>`}</div>`).join("")}</div>` : "")
      + (g ? `<div class="h2" style="margin-bottom:14px">Глоссарий</div>
      ${g.synonyms.length ? `<div class="stack" style="margin-bottom:16px">${g.synonyms.map((s) => `<div class="card" style="padding:14px;background:var(--major-soft);border-color:transparent">
        <b>Разнобой терминов:</b> ${s.terms.map((t) => `<span class="chip" style="margin:0 2px">${esc(t)}</span>`).join("")} → используйте «${esc(s.preferred)}». <span class="small muted">${esc(s.problem)}</span></div>`).join("")}</div>` : ""}
      <div class="table-wrap"><table class="tbl"><thead><tr><th>Термин</th><th>Определение</th><th>Упоминаний</th><th>Требования</th></tr></thead><tbody>
      ${g.terms.map((t) => `<tr><td><b>${esc(t.term)}</b></td><td>${t.defined ? esc(t.definition) : `<span class="chip sev-major">не определён</span>`}</td><td>${t.count}</td><td class="small">${t.reqs.slice(0, 8).map((r) => `<a href="#${r}" data-go-req="${r}">${esc(reqById[r] ? reqById[r].doc_id || r : r)}</a>`).join(", ")}</td></tr>`).join("")}
      </tbody></table></div>` : "") || empty("Нет данных", "Доменная проверка отключена (--domain none).");
    sortable(el);
  }
  function sortable(el) {
    $$("table.tbl", el).forEach((t) => $$("th", t).forEach((th, i) => th.onclick = () => {
      const rows = $$("tbody tr", t), dir = th.dataset.dir === "asc" ? -1 : 1; th.dataset.dir = dir === 1 ? "asc" : "desc";
      rows.sort((a, b) => { const x = a.children[i].textContent, y = b.children[i].textContent; return (isNaN(x) || isNaN(y) ? x.localeCompare(y, "ru") : x - y) * dir; });
      rows.forEach((r) => t.tBodies[0].appendChild(r));
    }));
  }

  // ------------------------------------------------------------ Паспорт
  function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n\n+/).map((p) => `<p class="small" style="margin-bottom:10px">${p}</p>`).join(""); }
  function renderPassport(el) {
    const p = D.passport;
    const rows = [["Документ", p.document], ["Файл", `${p.file} (${p.format}${p.pages ? ", " + p.pages + " стр." : ""})`], ["SHA-256", p.sha256], ["Дата и время", p.started],
      ["Модель", p.model], ["Версия агента", p.agent_version], ["Профиль", p.profile], ["Режим", p.mode], ["Обращений к модели", `${p.calls} (повторов: ${p.retries})`],
      ["Токены (вход / выход)", p.tokens_in ? `${p.tokens_in} / ${p.tokens_out}` : "—"], ["Длительность", p.duration_s + " с"],
      ["Способ нарезки", { ids: "по идентификаторам документа", modal: "по модальным формулировкам", llm: "моделью" }[p.split_method]],
      ["Критик-агент", p.critic ? "включён" : "выключен"], ["Отброшено неподтверждённых цитат", p.dropped], ["Отклонено критиком", p.rejected],
      ["Критерии", "ISO/IEC/IEEE 29148:2018 п. 5.2.5, 5.2.6; IEEE Std 830-1998 п. 4.3"]];
    const tbl = (title, items, cols) => items.length ? `<div class="h3" style="margin:28px 0 10px">${title} <span class="faint">(${items.length})</span></div>
      <div class="table-wrap"><table class="tbl"><thead><tr>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${items.map((d) => `<tr>${cols.map((c) => `<td class="small">${esc(d[c[1]])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    el.innerHTML = `<div class="grid g-2" style="align-items:start"><div class="card"><div class="card-title">${ic("id")}<span class="h3">Паспорт прогона</span></div>
        <dl class="kv">${rows.map((r) => `<dt>${r[0]}</dt><dd ${r[0] === "SHA-256" ? 'class="mono" style="word-break:break-all"' : ""}>${esc(r[1])}</dd>`).join("")}</dl></div>
      <div class="card"><div class="card-title">${ic("book")}<span class="h3">Методика оценки</span></div>${md(D.method)}
        ${D.notes.length ? `<div class="h3" style="margin:16px 0 8px">Примечания</div>${D.notes.map((n) => `<p class="small" style="color:var(--major)">⚠️ ${esc(n)}</p>`).join("")}` : ""}</div></div>
      ${tbl("Отброшенные замечания модели (цитата не найдена в документе)", D.dropped, [["Где", "where"], ["Цитата модели", "quote"], ["Суть", "problem"]])}
      ${tbl("Замечания, отклонённые критиком", D.rejected, [["Где", "where"], ["Цитата", "quote"], ["Суть", "problem"], ["Причина", "reason"]])}`;
  }

  const RENDER = { doc: renderDoc, reqs: renderReqs, set: renderSet, graph: renderGraph, tests: renderTests, fixed: renderFixed, questions: renderQuestions, domain: renderDomain, passport: renderPassport };

  // ------------------------------------------------------------ горячие клавиши
  const KEYS = [["/", "поиск по требованиям"], ["J / K", "следующий / предыдущий дефект"], ["T", "сменить тему"], ["Esc", "закрыть панель"], ["1–9", "вкладки"]];
  $("#btn-keys").onclick = () => {
    $("#drawer-title").textContent = "Горячие клавиши";
    $("#drawer-body").innerHTML = KEYS.map((k) => `<div class="row between" style="padding:8px 0;border-bottom:1px solid var(--border)"><span>${esc(k[1])}</span><span class="kbd">${esc(k[0])}</span></div>`).join("");
    lastFocus = $("#btn-keys");
    $("#drawer").classList.add("open"); $("#overlay").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input,select,textarea")) { if (e.key === "Escape") e.target.blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") closeDrawer();
    else if (e.key === "/") { e.preventDefault(); show("reqs"); $("#q").focus(); }
    else if (e.key === "j" || e.key === "о") stepMark(1);
    else if (e.key === "k" || e.key === "л") stepMark(-1);
    else if (e.key === "t" || e.key === "е") toggleTheme();
    else if (e.key === "?") $("#btn-keys").click();
    else if (/^[1-9]$/.test(e.key) && TABS[+e.key - 1]) show(TABS[+e.key - 1].id);
  });

  // ------------------------------------------------------------ печать: отрисовать все вкладки
  window.addEventListener("beforeprint", () => TABS.forEach((t) => { if (!rendered[t.id]) { RENDER[t.id]($("#panel-" + t.id)); rendered[t.id] = true; } }));

  // ------------------------------------------------------------ старт
  renderHero();
  renderOverview();
  renderTabs();
  $("#footer").innerHTML = `Сформировано агентом ReqLens · ${esc(D.passport.agent_version)} · ${esc(D.passport.started)} · Критерии ISO/IEC/IEEE 29148:2018 и IEEE Std 830-1998`;
  window.addEventListener("hashchange", () => {
    const x = decodeURIComponent(location.hash.slice(1));
    if (reqById[x]) goReq(x); else if (/^L\d+$/.test(x)) goLine(+x.slice(1)); else if (TABS.some((t) => t.id === x)) show(x);
  });
  const h = decodeURIComponent(location.hash.slice(1));
  if (h && reqById[h]) { show("reqs"); setTimeout(() => goReq(h), 50); }
  else if (/^L\d+$/.test(h)) goLine(+h.slice(1));
  else show(TABS.some((t) => t.id === h) ? h : "doc");
})();
