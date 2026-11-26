/* ReqLens — раздел «Граф»: 3D (3d-force-graph + three.js, инлайн, распаковывается лениво) и 2D-вид на SVG
   как запасной вариант (кнопка «2D» и автоматический fallback, если WebGL недоступен). Использует window.RL. */
(function () {
  "use strict";
  const RL = window.RL; if (!RL) return;
  const { D, $, $$, esc, ic, SEV, ORDER, chip, statusChip, label, reqById, empty } = RL;
  const KIND = {
    contradiction: { label: "Противоречие", color: "#D64545", hint: "красная линия" },
    dependency: { label: "Зависимость", color: "#8A968E", hint: "серая линия" },
    duplicate: { label: "Дубликат", color: "#3FA06B", hint: "пунктир" },
    term: { label: "Термин", color: "#2E8B57", hint: "тонкая линия" },
  };
  const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  // ---------------------------------------------------------------- данные: узлы с числом дефектов, рёбра со ссылкой на замечание
  // статус узла — худшее из замечаний к требованию и к набору, где оно участвует (противоречие красит обе стороны)
  const setRefs = {}, setWorst = {};
  D.set.forEach((fid) => D.findings[fid].refs.forEach((x) => {
    setRefs[x.rid] = (setRefs[x.rid] || 0) + 1;
    const s = D.findings[fid].severity; if (!setWorst[x.rid] || ORDER[s] < ORDER[setWorst[x.rid]]) setWorst[x.rid] = s;
  }));
  const NODES = D.graph.nodes.map((n) => {
    const r = reqById[n.id], own = n.severity || "ok", fromSet = setWorst[n.id];
    return { id: n.id, label: n.label, severity: fromSet && ORDER[fromSet] < ORDER[own] ? fromSet : own, text: n.text || (r ? r.text : ""), section: n.section || "", degree: n.degree || 0,
      nfind: (r ? r.findings.length : 0) + (setRefs[n.id] || 0), score: r ? r.score : null };
  });
  const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));
  const LINKS = D.graph.edges.filter((e) => byId[e.source] && byId[e.target]).map((e, i) => {
    const m = /^(S-\d+)/.exec(e.title || "");
    return { i, source: e.source, target: e.target, a: e.source, b: e.target, kind: KIND[e.kind] ? e.kind : "dependency", title: e.title || "", fid: m && D.findings[m[1]] ? m[1] : null };
  });
  const adj = {};
  LINKS.forEach((l) => { (adj[l.a] = adj[l.a] || []).push(l); (adj[l.b] = adj[l.b] || []).push(l); });
  const other = (l, id) => (l.a === id ? l.b : l.a);

  const st = { mode: null, kinds: { contradiction: true, dependency: true, duplicate: true, term: true }, sev: { critical: true, major: true, minor: true, ok: true }, sel: null, chain: null };
  const nodeOn = (n) => st.sev[n.severity];
  const linkOn = (l) => st.kinds[l.kind] && nodeOn(byId[l.a]) && nodeOn(byId[l.b]);
  const inChain = (id) => !st.chain || st.chain.nodes.has(id);
  const linkInChain = (l) => !st.chain || st.chain.links.has(l.i);

  // Цепочка конфликта: компонент связности по противоречиям (и дублям); без противоречий — ближайшие соседи
  function chainOf(id) {
    const nodes = new Set([id]), links = new Set(), q = [id];
    while (q.length) {
      const cur = q.shift();
      (adj[cur] || []).forEach((l) => {
        if (l.kind !== "contradiction" && l.kind !== "duplicate") return;
        links.add(l.i); const o = other(l, cur); if (!nodes.has(o)) { nodes.add(o); q.push(o); }
      });
    }
    if (nodes.size === 1) (adj[id] || []).forEach((l) => { links.add(l.i); nodes.add(other(l, id)); });
    return { nodes, links, root: id, conflict: [...links].some((i) => LINKS[i].kind === "contradiction") };
  }

  // ---------------------------------------------------------------- разметка раздела
  const webgl = (() => { try { const c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"))); } catch (e) { return false; } })();
  const canInflate = typeof DecompressionStream === "function" && !!document.getElementById("lib-3d") && document.getElementById("lib-3d").textContent.trim().length > 100;
  const kindCount = (k) => LINKS.filter((l) => l.kind === k).length;
  const sevCount = (k) => NODES.filter((n) => n.severity === k).length;

  function render(el) {
    if (!NODES.length) { el.innerHTML = `<div class="section-title" style="margin-top:0"><h2 class="h1">Граф требований</h2></div>${empty("Граф пуст", "В документе не найдено требований.")}`; return; }
    const sample = { contradiction: "g-l-red", dependency: "g-l-gray", duplicate: "g-l-dash", term: "g-l-thin" };
    el.innerHTML = `<div class="section-title" style="margin-top:0"><div><h2 class="h1">Граф требований</h2>
        <p class="small muted" style="margin-top:4px">Узлы — требования: цвет и значок — статус, размер — число дефектов. Рёбра: красные — противоречия, серые — зависимости, пунктир — дубликаты.</p></div>
        <div class="row wrap no-print"><div class="seg" role="group" aria-label="Вид графа">
          <button data-gmode="3d" aria-pressed="false" ${webgl && canInflate ? "" : `disabled title="WebGL недоступен в этом браузере"`}>${ic("cube", 14)} 3D</button>
          <button data-gmode="2d" aria-pressed="false">${ic("graph", 14)} 2D</button></div>
          <button class="btn btn-sm btn-outline" id="g-reset">${ic("refresh", 14)}Сбросить вид</button></div></div>
      <div class="toolbar no-print g-filters">
        <span class="caption">Связи</span>${Object.keys(KIND).filter((k) => kindCount(k) || k !== "term").map((k) => `<button class="pill" data-gkind="${k}" aria-pressed="true"><i class="g-swatch ${sample[k]}" aria-hidden="true"></i>${KIND[k].label} · ${kindCount(k)}</button>`).join("")}
        <span class="caption" style="margin-left:8px">Тяжесть</span>${["critical", "major", "minor", "ok"].map((k) => `<button class="pill" data-gsev="${k}" aria-pressed="true">${ic(SEV[k].icon, 13)}${k === "ok" ? "Без замечаний" : SEV[k].label} · ${sevCount(k)}</button>`).join("")}</div>
      <div class="g-layout">
        <div class="g-stage" id="g-stage">
          <div class="g-canvas" id="g-canvas" aria-label="Граф связей требований"></div>
          <div class="g-labels" id="g-labels" aria-hidden="true"></div>
          <div class="g-note" id="g-note" role="status" aria-live="polite"></div>
          <div class="g-hint small" id="g-hint"></div>
        </div>
        <aside class="g-side card" id="g-side" aria-live="polite"></aside>
      </div>
      <div class="section-title"><h3 class="h2">Связи <span class="faint">(${LINKS.length})</span></h3></div>
      ${LINKS.length ? `<div class="table-wrap"><table class="tbl"><thead><tr><th>Тип</th><th>Требование</th><th>Связано с</th><th>Описание</th></tr></thead><tbody>
        ${LINKS.map((l) => `<tr><td>${kindChip(l.kind)}</td><td><button class="linkish" data-gsel="${l.a}">${esc(byId[l.a].label)}</button></td><td><button class="linkish" data-gsel="${l.b}">${esc(byId[l.b].label)}</button></td>
          <td class="small">${esc(l.title)}${l.fid ? ` <a href="#${l.fid}" data-open="${l.fid}">${l.fid}</a>` : ""}</td></tr>`).join("")}</tbody></table></div>`
        : empty("Связей не найдено", "Противоречий, дублей и ссылок между требованиями нет — узлы показаны без рёбер.")}`;
    $$("[data-gmode]", el).forEach((b) => b.onclick = () => setMode(b.dataset.gmode));
    $$("[data-gkind]", el).forEach((b) => b.onclick = () => { const k = b.dataset.gkind; st.kinds[k] = !st.kinds[k]; b.setAttribute("aria-pressed", st.kinds[k]); refresh(); });
    $$("[data-gsev]", el).forEach((b) => b.onclick = () => { const k = b.dataset.gsev; st.sev[k] = !st.sev[k]; b.setAttribute("aria-pressed", st.sev[k]); if (st.sel && !nodeOn(byId[st.sel])) select(null); refresh(); });
    $("#g-reset", el).onclick = () => { select(null); if (st.mode === "3d" && G3) G3.zoomToFit(600, 40); if (st.mode === "2d") reset2D(); };
    el.addEventListener("click", (e) => { const b = e.target.closest("[data-gsel]"); if (b) { e.preventDefault(); select(b.dataset.gsel, true); $("#g-stage").scrollIntoView({ behavior: RL.REDUCED ? "auto" : "smooth", block: "nearest" }); return; }
      const c = e.target.closest("[data-gchain]"); if (c) { st.chain = st.chain && st.chain.root === c.dataset.gchain ? null : chainOf(c.dataset.gchain); side(); refresh(); return; }
      if (e.target.closest("[data-gclose]")) select(null); });
    side();
  }
  // режим выбираем при первом показе: до этого раздел скрыт и у холста нет размеров
  const firstMode = () => setMode(webgl && canInflate ? "3d" : "2d", !webgl ? "WebGL недоступен — показан 2D-вид." : !canInflate ? "Браузер не может распаковать 3D-движок — показан 2D-вид." : "");
  function kindChip(k) {
    const cls = { contradiction: "sev-critical", dependency: "chip-outline", duplicate: "sev-ok", term: "chip-brand" }[k];
    return `<span class="chip ${cls}"><i class="g-swatch ${{ contradiction: "g-l-red", dependency: "g-l-gray", duplicate: "g-l-dash", term: "g-l-thin" }[k]}" aria-hidden="true"></i>${KIND[k].label}</span>`;
  }

  // ---------------------------------------------------------------- боковая панель
  function side() {
    const el = $("#g-side"); if (!el) return;
    if (!st.sel) {
      const hot = NODES.filter((n) => n.nfind || n.degree).sort((a, b) => ORDER[a.severity] - ORDER[b.severity] || b.degree - a.degree || b.nfind - a.nfind).slice(0, 12);
      el.innerHTML = `<div class="caption">Обзор графа</div>
        <div class="g-stats"><div><b>${NODES.length}</b><span>требований</span></div><div><b>${LINKS.length}</b><span>связей</span></div>
          <div><b style="color:${kindCount("contradiction") ? "var(--critical)" : "inherit"}">${kindCount("contradiction")}</b><span>противоречий</span></div></div>
        <p class="small muted">Нажмите на узел — появятся детали и цепочка конфликта. ${st.mode === "3d" ? "Перетаскивание — вращение, колёсико — масштаб." : "Колёсико — масштаб, перетаскивание — сдвиг."}</p>
        ${hot.length ? `<div class="caption" style="margin-top:14px">Проблемные узлы</div><div class="g-nodes">${hot.map((n) => `<button class="g-node-btn" data-gsel="${n.id}">${ic(SEV[n.severity].icon, 13)}<b>${esc(n.label)}</b><span class="small muted">${n.nfind} деф. · ${n.degree} св.</span></button>`).join("")}</div>` : ""}`;
      return;
    }
    const n = byId[st.sel], r = reqById[n.id], ls = adj[n.id] || [], hasConflict = ls.some((l) => l.kind === "contradiction" || l.kind === "duplicate");
    const chainOn = st.chain && st.chain.root === n.id;
    el.innerHTML = `<div class="row" style="gap:8px"><b class="h2">${esc(n.label)}</b>${statusChip(n.severity)}<span class="grow"></span>
        <button class="btn btn-sm btn-ghost btn-icon" data-gclose aria-label="Закрыть детали">${ic("x", 14)}</button></div>
      <div class="small muted">${esc(r ? label(r) : n.id)}${n.section ? " · " + esc(n.section) : ""}</div>
      <p class="small">${esc(r ? r.text : n.text)}</p>
      <div class="g-stats"><div><b>${n.score == null ? "—" : n.score}</b><span>балл</span></div><div><b>${n.nfind}</b><span>дефектов</span></div><div><b>${ls.length}</b><span>связей</span></div></div>
      ${ls.length ? `<div class="caption">Связи</div><div class="g-rel">${ls.map((l) => `<div class="g-rel-row ${linkInChain(l) && st.chain ? "on" : ""}">${kindChip(l.kind)}
          <button class="linkish" data-gsel="${other(l, n.id)}"><b>${esc(byId[other(l, n.id)].label)}</b></button>
          <span class="small muted">${esc(short(l.title.replace(/^S-\d+:\s*/, ""), 110))}</span>${l.fid ? `<a class="small" href="#${l.fid}" data-open="${l.fid}">${l.fid} — подробнее</a>` : ""}</div>`).join("")}</div>` : `<p class="small faint">Связей с другими требованиями нет.</p>`}
      ${r && r.findings.length ? `<div class="caption">Замечания</div><div class="g-rel">${r.findings.map((id) => { const f = D.findings[id]; return `<button class="g-find" data-open="${id}">${chip(f.severity)}<span class="small">${esc(f.cname)}</span></button>`; }).join("")}</div>` : ""}
      <div class="row wrap" style="gap:6px">${hasConflict || ls.length ? `<button class="btn btn-sm ${chainOn ? "btn-primary" : "btn-outline"}" data-gchain="${n.id}" aria-pressed="${!!chainOn}">${ic("link", 14)}${chainOn ? "Снять подсветку" : "Цепочка конфликта"}</button>` : ""}
        ${r ? `<button class="btn btn-sm btn-ghost" data-go-req="${n.id}">${ic("list", 14)}В таблице</button><button class="btn btn-sm btn-ghost" data-go-doc="${n.id}">${ic("file", 14)}В документе</button>` : ""}</div>`;
  }
  function select(id, focusCam) {
    st.sel = id && byId[id] ? id : null;
    st.chain = st.sel ? chainOf(st.sel) : null;
    if (st.chain && st.chain.nodes.size <= 1) st.chain = null;
    side(); refresh();
    if (st.sel && focusCam && st.mode === "3d" && G3) {
      const n = G3.graphData().nodes.find((x) => x.id === st.sel);
      if (n && n.x != null) {
        // подлетаем к узлу, сохраняя угол обзора: расстояние — не ближе 220, чтобы были видны соседи по цепочке
        const c = G3.camera().position, dx = c.x - n.x, dy = c.y - n.y, dz = c.z - n.z, cur = Math.hypot(dx, dy, dz) || 1;
        const d = Math.max(220, Math.min(cur, 420)) / cur;
        G3.cameraPosition({ x: n.x + dx * d, y: n.y + dy * d, z: n.z + dz * d }, n, RL.REDUCED ? 0 : 900);
      }
    }
  }

  // ---------------------------------------------------------------- цвета
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const DIM = "rgba(140,150,145,0.18)";
  function nodeColor(n) { if (!inChain(n.id)) return DIM; return SEV[n.severity].color; }
  function linkColor(l) {
    if (st.chain && !linkInChain(l)) return "rgba(140,150,145,0.10)";
    return { contradiction: "#D64545", dependency: "rgba(138,150,142,0.85)", duplicate: "rgba(63,160,107,0.45)", term: "rgba(46,139,87,0.5)" }[l.kind];
  }

  // ---------------------------------------------------------------- 3D
  let G3 = null, lib = null, raf = 0;
  function loadLib() {
    if (window.ForceGraph3D) return Promise.resolve(window.ForceGraph3D);
    if (lib) return lib;
    lib = (async () => {
      const raw = document.getElementById("lib-3d").textContent.trim();
      const bin = Uint8Array.from(atob(raw), (c) => c.charCodeAt(0));
      const text = await new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
      const s = document.createElement("script"); s.textContent = text; document.head.appendChild(s);
      if (!window.ForceGraph3D) throw new Error("3D-движок не инициализировался");
      return window.ForceGraph3D;
    })();
    return lib;
  }
  function clusterForce() {
    let ns = [];
    const f = (alpha) => {
      const c = {};
      ns.forEach((n) => { const k = c[n.section] || (c[n.section] = { x: 0, y: 0, z: 0, n: 0 }); k.x += n.x; k.y += n.y; k.z += n.z || 0; k.n++; });
      ns.forEach((n) => { const k = c[n.section]; if (k.n < 2) return; n.vx += (k.x / k.n - n.x) * 0.06 * alpha; n.vy += (k.y / k.n - n.y) * 0.06 * alpha; n.vz = (n.vz || 0) + (k.z / k.n - (n.z || 0)) * 0.06 * alpha; });
    };
    f.initialize = (x) => (ns = x);
    return f;
  }
  async function init3D() {
    const box = $("#g-canvas"), note = $("#g-note");
    note.innerHTML = `<span class="skel" style="width:140px;display:inline-block;vertical-align:middle"></span> Загружаем 3D-движок…`; note.hidden = false;
    let F;
    try { F = await loadLib(); } catch (e) { setMode("2d", "Не удалось запустить 3D-вид — показан 2D."); return; }
    if (st.mode !== "3d") return;
    note.hidden = true; note.textContent = "";
    box.innerHTML = "";
    try {
      G3 = F({ controlType: "orbit" })(box);
    } catch (e) { G3 = null; setMode("2d", "WebGL недоступен — показан 2D-вид."); return; }
    const data = { nodes: NODES.map((n) => ({ ...n })), links: LINKS.map((l) => ({ ...l })) };
    G3.backgroundColor(css("--surface") || "#ffffff").showNavInfo(false)
      .width(box.clientWidth).height(box.clientHeight)
      .nodeId("id").nodeVal((n) => 2 + n.nfind * 3).nodeRelSize(6).nodeResolution(20).nodeOpacity(0.95)
      .nodeColor(nodeColor).nodeVisibility(nodeOn)
      .nodeLabel((n) => `<div class="g3-tip"><b>${esc(n.label)}</b> · ${esc(n.severity === "ok" ? "без замечаний" : SEV[n.severity].label.toLowerCase())}<br>${esc(short(n.text, 120))}<br><span>дефектов: ${n.nfind} · связей: ${n.degree}</span></div>`)
      .linkVisibility(linkOn).linkColor(linkColor).linkOpacity(0.85)
      .linkWidth((l) => (l.kind === "duplicate" ? 0.3 : (l.kind === "contradiction" ? 1.6 : 0.7) * (st.chain && linkInChain(l) ? 1.8 : 1)))
      .linkDirectionalParticles((l) => (l.kind === "duplicate" ? 10 : 0)).linkDirectionalParticleSpeed(RL.REDUCED ? 0 : 0.0035)
      .linkDirectionalParticleWidth(2.2).linkDirectionalParticleColor(() => "#3FA06B")
      .linkLabel((l) => `<div class="g3-tip"><b>${esc(KIND[l.kind].label)}</b><br>${esc(short(l.title, 160))}</div>`)
      .onNodeClick((n) => select(n.id, true)).onLinkClick((l) => { if (l.fid) RL.openFinding(l.fid); })
      .onBackgroundClick(() => select(null))
      .cooldownTicks(220).warmupTicks(30)
      .graphData(data);
    G3.d3Force("charge").strength(-90);
    G3.d3Force("cluster", clusterForce());
    let fitted = false;
    G3.onEngineStop(() => { if (!fitted) { fitted = true; G3.zoomToFit(RL.REDUCED ? 0 : 700, 60); } });
    setTimeout(() => { if (G3 && !fitted) G3.zoomToFit(RL.REDUCED ? 0 : 600, 60); }, 900);
    const ctl = G3.controls();
    if (ctl) {
      if (!RL.REDUCED && "autoRotate" in ctl) { ctl.autoRotate = true; ctl.autoRotateSpeed = 0.7; }
      ctl.addEventListener("start", () => { if ("autoRotate" in ctl) ctl.autoRotate = false; });
    }
    $("#g-hint").textContent = "Перетаскивание — вращение · колёсико — масштаб · правая кнопка — сдвиг · клик по узлу — детали";
    loop();
  }
  // подписи узлов поверх canvas (без SpriteText): проекция координат в экранные каждый кадр
  function loop() {
    cancelAnimationFrame(raf);
    const lay = $("#g-labels"); if (!lay || !G3 || st.mode !== "3d") return;
    const many = NODES.length > 60;
    lay.innerHTML = NODES.map((n) => `<span data-l="${esc(n.id)}" class="g-lbl">${esc(n.label)}</span>`).join("");
    const els = Object.fromEntries($$(".g-lbl", lay).map((x) => [x.dataset.l, x]));
    const tick = () => {
      if (!G3 || st.mode !== "3d" || RL.active !== "graph") return;
      G3.graphData().nodes.forEach((n) => {
        const e = els[n.id]; if (!e) return;
        const show = n.x != null && nodeOn(n) && (!many || n.nfind || n.degree || st.sel === n.id);
        if (!show) { e.style.display = "none"; return; }
        const p = G3.graph2ScreenCoords(n.x, n.y, n.z);
        e.style.display = ""; e.style.transform = `translate(${p.x.toFixed(1)}px,${(p.y + 10).toFixed(1)}px) translate(-50%,0)`;
        e.classList.toggle("dim", !inChain(n.id)); e.classList.toggle("sel", st.sel === n.id);
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- 2D (SVG, без библиотек)
  let pos2 = null, view2 = { k: 1, tx: 0, ty: 0 };
  function layout2D(W, H) {
    const nodes = NODES.map((n, i) => ({ id: n.id, section: n.section, x: W / 2 + Math.cos(i * 2.4) * (60 + i * 7), y: H / 2 + Math.sin(i * 2.4) * (60 + i * 7), vx: 0, vy: 0 }));
    const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
    for (let it = 0; it < 420; it++) {
      const al = 1 - it / 420;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy || 1, f = (2600 / d2) * al, d = Math.sqrt(d2); dx /= d; dy /= d;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
      LINKS.forEach((e) => { const a = nodes[idx[e.a]], b = nodes[idx[e.b]], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - 110) * 0.02 * al; a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f; });
      const c = {}; nodes.forEach((n) => { const k = c[n.section] || (c[n.section] = { x: 0, y: 0, n: 0 }); k.x += n.x; k.y += n.y; k.n++; });
      nodes.forEach((n) => { const k = c[n.section]; if (k.n > 1) { n.vx += (k.x / k.n - n.x) * 0.01 * al; n.vy += (k.y / k.n - n.y) * 0.01 * al; } n.vx += (W / 2 - n.x) * 0.004 * al; n.vy += (H / 2 - n.y) * 0.006 * al; n.x += n.vx; n.y += n.vy; n.vx *= 0.6; n.vy *= 0.6; });
    }
    return Object.fromEntries(nodes.map((n) => [n.id, n]));
  }
  const GLYPH = { critical: "!", major: "!", minor: "·", ok: "✓" };
  function draw2D() {
    const box = $("#g-canvas"); if (!box) return;
    const W = box.clientWidth || 800, H = box.clientHeight || 560;
    if (!pos2) pos2 = layout2D(W, H);
    const dash = { contradiction: 'stroke-width="2.5"', dependency: 'stroke-width="1.6"', duplicate: 'stroke-width="2.2" stroke-dasharray="7 5"', term: 'stroke-width="1.2"' };
    let g = `<g id="g2view" transform="translate(${view2.tx},${view2.ty}) scale(${view2.k})">`;
    LINKS.forEach((l) => { const a = pos2[l.a], b = pos2[l.b]; g += `<line class="g2-link" data-li="${l.i}" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${KIND[l.kind].color}" ${dash[l.kind]}><title>${esc(KIND[l.kind].label)}: ${esc(l.title)}</title></line>`; });
    NODES.forEach((n) => {
      const p = pos2[n.id], r = 12 + Math.min(14, n.nfind * 3);
      g += `<g class="node" data-nid="${esc(n.id)}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})" tabindex="0" role="button" aria-label="${esc(n.label)}: ${esc(n.severity === "ok" ? "без замечаний" : SEV[n.severity].label)}, дефектов ${n.nfind}">
        <circle r="${r}" fill="${SEV[n.severity].color}"><title>${esc(n.label)}: ${esc(n.text)}</title></circle><text class="glyph" dy="4" text-anchor="middle">${GLYPH[n.severity]}</text><text y="${r + 14}" text-anchor="middle">${esc(n.label)}</text></g>`;
    });
    box.innerHTML = `<svg id="g2" width="100%" height="100%" role="img" aria-label="Граф связей требований, 2D">${g}</g></svg>`;
    const svg = $("#g2"), v = $("#g2view"); let drag = null;
    const apply = () => v.setAttribute("transform", `translate(${view2.tx},${view2.ty}) scale(${view2.k})`);
    svg.addEventListener("wheel", (e) => { e.preventDefault(); const nk = Math.min(4, Math.max(0.3, view2.k * (e.deltaY < 0 ? 1.12 : 0.89))), r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top; view2.tx = mx - ((mx - view2.tx) * nk) / view2.k; view2.ty = my - ((my - view2.ty) * nk) / view2.k; view2.k = nk; apply(); }, { passive: false });
    svg.addEventListener("pointerdown", (e) => { if (e.target.closest(".node")) return; drag = [e.clientX - view2.tx, e.clientY - view2.ty]; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener("pointermove", (e) => { if (drag) { view2.tx = e.clientX - drag[0]; view2.ty = e.clientY - drag[1]; apply(); } });
    svg.addEventListener("pointerup", () => (drag = null));
    svg.addEventListener("click", (e) => { const n = e.target.closest(".node"); if (n) select(n.dataset.nid); else if (!e.target.closest("line")) select(null); });
    svg.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { const n = e.target.closest(".node"); if (n) { e.preventDefault(); select(n.dataset.nid); } } });
    $("#g-hint").textContent = "Колёсико — масштаб · перетаскивание фона — сдвиг · клик или Enter по узлу — детали";
    style2D();
  }
  function style2D() {
    $$("#g2 .node").forEach((g) => { const n = byId[g.dataset.nid]; g.style.display = nodeOn(n) ? "" : "none"; g.classList.toggle("dim", !inChain(n.id)); g.classList.toggle("sel", st.sel === n.id); });
    $$("#g2 .g2-link").forEach((e) => { const l = LINKS[+e.dataset.li]; e.style.display = linkOn(l) ? "" : "none"; e.style.opacity = st.chain && !linkInChain(l) ? 0.12 : 1; });
  }
  function reset2D() { view2 = { k: 1, tx: 0, ty: 0 }; const v = $("#g2view"); if (v) v.setAttribute("transform", "translate(0,0) scale(1)"); }

  // ---------------------------------------------------------------- переключение вида и обновление
  function refresh() {
    if (st.mode === "3d" && G3) {
      G3.nodeColor(nodeColor).nodeVisibility(nodeOn).linkVisibility(linkOn).linkColor(linkColor)
        .linkWidth((l) => (l.kind === "duplicate" ? 0.3 : (l.kind === "contradiction" ? 1.6 : 0.7) * (st.chain && linkInChain(l) ? 1.8 : 1)));
    }
    if (st.mode === "2d") style2D();
  }
  function destroy3D() {
    cancelAnimationFrame(raf);
    if (G3) { try { G3.pauseAnimation(); if (G3._destructor) G3._destructor(); } catch (e) { /* уже уничтожен */ } }
    G3 = null; const l = $("#g-labels"); if (l) l.innerHTML = "";
  }
  function setMode(m, notice) {
    if (m === "3d" && !(webgl && canInflate)) m = "2d";
    const note = $("#g-note");
    if (m === st.mode) return;
    st.mode = m;
    $$("[data-gmode]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.gmode === m));
    $("#g-stage").classList.toggle("is-3d", m === "3d");
    if (m === "2d") { destroy3D(); draw2D(); }
    else { $("#g-canvas").innerHTML = ""; init3D(); }
    if (notice) { note.hidden = false; note.innerHTML = `${ic("alert", 14)} ${esc(notice)}`; setTimeout(() => { if (note.textContent.includes(notice)) note.hidden = true; }, 6000); }
    else if (m === "2d") note.hidden = true;
    side();
  }
  RL.RENDER.graph = (el) => {
    render(el);
    if (window.ResizeObserver && $("#g-canvas")) {
      const ro = new ResizeObserver(() => { const b = $("#g-canvas"); if (!b) return; if (G3) G3.width(b.clientWidth).height(b.clientHeight); });
      ro.observe($("#g-canvas"));
    }
  };
  RL.ONSHOW.graph = () => { if (!st.mode) { if (NODES.length) firstMode(); return; } if (G3) { G3.resumeAnimation(); const b = $("#g-canvas"); G3.width(b.clientWidth).height(b.clientHeight); loop(); } };
  RL.ONHIDE.graph = () => { if (G3) G3.pauseAnimation(); cancelAnimationFrame(raf); };
  document.addEventListener("reqlens:theme", () => { if (G3) G3.backgroundColor(css("--surface") || "#ffffff"); });
})();
