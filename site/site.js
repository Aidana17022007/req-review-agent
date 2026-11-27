/* ReqLens — сайт: тема, язык RU/KK, копирование команды, появление блоков. Страница работает и без JS. */
(function () {
  var d = document.documentElement;
  d.classList.add("js");
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  // тема
  var theme = document.getElementById("theme");
  function themeLabel() {
    if (!theme) return;
    var dark = d.dataset.theme !== "light", kk = d.lang === "kk";
    theme.setAttribute("aria-label", dark ? (kk ? "Жарық тақырып" : "Светлая тема") : (kk ? "Қараңғы тақырып" : "Тёмная тема"));
  }
  if (theme) theme.addEventListener("click", function () {
    var t = d.dataset.theme === "light" ? "dark" : "light";
    d.dataset.theme = t; store.set("reqlens-theme", t); themeLabel();
  });
  themeLabel();

  // язык: русский — в разметке, казахский — словарь ниже
  var KK = {
    "skip": "Мазмұнға өту", "nav.features": "Мүмкіндіктер", "nav.how": "Қалай жұмыс істейді", "nav.bench": "Бенчмарк",
    "try.eyebrow": "Өзіңіз байқап көріңіз", "try.t": "Бір сөйлемді осы жерде тексеріңіз.",
    "try.lead": "Талапты жазыңыз: агенттің сөздік ережелері бұлыңғыр сөздерді белгілеп, қалай түзету керегін түсіндіреді. Модельсіз, серверсіз және кілтсіз — бәрі браузерде есептеледі.",
    "try.label": "Талап мәтіні", "try.ex": "Мысалдар:", "try.go": "Тексеру",
    "try.note": "Бұл — агенттің тек бірінші, сөздік қабаты. Толық тексеру — модель, тест-сынама, талаптар арасындағы қайшылықтар — Studio-да немесе төмендегі бір командамен.",
    "cta.try": "Орнатусыз бағалау", "nav.proof": "Дәлелдер", "cta.pdf": "PDF есеп", "cta.try.studio": "Браузердегі Studio: дайын мысал — прогонсыз және квотасыз; өз файлыңыз — тәулігіне 2 тексеруге дейін.",
    "cta.try.report": "Ұйымдастырушылар құжаты бойынша интерактивті есеп — браузерде ашылады, орнатусыз және кілтсіз.",
    "blind.eyebrow": "Соқыр бағалау", "blind.t": "Агент алғаш көретін құжаттар.",
    "blind.note": "Құжаттарды команда жазған жоқ, ақаулар кілті бөлек сақталды, агент оларға бапталмаған. Сандар — bench/RESULTS.md файлынан.",
    "cta.check": "Құжатты тексеру", "cta.demo": "Демоны көру", "cta.slides": "Қорғау слайдтары", "nav.demo": "Демо",
    "cta.report": "Ұйымдастырушылар құжаты бойынша есепті ашу", "cta.report.s": "Есеп", "cta.own": "Өз құжатыңызды тексеру",
    "hero.t1": "Талаптар ақаусыз —", "hero.t2": "кодтың алғашқы жолына дейін.",
    "hero.lead": "ReqLens талаптар құжатын ISO/IEC/IEEE 29148 және IEEE 830 бойынша тексеріп, есеп жазады: сөзбе-сөз дәйексөз, орны, маңыздылығы және дайын түзету тұжырымы.",
    "kpi.eyebrow": "Нәтиже", "kpi.t1": "Сіздің шолу", "kpi.t2": "процесіңізге арналған.",
    "kpi.found": "ұйымдастырушылар құжатының күтілген ақаулары табылды", "kpi.req": "ұйымдастырушылар құжатындағы талаптар",
    "kpi.findings": "сөзбе-сөз дәйексөзі бар ескерту, оның ішінде маңыздысы:", "kpi.bench": "бенчмарктағы recall / precision",
    "feat.eyebrow": "Мүмкіндіктер", "feat.t1": "Талаптарды шолуға керектің бәрі —", "feat.t2": "агенттің бір жүрісінде.",
    "f1.t": "Given/When/Then тест-сынағы", "f1.d": "Агент әр талапқа қабылдау тестін жазады. Шықпаса — дәйексөзбен тексерілмейтіндіктің дәлелі.",
    "f2.t": "Интерактивті есеп және «Есептен сұра»", "f2.d": "Ақаулар мәтінде белгіленген: басу — түсіндірме, стандарт тармағы және тұжырым. «Есептен сұра» офлайн-көмекшісі HTML-файлдың ішінде, желісіз жауап береді.",
    "f3.t": "Автотүзету", "f3.d": "Түзетілген құжат және «болды → болды» айырмасы; қайта тексеру бұрынғы және кейінгі балды көрсетеді.",
    "f4.t": "Дәйексөз аудиті және галлюцинациядан қорғау", "f4.d": "Әр дәйексөзді код мәтін бойынша тексереді, ойдан шығарылғаны алынып тасталады; сыншы қайталауларды біріктіреді.",
    "f5.t": "Финтех тізімі", "f5.d": "Банк өнімдері үшін толықтық: 2FA, лимиттер, идемпотенттілік, AML, дербес деректер, SLA — тек дәйексөзбен.",
    "f6.t": "Метрикалар", "f6.d": "Құжат балы, әзірлеуге дайындық, критерийлер радары және «ақау құны» — модель емес, код есептейді.",
    "f7.t": "Офлайн режим", "f7.d": "Ollama арқылы жергілікті модель — банк құжаты контурдан шықпайды. Кілтсіз ережелер жұмыс істейді.",
    "f8.t": "Команда үшін", "f8.d": "Excel трассировкасы, Jira үшін CSV, report.json, тапсырысшыға сұрақтар, нұсқаларды салыстыру, GitHub Action, Docker.",
    "f9.t": "Талаптардың 3D графы", "f9.d": "Қайшылықтар, тәуелділіктер және қайталаулар; түйінді басу — мәліметтер мен қайшылық тізбегі.",
    "f10.t": "Studio және көмекші", "f10.d": "Файлды сүйреңіз — қадамдар тікелей жүреді; көмекші «S-01 неге маңызды?» сұрағына талаптар мен нормаларға сілтемелермен жауап береді.",
    "more.t": "Тағы:", "more.d": "финтех тізімі (2FA, лимиттер, идемпотенттілік, AML, дербес деректер, SLA) · құжат балы және «ақау құны» · Ollama арқылы офлайн режим · Excel трассировкасы, Jira үшін CSV, report.json · тапсырысшыға сұрақтар және нұсқаларды салыстыру · қазақша интерфейс · GitHub Action және Docker.",
    "demo.eyebrow": "Демо", "demo.t1": "ReqLens 60 секундта.", "demo.t2": "Ұйымдастырушылар құжаты бойынша нақты жүріс.",
    "demo.note": "Тікелей жүріс, «30 секундтағы қорытынды», дәйексөз аудиті, белгіленген құжат, критерийлер матрицасы және «Дейін / Кейін». Бейне дыбыссыз.",
    "trust.eyebrow": "Сенім", "trust.t": "ТТ-ның міндетті тармағы орындалды", "trust.tz": "ТТ-ға сәйкестік", "foot.tz": "ТТ-ға сәйкестік",
    "trust.d": "Сәйкестік кестесін код жасайды (scripts/tz_check.py): әр тармақ үшін — қайда және немен расталған. Қазылар алқасының ЖИ-көмекшілеріне арналған карта — llms.txt.",
    "how.eyebrow": "Қалай жұмыс істейді", "how.t1": "Модель ұсынады —", "how.t2": "код тексереді.",
    "s1.t": "Жүктеу", "s1.d": "PDF, DOCX, Markdown: кестелер мен тақырыптар танылады, әр жол есепке алынады.",
    "s2.t": "Талаптарды бөлу", "s2.d": "Нөмірлі және нөмірсіз тармақтар; API кестелерінің жолдары мен қабылдау критерийлері — бөлек.",
    "s3.t": "Тексеру және сыншы", "s3.d": "Талапқа 9 критерий, жиынға 6, тест-сынақ, тар жүрістер; сыншы қайталауларды алып тастайды.",
    "s4.t": "Есеп және түзетулер", "s4.d": "ТТ-ның 6 бөлімі, «30 секундтағы қорытынды», түзетілген құжат және талдаушыға сұрақтар.",
    "shots.eyebrow": "Интерфейс", "shots.t1": "Бір есеп —", "shots.t2": "оны оқудың бес тәсілі.",
    "shots.live": "Интерактивті есепті ашу: 3D/2D граф, құжат, тесттер", "tab.doc": "Құжат", "tab.graph": "3D граф", "tab.tests": "Тесттер", "tab.fix": "Түзетулер",
    "bench.eyebrow": "Бенчмарк", "bench.t1": "Тексеруге болатын дәлдік.",
    "b.doc": "Құжат", "b.found": "Табылды", "b.total": "Барлығы",
    "bench.note": "Сандарды модель емес, код есептейді (bench/run.py). Тәуелсіз бағалау — bench/external/PROTOCOL.md бойынша сырттан белгілеу.",
    "start.eyebrow": "Жылдам бастау", "start.t": "Бір команда.", "copy": "Көшіру",
    "start.note": "Алдымен pip install -r requirements.txt және .env ішіне Gemini кілті. Кілтсіз: LLM_PROVIDER=rules — тек агент ережелері.",
    "final.t1": "Құжатыңызды тексеріңіз", "final.t2": "бірнеше минутта.",
    "foot.team": "BCC-HUB × MNU хакатонының командасы", "foot.report": "Есеп", "foot.slides": "Слайдтар",
    "foot.license": "Код — жоба лицензиясы; Inter қарпі — SIL OFL 1.1; ISO/IEC/IEEE 29148 және IEEE 830 — мазмұндамасы, мәтіні емес."
  };
  var nodes = document.querySelectorAll("[data-i18n]");
  var RU = {};
  nodes.forEach(function (n) { RU[n.dataset.i18n] = n.textContent; });
  var langBtn = document.getElementById("lang");
  function setLang(l) {
    d.lang = l;
    nodes.forEach(function (n) { var k = n.dataset.i18n; var v = (l === "kk" ? KK : RU)[k]; if (v) n.textContent = v; });
    if (langBtn) langBtn.textContent = l === "kk" ? "РУС" : "ҚАЗ";
    themeLabel();
    store.set("reqlens-lang", l);
  }
  if (store.get("reqlens-lang") === "kk") setLang("kk");
  if (langBtn) langBtn.addEventListener("click", function () { setLang(d.lang === "kk" ? "ru" : "kk"); });

  // копирование команды
  document.querySelectorAll("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var el = document.querySelector(b.dataset.copy); if (!el || !navigator.clipboard) return;
      var label = b.querySelector("span") || b, old = label.textContent;
      navigator.clipboard.writeText(el.textContent).then(function () {
        label.textContent = d.lang === "kk" ? "Көшірілді" : "Скопировано";
        setTimeout(function () { label.textContent = old; }, 1600);
      });
    });
  });

  // появление блоков и лёгкий параллакс экранов hero
  // контент виден всегда: .reveal только чуть сдвинут (без прозрачности), а через 1 с всё на месте в любом случае
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var items = document.querySelectorAll(".reveal");
  function showAll() { items.forEach(function (n) { n.classList.add("on"); }); }
  if (reduce || !("IntersectionObserver" in window)) { showAll(); return; }
  setTimeout(showAll, 1000);
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("on"); io.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -8% 0px" });
  items.forEach(function (n) { io.observe(n); });
  var screens = document.querySelector(".screens");
  if (screens) window.addEventListener("scroll", function () {
    var y = Math.min(window.scrollY, 600);
    screens.style.transform = "translateY(" + (y * -0.08).toFixed(1) + "px)";
  }, { passive: true });

  // «Проверьте одну фразу»: словарные правила агента (вшиты при сборке, scripts/build_site.py) — в браузере, без сервера
  (function () {
    var sec = document.getElementById("try"), raw = document.getElementById("rl-rules");
    if (!sec || !raw) return;
    var R, EX;
    try {
      R = JSON.parse(raw.textContent); EX = JSON.parse(document.getElementById("rl-examples").textContent);
      R.rules.forEach(function (r) { r.rx = new RegExp(r.p, "giu"); });
      R.andRx = new RegExp(R.and, "iu"); R.kkRx = new RegExp(R.kk, "iu");
      R.sentRx = new RegExp(R.sent, "gu"); R.idRx = new RegExp("^(?:" + R.id + ")", "u");
    } catch (e) { return; }  // старый браузер без Unicode-классов в RegExp — секция остаётся скрытой
    sec.hidden = false;
    var q = document.getElementById("try-q"), out = document.getElementById("try-out");
    var SEV = { ru: { critical: "Критичный", major: "Существенный", minor: "Незначительный" },
                kk: { critical: "Критикалық", major: "Елеулі", minor: "Елеусіз" } };
    var T = { ru: { none: "Словарные правила ничего не нашли. Это не значит, что требование идеально: модель проверит полноту, тестируемость и противоречия.",
                    found: "Найдено замечаний: ", fix: "Как исправить: " },
              kk: { none: "Сөздік ережелер ештеңе таппады. Бұл талап мінсіз дегенді білдірмейді: модель толықтықты, тестіленуді және қайшылықтарды тексереді.",
                    found: "Табылған ескертулер: ", fix: "Қалай түзету керек: " } };
    function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function check(t) {
      var hits = [];
      R.rules.forEach(function (r) {
        var m, seen = {}, ms = []; r.rx.lastIndex = 0;
        while ((m = r.rx.exec(t))) {
          if (!m[0]) { r.rx.lastIndex++; continue; }
          if (r.num && /\d/.test(t.slice(Math.max(0, m.index - 30), m.index + m[0].length + 60))) continue;
          var k = m[0].toLowerCase(); if (seen[k]) continue; seen[k] = 1;
          ms.push([m.index, m.index + m[0].length]);
        }
        if (ms.length) hits.push({ r: r, ms: ms });
      });
      var a = R.andRx.exec(t) || R.kkRx.exec(t);
      if (a || t.split(";").length > 2) hits.push({ r: R.singular, ms: a ? [[a.index, a.index + a[0].length]] : [] });
      else if (t.trim().charAt(0) !== "|") {  // v12: три и больше самостоятельных правила в одном пункте
        var id = R.idRx.exec(t), from = id && /\d/.test(id[0]) ? id[0].length : 0, rules = 0, s;
        R.sentRx.lastIndex = from;
        while ((s = R.sentRx.exec(t))) {
          if (!s[0]) { R.sentRx.lastIndex++; continue; }
          var x = s[0].trim();
          if (x.split(/\s+/).length >= 4 && x.indexOf("→") < 0 && !/^(?:например|т\.\s?е\.|то есть|пример)/i.test(x)) rules++;
        }
        if (rules >= 3) hits.push({ r: R.atomic, ms: [] });
      }
      return hits;
    }
    function render() {
      var t = q.value.trim(), L = d.lang === "kk" ? "kk" : "ru";
      if (!t) { out.innerHTML = ""; return; }
      var hits = check(t), spans = [];
      hits.forEach(function (h) { h.ms.forEach(function (m) { spans.push([m[0], m[1], h.r.sev]); }); });
      spans.sort(function (x, y) { return x[0] - y[0]; });
      var html = "", pos = 0;
      spans.forEach(function (sp) { if (sp[0] < pos) return; html += esc(t.slice(pos, sp[0])) + '<mark class="try-m ' + sp[2] + '">' + esc(t.slice(sp[0], sp[1])) + "</mark>"; pos = sp[1]; });
      html += esc(t.slice(pos));
      var order = { critical: 0, major: 1, minor: 2 };
      hits.sort(function (x, y) { return order[x.r.sev] - order[y.r.sev]; });
      out.innerHTML = '<div class="try-text">' + html + "</div>" + (hits.length
        ? '<p class="note" style="margin:14px 0 8px">' + T[L].found + "<b>" + hits.length + "</b></p><ul class=\"try-list\">" + hits.map(function (h) {
            return '<li><span class="try-sev ' + h.r.sev + '">' + SEV[L][h.r.sev] + "</span> <b>" + esc(h.r.name) + "</b><div>" + esc(h.r.problem) + '</div><div class="try-fix">' + T[L].fix + esc(h.r.fix) + "</div></li>";
          }).join("") + "</ul>"
        : '<p class="note try-ok">' + T[L].none + "</p>");
    }
    window.REQLENS_TRY = function (t) { return check(t).map(function (h) { return h.r.crit + ":" + h.r.sev; }).sort(); };  // для тестов
    document.getElementById("try-form").addEventListener("submit", function (e) { e.preventDefault(); render(); });
    sec.addEventListener("click", function (e) {
      var b = e.target.closest("[data-try]"); if (!b) return;
      q.value = EX[+b.getAttribute("data-try")] || ""; render();
    });
    if (window.MutationObserver) new MutationObserver(render).observe(d, { attributes: true, attributeFilter: ["lang"] });
    render();
  })();

  // v13: Studio на бесплатном Render засыпает. Нажали «Оценить без установки» — ждём /api/health и пишем
  // «Studio просыпается, ~30 с» вместо ошибки; не проснулась за 90 с — предлагаем интерактивный отчёт.
  (function () {
    var note = document.getElementById("wake");
    var links = document.querySelectorAll("a[data-studio]");
    if (!note || !links.length || !window.fetch) return;
    var T = { ru: { wake: "Studio просыпается, ~30 с…", fail: "Studio пока не отвечает — откройте интерактивный отчёт: ", rep: "отчёт" },
              kk: { wake: "Studio оянып жатыр, ~30 с…", fail: "Studio әзірге жауап бермейді — интерактивті есепті ашыңыз: ", rep: "есеп" } };
    function L() { return T[d.lang === "kk" ? "kk" : "ru"]; }
    Array.prototype.forEach.call(links, function (a) {
      a.addEventListener("click", function (e) {
        var href = a.getAttribute("href"); if (!/^https?:/.test(href)) return;
        e.preventDefault();
        var base = href.replace(/\/?(\?.*)?$/, ""), t0 = Date.now(), shown = false;
        var timer = setTimeout(function () { shown = true; note.hidden = false; note.textContent = L().wake; }, 1500);
        (function ping() {
          var ctl = window.AbortController ? new AbortController() : null;
          var kill = ctl && setTimeout(function () { ctl.abort(); }, 8000);
          fetch(base + "/api/health", { cache: "no-store", signal: ctl ? ctl.signal : undefined }).then(function (r) {
            if (kill) clearTimeout(kill);
            if (r.ok) { clearTimeout(timer); location.href = href; return; }
            throw new Error("HTTP " + r.status);
          }).catch(function () {
            if (kill) clearTimeout(kill);
            if (Date.now() - t0 < 90000) { setTimeout(ping, 3000); return; }
            clearTimeout(timer); note.hidden = false;
            note.innerHTML = L().fail + '<a href="report/">' + L().rep + "</a>";
          });
        })();
        if (shown) note.hidden = false;
      });
    });
  })();
})();
