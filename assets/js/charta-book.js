/* Imperiale Charta – Buchmodus
   Baut aus dem vorhandenen Charta-Text (article.doc) ein blätterbares Buch mit
   Umblätter-Animation und synthetisiertem Papiergeräusch (Web Audio, keine Dateien). */
(function () {
  "use strict";

  var article = document.querySelector("article.doc");
  if (!article) return;

  var lang = document.documentElement.getAttribute("lang") === "en" ? "en" : "de";
  var T = {
    de: { view: "Ansicht", read: "Lesemodus", book: "Buchmodus", hint: "Die Charta als gebundenes Buch zum Blättern.",
          close: "Zum Lesemodus", prev: "Zurück blättern", next: "Weiter blättern", toc: "Inhalt", page: "Seite", of: "von",
          cover: "Einband", back: "Rückseite", soundOn: "Ton an", soundOff: "Ton aus", sound: "Papiergeräusch",
          tocTitle: "Inhaltsverzeichnis", dlg: "Die Imperiale Charta als Buch", preamble: "Präambel", section: "Abschnitt" },
    en: { view: "View", read: "Reading mode", book: "Book mode", hint: "The Charter as a bound book you can page through.",
          close: "Reading mode", prev: "Previous page", next: "Next page", toc: "Contents", page: "Page", of: "of",
          cover: "Cover", back: "Back cover", soundOn: "Sound on", soundOff: "Sound off", sound: "Paper sound",
          tocTitle: "Contents", dlg: "The Imperial Charter as a book", preamble: "Preamble", section: "Section" }
  }[lang];

  var ICON = {
    book: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3.5C6.6 2.6 4.6 2.3 2 2.5v9.5c2.6-.2 4.6.1 6 1 1.4-.9 3.4-1.2 6-1V2.5c-2.6-.2-4.6.1-6 1zM8 3.5V13"/></svg>',
    read: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 2.5h10v11H3zM5.5 5.5h5M5.5 8h5M5.5 10.5h3"/></svg>',
    prev: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3L5 8l5 5"/></svg>',
    next: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3l5 5-5 5"/></svg>',
    list: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M5.5 4h8M5.5 8h8M5.5 12h8M2.5 4h.01M2.5 8h.01M2.5 12h.01"/></svg>',
    on: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 6h2.5L8 3v10L4.5 10H2zM10.5 5.5a3.5 3.5 0 010 5M12.3 3.7a6 6 0 010 8.6"/></svg>',
    off: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 6h2.5L8 3v10L4.5 10H2zM10.5 6l3.5 4M14 6l-3.5 4"/></svg>',
    x: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/></svg>'
  };

  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignorieren */ } }
  };

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  /* =====================================================================
     Ton: Papier wird mit gefiltertem Rauschen nachgebildet
     ===================================================================== */
  var Sound = (function () {
    var ctx = null, noise = null, master = null;
    var enabled = store.get("ig-charta-sound") !== "off";

    function init() {
      if (ctx) { if (ctx.state === "suspended") ctx.resume(); return !!ctx; }
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      try {
        ctx = new AC();
        master = ctx.createGain();
        master.gain.value = 0.8;
        master.connect(ctx.destination);
        var len = ctx.sampleRate * 1.5, buf = ctx.createBuffer(1, len, ctx.sampleRate), d = buf.getChannelData(0), last = 0;
        for (var i = 0; i < len; i++) { var w = Math.random() * 2 - 1; last = (last + 0.02 * w) / 1.02; d[i] = (w * 0.6 + last * 8); }
        noise = buf;
      } catch (e) { ctx = null; return false; }
      return true;
    }

    function burst(t0, dur, f0, f1, q, peak, type) {
      var src = ctx.createBufferSource();
      src.buffer = noise;
      src.playbackRate.value = 0.9 + Math.random() * 0.3;
      var bp = ctx.createBiquadFilter();
      bp.type = type || "bandpass";
      bp.Q.value = q;
      bp.frequency.setValueAtTime(f0, t0);
      bp.frequency.exponentialRampToValueAtTime(f1, t0 + dur);
      var g = ctx.createGain();
      // unregelmäßige Hüllkurve = raschelndes Papier
      var n = 24, curve = new Float32Array(n);
      for (var i = 0; i < n; i++) {
        var x = i / (n - 1), env = Math.sin(Math.PI * Math.pow(x, 0.7));
        curve[i] = peak * env * (0.55 + Math.random() * 0.45);
      }
      g.gain.setValueCurveAtTime(curve, t0, dur);
      src.connect(bp); bp.connect(g); g.connect(master);
      src.start(t0, Math.random() * 0.8, dur + 0.05);
    }

    function click(t0, vol) {
      var src = ctx.createBufferSource();
      src.buffer = noise;
      var hp = ctx.createBiquadFilter();
      hp.type = "highpass"; hp.frequency.value = 3500 + Math.random() * 3000;
      var g = ctx.createGain();
      g.gain.setValueAtTime(vol, t0);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.025);
      src.connect(hp); hp.connect(g); g.connect(master);
      src.start(t0, Math.random(), 0.04);
    }

    function thump(t0, vol, f) {
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(f, t0);
      o.frequency.exponentialRampToValueAtTime(f * 0.45, t0 + 0.22);
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(vol, t0 + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.3);
      o.connect(g); g.connect(master);
      o.start(t0); o.stop(t0 + 0.32);
    }

    return {
      get enabled() { return enabled; },
      set: function (on) { enabled = on; store.set("ig-charta-sound", on ? "on" : "off"); if (on) init(); },
      unlock: function () { if (enabled) init(); },
      /* Seite wird umgeblättert */
      page: function (strong) {
        if (!enabled || !init()) return;
        var t = ctx.currentTime + 0.01, d = 0.42 + Math.random() * 0.12;
        burst(t, d, 1400 + Math.random() * 600, 4600 + Math.random() * 900, 0.7, strong ? 0.5 : 0.38, "bandpass");
        burst(t + 0.04, d * 0.8, 400, 1100, 0.9, 0.22, "bandpass");
        click(t + 0.02, 0.18);
        click(t + d * 0.45, 0.1);
        click(t + d * 0.9, 0.14);
      },
      /* Einband wird geöffnet bzw. geschlossen */
      cover: function () {
        if (!enabled || !init()) return;
        var t = ctx.currentTime + 0.01;
        burst(t, 0.55, 300, 900, 0.8, 0.5, "bandpass");
        burst(t + 0.05, 0.5, 1200, 3500, 0.7, 0.25, "bandpass");
        thump(t + 0.5, 0.55, 110);
        burst(t + 0.48, 0.18, 200, 120, 0.8, 0.45, "lowpass");
      },
      /* Schnelles Überblättern mehrerer Seiten */
      riffle: function () {
        if (!enabled || !init()) return;
        var t = ctx.currentTime + 0.01;
        for (var i = 0; i < 7; i++) { burst(t + i * 0.045, 0.12, 2000 + Math.random() * 1500, 5200, 0.8, 0.22, "bandpass"); click(t + i * 0.045, 0.1); }
      }
    };
  })();

  /* =====================================================================
     Umschalter auf der Seite
     ===================================================================== */
  var bar = el("div", "charta-view");
  bar.innerHTML = '<span class="cv-label">' + T.view + '</span>' +
    '<span class="cv-seg" role="group" aria-label="' + T.view + '">' +
    '<button type="button" data-mode="read" aria-pressed="true">' + ICON.read + T.read + '</button>' +
    '<button type="button" data-mode="book" aria-pressed="false">' + ICON.book + T.book + '</button></span>' +
    '<span class="cv-hint">' + T.hint + '</span>';
  article.parentNode.insertBefore(bar, article);
  var btnRead = bar.querySelector('[data-mode="read"]'), btnBook = bar.querySelector('[data-mode="book"]');
  function setPressed(mode) {
    btnRead.setAttribute("aria-pressed", mode === "read" ? "true" : "false");
    btnBook.setAttribute("aria-pressed", mode === "book" ? "true" : "false");
  }
  btnRead.addEventListener("click", function () { store.set("ig-charta-view", "read"); close(); });
  btnBook.addEventListener("click", function () { store.set("ig-charta-view", "book"); open(); });

  /* =====================================================================
     Inhalt einlesen
     ===================================================================== */
  var H1 = document.querySelector("h1");
  var BOOK_TITLE = H1 ? H1.textContent.trim() : "Imperiale Charta";
  var eyebrow = document.querySelector(".page-head .eyebrow");
  var BOOK_SUB = eyebrow ? eyebrow.textContent.trim() : "";
  var emblemSrc = (function () {
    var a = document.querySelector('.subnav a[aria-current="page"] img');
    return a ? (a.currentSrc || a.src) : "";
  })();

  var sections = [].map.call(article.querySelectorAll(".doc-part"), function (s) {
    var head = s.querySelector("header");
    var num = head.querySelector(".num").textContent.trim();
    var title = head.querySelector("h2").textContent.trim();
    var isPre = s.classList.contains("preamble");
    var blocks = [];
    if (isPre) {
      var wrap = el("div", "bk-pre");
      [].forEach.call(s.querySelectorAll(":scope > p"), function (p) { wrap.appendChild(el("p", "", p.innerHTML)); });
      wrap.appendChild(el("div", "bk-orn", "<i></i>"));
      blocks.push({ node: wrap });
    } else {
      [].forEach.call(s.querySelectorAll(".article-par"), function (ap) {
        var a = el("div", "bk-art");
        a.dataset.anchor = ap.id;
        var n = el("span", "n", "");
        n.textContent = ap.querySelector(".par").textContent.trim();
        a.appendChild(n);
        var body = ap.querySelector(".body").cloneNode(true);
        while (body.firstChild) a.appendChild(body.firstChild);
        blocks.push({ node: a, anchor: ap.id });
      });
    }
    return { id: s.id, num: num, title: title, pre: isPre, blocks: blocks };
  });

  /* =====================================================================
     Buch bauen
     ===================================================================== */
  var overlay, stage, scene, book, bookEl, shadow, stackL, stackR, hitPrev, hitNext;
  var btnPrev, btnNext, btnToc, btnSound, ind, prog, menu, measure;
  var built = false, isOpen = false, single = false;
  var pages = [];     // { cls, build(), run, no, anchor[] }
  var leaves = [];    // DOM-Blätter
  var cur = 0;        // Anzahl umgeblätterter Blätter (Doppelseite) bzw. aktuelle Seite (Einzelseite)
  var N = 0;
  var busy = 0, geo = null, lastFocus = null;

  function buildShell() {
    overlay = el("div", "bk-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", T.dlg);
    overlay.tabIndex = -1;
    overlay.innerHTML =
      '<div class="bk-stage"><div class="bk-scene"><div class="bk-shadow"></div><div class="bk-book"></div></div></div>' +
      '<div class="bk-bar"><div class="bk-progress"></div>' +
      '<div class="bk-menu" role="menu" aria-label="' + T.tocTitle + '"></div>' +
      '<div class="bk-grp l"><button type="button" class="bk-btn" data-act="toc" aria-haspopup="true" aria-expanded="false">' + ICON.list + '<span class="lbl">' + T.toc + '</span></button></div>' +
      '<button type="button" class="bk-btn" data-act="prev" aria-label="' + T.prev + '">' + ICON.prev + '</button>' +
      '<span class="bk-ind" aria-live="polite"></span>' +
      '<button type="button" class="bk-btn" data-act="next" aria-label="' + T.next + '">' + ICON.next + '</button>' +
      '<div class="bk-grp r"><button type="button" class="bk-btn" data-act="sound" aria-pressed="true" title="' + T.sound + '"></button>' +
      '<button type="button" class="bk-btn" data-act="close">' + ICON.x + '<span class="lbl">' + T.close + '</span></button></div></div>';
    stage = overlay.querySelector(".bk-stage");
    scene = overlay.querySelector(".bk-scene");
    shadow = overlay.querySelector(".bk-shadow");
    bookEl = overlay.querySelector(".bk-book");
    btnPrev = overlay.querySelector('[data-act="prev"]');
    btnNext = overlay.querySelector('[data-act="next"]');
    btnToc = overlay.querySelector('[data-act="toc"]');
    btnSound = overlay.querySelector('[data-act="sound"]');
    ind = overlay.querySelector(".bk-ind");
    prog = overlay.querySelector(".bk-progress");
    menu = overlay.querySelector(".bk-menu");
    measure = el("div", "bk-measure");
    overlay.appendChild(measure);
    document.body.appendChild(overlay);

    btnPrev.addEventListener("click", function () { step(-1); });
    btnNext.addEventListener("click", function () { step(1); });
    overlay.querySelector('[data-act="close"]').addEventListener("click", function () { store.set("ig-charta-view", "read"); close(); });
    btnSound.addEventListener("click", function () { Sound.set(!Sound.enabled); updateSoundBtn(); if (Sound.enabled) Sound.page(); });
    btnToc.addEventListener("click", function (e) { e.stopPropagation(); toggleMenu(); });
    overlay.addEventListener("click", function (e) { if (menu.classList.contains("is-open") && !menu.contains(e.target)) toggleMenu(false); });
    updateSoundBtn();

    // Wischgesten
    var sx = null, sy = 0;
    stage.addEventListener("touchstart", function (e) { if (e.touches.length === 1) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; } }, { passive: true });
    stage.addEventListener("touchend", function (e) {
      if (sx === null) return;
      var t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
      sx = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.4) step(dx < 0 ? 1 : -1);
    }, { passive: true });

    window.addEventListener("resize", onResize);
    document.addEventListener("keydown", onKey);
  }

  function updateSoundBtn() {
    var on = Sound.enabled;
    btnSound.innerHTML = (on ? ICON.on : ICON.off) + '<span class="lbl">' + (on ? T.soundOn : T.soundOff) + '</span>';
    btnSound.setAttribute("aria-pressed", on ? "true" : "false");
  }

  /* ---------- Geometrie ---------- */
  function computeGeo() {
    var cs = getComputedStyle(stage);
    var W = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    var H = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    var sgl = window.innerWidth < 860;
    var pw, ph;
    if (sgl) {
      ph = Math.min(H, 840);
      pw = Math.min(W, 560, ph * 0.82);
      ph = Math.min(H, 840, pw / 0.56);
    } else {
      ph = Math.min(H, 820);
      pw = Math.min(W / 2, ph * 0.74, 560);
      ph = Math.min(ph, pw / 0.6);
    }
    pw = Math.floor(pw); ph = Math.floor(ph);
    return { single: sgl, pw: pw, ph: ph, fs: Math.max(12.5, Math.min(20, pw * 0.0385)), px: Math.round(pw * 0.095), py: Math.round(ph * 0.06) };
  }

  /* ---------- Seiten erzeugen & umbrechen ---------- */
  function pageEl(cls, side) {
    var p = el("div", "bk-page " + (cls || "") + (side ? " is-" + side : ""));
    return p;
  }

  function paginate(g) {
    var out = [];
    // Messseite in Originalgröße
    measure.style.width = g.pw + "px";
    measure.style.height = g.ph + "px";
    measure.style.setProperty("--bk-fs", g.fs + "px");
    measure.style.setProperty("--bk-px", g.px + "px");
    measure.style.setProperty("--bk-py", g.py + "px");
    function newMeasure() {
      measure.innerHTML = "";
      var pg = pageEl("", "right");
      pg.style.cssText = "position:absolute;inset:0";
      pg.innerHTML = '<div class="bk-run">x</div><div class="bk-inner"></div><div class="bk-no">0</div>';
      measure.appendChild(pg);
      return pg.querySelector(".bk-inner");
    }
    var inner = newMeasure(), cur = null;
    function fits() { return inner.scrollHeight <= inner.clientHeight + 1; }
    function flush() { if (cur && cur.nodes.length) out.push(cur); cur = null; inner = newMeasure(); }
    function add(node, sec, anchor) {
      if (!cur) cur = { run: sec.title, nodes: [], anchors: [] };
      inner.appendChild(node);
      if (!fits() && cur.nodes.length) {
        inner.removeChild(node);
        flush();
        cur = { run: sec.title, nodes: [], anchors: [] };
        inner.appendChild(node);
      }
      cur.nodes.push(node.cloneNode(true));
      if (anchor) cur.anchors.push(anchor);
      // Original bleibt für die Messung stehen
    }
    sections.forEach(function (sec) {
      flush();
      if (sec.pre) {
        var hd0 = el("div", "bk-sec", '<span class="num"></span><h2></h2><div class="bk-orn"><i></i></div>');
        hd0.querySelector(".num").textContent = T.section === "" ? "" : "";
        hd0.querySelector("h2").textContent = sec.title;
        hd0.querySelector(".num").textContent = "";
        add(hd0, sec, sec.id);
        add(sec.blocks[0].node.cloneNode(true), sec);
        return;
      }
      var hd = el("div", "bk-sec", '<span class="num"></span><h2></h2><div class="bk-orn"><i></i></div>');
      hd.querySelector(".num").textContent = sec.num;
      hd.querySelector("h2").textContent = sec.title;
      add(hd, sec, sec.id);
      sec.blocks.forEach(function (b) { add(b.node.cloneNode(true), sec, b.anchor); });
    });
    flush();
    measure.innerHTML = "";
    return out;
  }

  function buildPages(g) {
    var content = paginate(g);
    pages = [];
    // Einband außen
    pages.push({ kind: "cover" });
    // Vorsatz innen + Titelseite
    pages.push({ kind: "cover-in" });
    pages.push({ kind: "title" });
    // Inhaltsverzeichnis
    pages.push({ kind: "toc" });
    // Textseiten
    content.forEach(function (c, i) { pages.push({ kind: "text", data: c, no: i + 1 }); });
    // gerade Seitenzahl für Doppelseiten (Rückseite braucht eine Gegenseite)
    if (!g.single && pages.length % 2 === 1) pages.push({ kind: "blank" });
    pages.push({ kind: "backcover" });
    if (!g.single && pages.length % 2 === 1) pages.splice(pages.length - 1, 0, { kind: "blank" });
    // Seitenzahlen für Verzeichnis
    var tocPage = {};
    pages.forEach(function (p, i) {
      if (p.kind === "text") (p.data.anchors || []).forEach(function (a) { if (!(a in tocPage)) tocPage[a] = i; });
    });
    pages.tocMap = tocPage;
  }

  function faceHTML(p, idx, g) {
    var side = (!g.single && idx % 2 === 0) ? "right" : (!g.single ? "left" : "right");
    // Doppelseite: gerade Indizes = rechte Seite (Vorderseite des Blatts), ungerade = linke Seite
    var f = el("div", "bk-face " + (p.kind === "cover" ? "cover " : p.kind === "cover-in" ? "cover-in " : p.kind === "backcover" ? "backcover " : "") + side);
    var pg;
    if (p.kind === "cover") {
      f.innerHTML = '<div class="bk-cover" style="font-size:' + (g.pw * 0.036) + 'px"><div class="frame"></div>' +
        (emblemSrc ? '<img src="' + emblemSrc + '" alt="">' : '') +
        '<div class="k">Imperium Germanicum</div><h2></h2><div class="s"></div><div class="bk-orn"><i></i></div></div>';
      f.querySelector("h2").textContent = BOOK_TITLE;
      f.querySelector(".s").textContent = BOOK_SUB;
      return f;
    }
    if (p.kind === "backcover") {
      f.innerHTML = '<div class="frame"></div><div class="emb"></div>';
      return f;
    }
    if (p.kind === "cover-in") return f;
    pg = pageEl("", side === "right" ? "right" : "left");
    pg.style.setProperty("--bk-fs", g.fs + "px");
    pg.style.setProperty("--bk-px", g.px + "px");
    pg.style.setProperty("--bk-py", g.py + "px");
    if (p.kind === "blank") { f.classList.add("bk-blank"); f.appendChild(pg); return f; }
    if (p.kind === "title") {
      pg.classList.add("bk-title");
      pg.innerHTML = '<div class="inner">' + (emblemSrc ? '<img src="' + emblemSrc + '" alt="">' : '') +
        '<span class="k">Imperium Germanicum</span><h2></h2><p></p><div class="bk-orn" style="width:40%"><i></i></div></div>';
      pg.querySelector("h2").textContent = BOOK_TITLE;
      pg.querySelector("p").textContent = BOOK_SUB;
    } else if (p.kind === "toc") {
      pg.classList.add("bk-toc");
      var h = el("h2"); h.textContent = T.tocTitle;
      pg.appendChild(h);
      pg.appendChild(el("div", "bk-orn", "<i></i>"));
      var ol = el("ol");
      sections.forEach(function (s) {
        var li = el("li"), a = el("a");
        a.href = "#" + s.id;
        a.innerHTML = '<span class="r"></span><span class="t"></span><span class="p"></span>';
        a.querySelector(".r").textContent = s.pre ? "–" : s.num;
        a.querySelector(".t").textContent = s.title;
        a.querySelector(".p").textContent = (pages.tocMap[s.id] + 1);
        a.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); goToPage(pages.tocMap[s.id]); });
        li.appendChild(a); ol.appendChild(li);
      });
      pg.appendChild(ol);
    } else {
      var run = el("div", "bk-run");
      run.textContent = side === "left" ? BOOK_TITLE : p.data.run;
      var inner = el("div", "bk-inner");
      p.data.nodes.forEach(function (n) { inner.appendChild(n.cloneNode(true)); });
      if (inner.dataset) inner.dataset.n = p.no;
      var no = el("div", "bk-no"); no.textContent = (idx + 1);
      pg.appendChild(run); pg.appendChild(inner); pg.appendChild(no);
      pg.dataset.anchors = (p.data.anchors || []).join(" ");
    }
    f.appendChild(pg);
    return f;
  }

  function buildBook() {
    var g = geo = computeGeo();
    single = g.single;
    buildPages(g);
    bookEl.innerHTML = "";
    bookEl.className = "bk-book" + (single ? " is-single" : "");
    bookEl.style.setProperty("--bk-w", (single ? g.pw : g.pw * 2) + "px");
    bookEl.style.setProperty("--bk-h", g.ph + "px");
    shadow.style.width = "";
    leaves = [];
    bookEl.appendChild(el("div", "bk-spine"));
    stackL = el("div", "bk-stack l"); stackR = el("div", "bk-stack r");
    bookEl.appendChild(stackL); bookEl.appendChild(stackR);

    if (single) {
      N = pages.length;
      pages.forEach(function (p, i) {
        var leaf = el("div", "bk-leaf");
        var front = faceHTML(p, i, g); front.classList.add("front");
        var backF = el("div", "bk-face back bk-blank left");
        leaf.appendChild(front); leaf.appendChild(backF);
        bookEl.appendChild(leaf); leaves.push(leaf);
      });
    } else {
      N = pages.length / 2;
      for (var j = 0; j < N; j++) {
        var leaf2 = el("div", "bk-leaf");
        var f2 = faceHTML(pages[2 * j], 2 * j, g); f2.classList.add("front");
        var b2 = faceHTML(pages[2 * j + 1], 2 * j + 1, g); b2.classList.add("back");
        b2.classList.remove("right"); b2.classList.add("left");
        leaf2.appendChild(f2); leaf2.appendChild(b2);
        bookEl.appendChild(leaf2); leaves.push(leaf2);
      }
    }
    hitPrev = el("button", "bk-hit prev"); hitPrev.type = "button"; hitPrev.setAttribute("aria-label", T.prev);
    hitNext = el("button", "bk-hit next"); hitNext.type = "button"; hitNext.setAttribute("aria-label", T.next);
    hitPrev.addEventListener("click", function () { step(-1); });
    hitNext.addEventListener("click", function () { step(1); });
    bookEl.appendChild(hitPrev); bookEl.appendChild(hitNext);
    if (single) { hitPrev.style.width = "24%"; hitNext.style.width = "24%"; } else { hitPrev.style.left = "0"; hitNext.style.right = "0"; }
    applyState(true);
  }

  /* ---------- Zustand ---------- */
  function maxCur() { return single ? N - 1 : N; }

  function applyState(instant) {
    leaves.forEach(function (lf, j) {
      var flipped = j < cur;
      lf.classList.toggle("is-flipped", flipped);
      lf.classList.toggle("is-hidden", single && flipped);
      lf.style.zIndex = flipped ? j : N - j;
      lf.setAttribute("aria-hidden", "true");
    });
    // sichtbare Seiten als lesbar markieren
    [].forEach.call(bookEl.querySelectorAll(".bk-face"), function (f) { f.setAttribute("aria-hidden", "true"); });
    var vis = visiblePages();
    vis.forEach(function (i) {
      var lf = single ? leaves[i] : leaves[Math.floor(i / 2)];
      if (!lf) return;
      var f = lf.querySelector(i % 2 === 0 || single ? ".front" : ".back");
      if (f) f.setAttribute("aria-hidden", "false");
    });
    var atFront = cur === 0, atBack = single ? cur >= N - 1 : cur >= N;
    bookEl.classList.toggle("is-front", atFront && !single);
    bookEl.classList.toggle("is-back", atBack && !single);
    // Seitenstapel
    var total = single ? N : N;
    var thick = Math.min(16, Math.max(3, geo.pw * 0.03));
    var frac = total ? cur / (single ? Math.max(1, N - 1) : N) : 0;
    stackL.style.setProperty("--bk-st", (frac * thick) + "px");
    stackR.style.setProperty("--bk-st", ((1 - frac) * thick) + "px");
    // Anzeige
    var label;
    if (atFront) label = T.cover;
    else if (atBack) label = T.back;
    else {
      var a = vis[0], b = vis[vis.length - 1];
      label = T.page + " " + (a === b || vis.length === 1 ? (a + 1) : ((vis[0] + 1) + "–" + (b + 1))) + " " + T.of + " " + (pages.length);
    }
    ind.textContent = label;
    btnPrev.disabled = cur <= 0;
    btnNext.disabled = cur >= maxCur();
    hitPrev.disabled = cur <= 0;
    hitNext.disabled = cur >= maxCur();
    var pos = single ? cur / Math.max(1, N - 1) : cur / N;
    prog.style.width = (pos * 100) + "%";
    store.set("ig-charta-page", String(firstAnchorOnView() || ""));
  }

  function visiblePages() {
    if (single) return [cur];
    var v = [];
    if (cur > 0) v.push(2 * cur - 1);
    if (cur < N) v.push(2 * cur);
    return v;
  }

  function firstAnchorOnView() {
    var v = visiblePages();
    for (var i = 0; i < v.length; i++) {
      var p = pages[v[i]];
      if (p && p.kind === "text" && p.data.anchors && p.data.anchors.length) return p.data.anchors[0];
    }
    return "";
  }

  /* ---------- Blättern ---------- */
  var coverNow = function (from, to) { return from === 0 || to === 0 || (!single && (from === N || to === N)) || (single && (from === N - 1 || to === N - 1)); };

  function step(dir, fast) {
    var to = cur + dir;
    if (to < 0 || to > maxCur()) return false;
    var leaf = leaves[dir > 0 ? cur : to];
    if (!leaf) return false;
    var from = cur;
    cur = to;
    leaf.classList.add("is-turning");
    leaf.classList.toggle("is-fast", !!fast);
    leaf.style.zIndex = 1000;
    var thisLeaf = leaf, myIndex = dir > 0 ? from : to;
    if (!fast) {
      if (coverNow(from, to) && (from === 0 || to === 0)) Sound.cover(); else Sound.page(Math.random() > 0.7);
    }
    busy++;
    // Zustand (Klassen) im nächsten Frame setzen, damit die Transition startet
    leaf.classList.toggle("is-flipped", dir > 0);
    if (single) leaf.classList.toggle("is-hidden", dir > 0);
    applyStateLight();
    setTimeout(function () {
      thisLeaf.classList.remove("is-turning", "is-fast");
      thisLeaf.style.zIndex = (thisLeaf.classList.contains("is-flipped")) ? myIndex : N - myIndex;
      busy = Math.max(0, busy - 1);
    }, fast ? 480 : 1020);
    return true;
  }

  function applyStateLight() {
    // wie applyState, ohne die Blattklassen zu überschreiben (laufende Animationen behalten ihren Zustand)
    var vis = visiblePages();
    [].forEach.call(bookEl.querySelectorAll(".bk-face"), function (f) { f.setAttribute("aria-hidden", "true"); });
    vis.forEach(function (i) {
      var lf = single ? leaves[i] : leaves[Math.floor(i / 2)];
      if (!lf) return;
      var f = lf.querySelector(i % 2 === 0 || single ? ".front" : ".back");
      if (f) f.setAttribute("aria-hidden", "false");
    });
    var atFront = cur === 0, atBack = single ? cur >= N - 1 : cur >= N;
    bookEl.classList.toggle("is-front", atFront && !single);
    bookEl.classList.toggle("is-back", atBack && !single);
    var thick = Math.min(16, Math.max(3, geo.pw * 0.03));
    var frac = cur / (single ? Math.max(1, N - 1) : N);
    stackL.style.setProperty("--bk-st", (frac * thick) + "px");
    stackR.style.setProperty("--bk-st", ((1 - frac) * thick) + "px");
    var label;
    if (atFront) label = T.cover;
    else if (atBack) label = T.back;
    else label = T.page + " " + (vis.length === 1 ? (vis[0] + 1) : ((vis[0] + 1) + "–" + (vis[vis.length - 1] + 1))) + " " + T.of + " " + pages.length;
    ind.textContent = label;
    btnPrev.disabled = cur <= 0;
    btnNext.disabled = cur >= maxCur();
    hitPrev.disabled = cur <= 0;
    hitNext.disabled = cur >= maxCur();
    prog.style.width = ((cur / (single ? Math.max(1, N - 1) : N)) * 100) + "%";
    store.set("ig-charta-page", String(firstAnchorOnView() || ""));
  }

  function targetCur(pageIdx) {
    if (single) return Math.max(0, Math.min(N - 1, pageIdx));
    // Seite i liegt auf Blatt floor(i/2); sichtbar, wenn cur = ceil(i/2)
    return Math.max(1, Math.min(N, Math.floor(pageIdx / 2) + (pageIdx % 2 === 0 ? 0 : 1)));
  }

  function goToCur(target, afterTimeout) {
    var dir = target > cur ? 1 : -1, n = Math.abs(target - cur);
    if (!n) return;
    if (n > 2) Sound.riffle();
    var fast = n > 2, i = 0;
    (function next() {
      if (!isOpen || cur === target) return;
      step(dir, fast);
      i++;
      if (cur !== target) setTimeout(next, fast ? Math.max(55, 420 / n) : 260);
    })();
  }

  function goToPage(pageIdx) {
    toggleMenu(false);
    var t = targetCur(pageIdx);
    // Sonderfall Doppelseite: sichtbare Seite vom Start nur über Titelblatt erreichbar
    goToCur(t);
  }

  function goToAnchor(id) {
    for (var i = 0; i < pages.length; i++) {
      var p = pages[i];
      if (p.kind === "text" && p.data.anchors && p.data.anchors.indexOf(id) !== -1) return goToPage(i);
    }
  }

  /* ---------- Inhaltsmenü ---------- */
  function buildMenu() {
    menu.innerHTML = "";
    sections.forEach(function (s) {
      var b = el("button", "", '<span class="r"></span><span class="t"></span><span class="p"></span>');
      b.type = "button"; b.setAttribute("role", "menuitem");
      b.querySelector(".r").textContent = s.pre ? "–" : s.num;
      b.querySelector(".t").textContent = s.title;
      b.querySelector(".p").textContent = (pages.tocMap[s.id] + 1);
      b.addEventListener("click", function () { goToPage(pages.tocMap[s.id]); });
      menu.appendChild(b);
    });
  }
  function toggleMenu(force) {
    var on = force === undefined ? !menu.classList.contains("is-open") : force;
    menu.classList.toggle("is-open", on);
    btnToc.setAttribute("aria-expanded", on ? "true" : "false");
    if (on) { var f = menu.querySelector("button"); if (f) f.focus(); }
  }

  /* ---------- Ereignisse ---------- */
  function onKey(e) {
    if (!isOpen) return;
    var k = e.key;
    if (k === "Escape") { if (menu.classList.contains("is-open")) toggleMenu(false); else { store.set("ig-charta-view", "read"); close(); } e.preventDefault(); }
    else if (k === "ArrowRight" || k === "PageDown") { step(1); e.preventDefault(); }
    else if (k === "ArrowLeft" || k === "PageUp") { step(-1); e.preventDefault(); }
    else if (k === " " && document.activeElement && document.activeElement.tagName !== "BUTTON") { step(e.shiftKey ? -1 : 1); e.preventDefault(); }
    else if (k === "Home") { goToCur(0); e.preventDefault(); }
    else if (k === "End") { goToCur(maxCur()); e.preventDefault(); }
    else if (k === "m" || k === "M") { Sound.set(!Sound.enabled); updateSoundBtn(); }
    else if (k === "Tab") {
      var f = [].filter.call(overlay.querySelectorAll("button:not([disabled]), a[href]"), function (x) { return x.offsetParent !== null; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === overlay)) { last.focus(); e.preventDefault(); }
      else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
    }
  }

  var rzT = null;
  function onResize() {
    if (!isOpen) return;
    clearTimeout(rzT);
    rzT = setTimeout(function () {
      var g = computeGeo();
      if (geo && g.single === geo.single && g.pw === geo.pw && g.ph === geo.ph) return;
      var anchor = firstAnchorOnView(), wasFront = cur === 0;
      var wasBack = cur >= maxCur() && cur > 0;
      bookEl.style.transition = "none";
      buildBook();
      if (anchor) { var t = pages.findIndex(function (p) { return p.kind === "text" && p.data.anchors.indexOf(anchor) !== -1; }); if (t >= 0) { cur = targetCur(t); } }
      else if (wasFront) cur = 0;
      else if (wasBack) cur = maxCur();
      applyState(true);
      buildMenu();
      void bookEl.offsetWidth;
      bookEl.style.transition = "";
    }, 220);
  }

  /* ---------- Öffnen / Schließen ---------- */
  function open(startAnchor) {
    if (isOpen) return;
    if (!built) { buildShell(); built = true; }
    lastFocus = document.activeElement;
    isOpen = true;
    setPressed("book");
    Sound.unlock();
    document.documentElement.classList.add("bk-lock");
    overlay.style.display = "flex";
    cur = 0;
    // erst messen, wenn Overlay Größe hat
    overlay.classList.remove("is-open");
    void overlay.offsetWidth;
    buildBook();
    buildMenu();
    requestAnimationFrame(function () {
      overlay.classList.add("is-open");
      overlay.focus();
    });
    var anchor = startAnchor || (location.hash && location.hash.length > 1 ? decodeURIComponent(location.hash.slice(1)) : "") || store.get("ig-charta-page") || "";
    // Einband öffnet sich nach dem Einblenden von selbst
    setTimeout(function () {
      if (!isOpen) return;
      if (anchor && pages.some(function (p) { return p.kind === "text" && p.data.anchors.indexOf(anchor) !== -1; })) goToAnchor(anchor);
      else if (single) step(1);
      else step(1);
    }, 1100);
  }

  function close() {
    setPressed("read");
    if (!isOpen) return;
    isOpen = false;
    toggleMenu(false);
    overlay.classList.remove("is-open");
    document.documentElement.classList.remove("bk-lock");
    setTimeout(function () { if (!isOpen && overlay) overlay.style.display = "none"; }, 520);
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* ignorieren */ } }
    // Zur Position im Lesetext scrollen
    var a = firstAnchorOnView();
    if (a) { var t = document.getElementById(a); if (t && t.scrollIntoView) t.scrollIntoView({ block: "start" }); }
  }

  // Gespeicherte Vorliebe beachten; URL-Schalter ?ansicht=buch / ?view=book hat Vorrang
  var q = /[?&](?:ansicht|view)=(buch|book|lesen|read)\b/.exec(location.search);
  var pref = q ? (/buch|book/.test(q[1]) ? "book" : "read") : store.get("ig-charta-view");
  if (q) store.set("ig-charta-view", pref);
  if (pref === "book") {
    var go = function () { setTimeout(function () { open(); }, 200); };
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(go); else go();
  }
})();
