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
  if (theme) theme.addEventListener("click", function () {
    var t = d.dataset.theme === "dark" ? "light" : "dark";
    d.dataset.theme = t; store.set("reqlens-theme", t);
  });

  // язык: русский — в разметке, казахский — словарь ниже
  var KK = {
    "skip": "Мазмұнға өту", "nav.features": "Мүмкіндіктер", "nav.how": "Қалай жұмыс істейді", "nav.bench": "Бенчмарк",
    "cta.check": "Құжатты тексеру", "cta.demo": "Демоны көру", "cta.slides": "Қорғау слайдтары",
    "hero.t1": "Талаптар ақаусыз —", "hero.t2": "кодтың алғашқы жолына дейін.",
    "hero.lead": "ReqLens талаптар құжатын ISO/IEC/IEEE 29148 және IEEE 830 бойынша тексеріп, есеп жазады: сөзбе-сөз дәйексөз, орны, маңыздылығы және дайын түзету тұжырымы.",
    "kpi.eyebrow": "Нәтиже", "kpi.t1": "Сіздің шолу", "kpi.t2": "процесіңізге арналған.",
    "kpi.found": "ұйымдастырушылар құжатының күтілген ақаулары", "kpi.recall": "бенчмарктағы recall", "kpi.precision": "бенчмарктағы precision",
    "kpi.findings": "талаптар / расталған ескертулер",
    "feat.eyebrow": "Мүмкіндіктер", "feat.t1": "Талаптарды шолуға керектің бәрі —", "feat.t2": "агенттің бір жүрісінде.",
    "f1.t": "Given/When/Then тест-сынағы", "f1.d": "Агент әр талапқа қабылдау тестін жазады. Шықпаса — дәйексөзбен тексерілмейтіндіктің дәлелі.",
    "f2.t": "Интерактивті есеп", "f2.d": "Ақаулар құжат мәтінінде белгіленген: басу — түсіндірме, стандарт тармағы және дайын тұжырым.",
    "f3.t": "Автотүзету", "f3.d": "Түзетілген құжат және «болды → болды» айырмасы; қайта тексеру бұрынғы және кейінгі балды көрсетеді.",
    "f4.t": "Галлюцинациядан қорғау", "f4.d": "Әр дәйексөзді код мәтін бойынша тексереді, ойдан шығарылғаны алынып тасталады; сыншы қайталауларды біріктіреді.",
    "f5.t": "Финтех тізімі", "f5.d": "Банк өнімдері үшін толықтық: 2FA, лимиттер, идемпотенттілік, AML, дербес деректер, SLA — тек дәйексөзбен.",
    "f6.t": "Метрикалар", "f6.d": "Құжат балы, әзірлеуге дайындық, критерийлер радары және «ақау құны» — модель емес, код есептейді.",
    "f7.t": "Офлайн режим", "f7.d": "Ollama арқылы жергілікті модель — банк құжаты контурдан шықпайды. Кілтсіз ережелер жұмыс істейді.",
    "f8.t": "Команда үшін", "f8.d": "Excel трассировкасы, Jira үшін CSV, report.json, тапсырысшыға сұрақтар, нұсқаларды салыстыру, GitHub Action, Docker.",
    "f9.t": "Талаптардың 3D графы", "f9.d": "Қайшылықтар, тәуелділіктер және қайталаулар; түйінді басу — мәліметтер мен қайшылық тізбегі.",
    "f10.t": "Studio және көмекші", "f10.d": "Файлды сүйреңіз — қадамдар тікелей жүреді; көмекші «S-01 неге маңызды?» сұрағына сілтемелермен жауап береді.",
    "how.eyebrow": "Қалай жұмыс істейді", "how.t1": "Модель ұсынады —", "how.t2": "код тексереді.",
    "s1.t": "Жүктеу", "s1.d": "PDF, DOCX, Markdown: кестелер мен тақырыптар танылады, әр жол есепке алынады.",
    "s2.t": "Талаптарды бөлу", "s2.d": "Нөмірлі және нөмірсіз тармақтар; API кестелерінің жолдары мен қабылдау критерийлері — бөлек.",
    "s3.t": "Тексеру және сыншы", "s3.d": "Талапқа 9 критерий, жиынға 6, тест-сынақ, тар жүрістер; сыншы қайталауларды алып тастайды.",
    "s4.t": "Есеп және түзетулер", "s4.d": "ТТ-ның 6 бөлімі, «30 секундтағы қорытынды», түзетілген құжат және талдаушыға сұрақтар.",
    "shots.eyebrow": "Интерфейс", "shots.t1": "Бір есеп —", "shots.t2": "оны оқудың бес тәсілі.",
    "tab.doc": "Құжат", "tab.graph": "3D граф", "tab.tests": "Тесттер", "tab.fix": "Түзетулер",
    "bench.eyebrow": "Бенчмарк", "bench.t1": "Тексеруге болатын дәлдік.", "bench.t2": "5 құжат, алдын ала белгілі 67 ақау.",
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
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var items = document.querySelectorAll(".reveal");
  if (reduce || !("IntersectionObserver" in window)) { items.forEach(function (n) { n.classList.add("on"); }); return; }
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("on"); io.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -8% 0px" });
  items.forEach(function (n) { io.observe(n); });
  var screens = document.querySelector(".screens");
  if (screens) window.addEventListener("scroll", function () {
    var y = Math.min(window.scrollY, 600);
    screens.style.transform = "translateY(" + (y * -0.08).toFixed(1) + "px)";
  }, { passive: true });
})();
