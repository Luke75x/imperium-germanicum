/* Reichskarte (/karte/): Anzeige und Editor.
   Konfiguration aus #karte-cfg (vom Wiki-Dienst, Modul karte.py), Geodaten aus /karte/geo.json (NUTS-3-Gebiete als SVG-Pfade).
   Anzeige: Zoomen (Mausrad, Knöpfe, Tasten, zwei Finger), Verschieben, Gebiet unter dem Zeiger, Suche, Legende hebt Teilstaaten hervor.
   Klick auf ein Gebiet (Anzeige): Fenster mit Teilstaat, Regent (Landesherr + Fraktionsrolle bzw. Kanzler), Bevölkerung, Fläche;
   angemeldete Regenten beantragen dort eine Namensänderung ihres Teilstaats (entscheidet der Kanzler per Discord-DM des Bots).
   Editor (nur Server-Admins): Gebiete per Klick/Ziehen zuweisen, Pipette, ganze Länder, Teilstaaten anlegen/ändern/löschen,
   Rückgängig/Wiederholen, Speichern mit Bemerkung und Konflikterkennung. Farben der Karte kommen aus den Tokens in site.css. */
(function () {
  "use strict";
  var root = document.querySelector("[data-karte]");
  var cfgEl = document.getElementById("karte-cfg");
  if (!root || !cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent);
  var T = cfg.i18n;
  var EDIT = cfg.modus === "bearbeiten";
  var NS = "http://www.w3.org/2000/svg";
  var surface = root.querySelector(".karte-flaeche");
  var info = root.querySelector(".karte-info");
  var stand = clone(cfg.stand);
  var saved = clone(cfg.stand);
  var geo, svg, defs, layer, hilite, paths = {}, full, view = { x: 0, y: 0, w: 1 };
  var raf = 0;

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fmt(n) { return n.toLocaleString(document.documentElement.lang === "en" ? "en-GB" : "de-DE"); }
  function state(id) { for (var i = 0; i < stand.staaten.length; i++) if (stand.staaten[i].id === id) return stand.staaten[i]; return null; }
  function sorted() { return stand.staaten.slice().sort(function (a, b) { return a.name.localeCompare(b.name, "de"); }); }

  // ---------- Muster ----------
  var swCount = 0;
  function patternBody(s, size) {
    var h = size / 2;
    if (s.muster === "streifen") return '<rect width="' + size + '" height="' + size + '" fill="' + s.farbe + '"/><rect width="' + (size * 0.35) + '" height="' + size + '" fill="' + s.farbe2 + '"/>';
    if (s.muster === "karo") return '<rect width="' + size + '" height="' + size + '" fill="' + s.farbe + '"/><rect width="' + h + '" height="' + h + '" fill="' + s.farbe2 + '"/><rect x="' + h + '" y="' + h + '" width="' + h + '" height="' + h + '" fill="' + s.farbe2 + '"/>';
    return '<rect width="' + size + '" height="' + size + '" fill="' + s.farbe + '"/><circle cx="' + h + '" cy="' + h + '" r="' + (size * 0.22) + '" fill="' + s.farbe2 + '"/>';
  }
  function swatch(s, size) {
    size = size || 18;
    if (!s) return '<svg class="karte-swatch is-leer" viewBox="0 0 18 18" width="' + size + '" height="' + size + '" aria-hidden="true"><rect width="18" height="18"/></svg>';
    if (s.muster === "voll") return '<svg class="karte-swatch" viewBox="0 0 18 18" width="' + size + '" height="' + size + '" aria-hidden="true"><rect width="18" height="18" fill="' + s.farbe + '"/></svg>';
    var id = "ksw" + (++swCount);
    return '<svg class="karte-swatch" viewBox="0 0 18 18" width="' + size + '" height="' + size + '" aria-hidden="true"><defs><pattern id="' + id +
      '" width="6" height="6" patternUnits="userSpaceOnUse"' + (s.muster === "streifen" ? ' patternTransform="rotate(45)"' : "") + ">" +
      patternBody(s, 6) + '</pattern></defs><rect width="18" height="18" fill="url(#' + id + ')"/></svg>';
  }
  function fillOf(s) { return s.muster === "voll" ? s.farbe : "url(#km-" + s.id + ")"; }
  function buildPatterns() {
    defs.innerHTML = stand.staaten.filter(function (s) { return s.muster !== "voll"; }).map(function (s) {
      return '<pattern id="km-' + s.id + '" class="' + (s.muster === "streifen" ? "is-schraeg" : "") + '" width="8" height="8" patternUnits="userSpaceOnUse">' + patternBody(s, 8) + "</pattern>";
    }).join("");
    scalePatterns();
  }
  function scalePatterns() {
    // Muster behalten auf dem Bildschirm ihre Größe, egal wie weit gezoomt ist
    var k = (base || view).w / Math.max(1, surface.clientWidth);
    defs.querySelectorAll("pattern").forEach(function (p) {
      p.setAttribute("patternTransform", "scale(" + k + ")" + (p.classList.contains("is-schraeg") ? " rotate(45)" : ""));
    });
  }
  function paint(id) {
    var p = paths[id], s = state(stand.gebiete[id]);
    if (!p) return;
    // Kontur in der Füllfarbe schließt die feinen Haarfugen zwischen benachbarten Gebieten
    p.style.fill = p.style.stroke = s ? fillOf(s) : "";
  }
  function paintAll() { Object.keys(paths).forEach(paint); }

  // ---------- Aufbau ----------
  fetch(cfg.geo).then(function (r) { if (!r.ok) throw r; return r.json(); }).then(init).catch(function () {
    var l = surface.querySelector(".karte-laden");
    if (l) l.textContent = T.loadError;
  });

  function init(g) {
    geo = g;
    full = { x: 0, y: 0, w: g.breite, h: g.hoehe };
    var html = ['<svg xmlns="' + NS + '" class="karte-svg" preserveAspectRatio="xMidYMid meet"><defs></defs><g class="karte-hg">'];
    g.hintergrund.forEach(function (d) { html.push('<path d="' + d + '"/>'); });
    html.push('</g><g class="karte-gebiete">');
    Object.keys(g.gebiete).forEach(function (k) { html.push('<path data-id="' + k + '" d="' + g.gebiete[k].d + '"/>'); });
    html.push('</g><g class="karte-markierung"></g></svg>');
    surface.innerHTML = html.join("");
    svg = surface.querySelector("svg");
    defs = svg.querySelector("defs");
    layer = svg.querySelector(".karte-gebiete");
    hilite = svg.querySelector(".karte-markierung");
    layer.querySelectorAll("path").forEach(function (p) { paths[p.getAttribute("data-id")] = p; });
    buildPatterns();
    paintAll();
    fillSearch();
    root.classList.toggle("mit-grenzen", EDIT);
    var cb = root.querySelector("[data-grenzen]");
    if (cb) { cb.checked = EDIT; cb.addEventListener("change", function () { root.classList.toggle("mit-grenzen", cb.checked); }); }
    fit(Object.keys(stand.gebiete));
    bindView();
    if (EDIT) initEditor(); else { bindLegend(); bindInfo(); }
    window.addEventListener("resize", function () { setView(view.x + view.w / 2, view.y + view.h / 2, view.w); });
  }

  // ---------- Ausschnitt ----------
  function aspect() { return surface.clientHeight / Math.max(1, surface.clientWidth); }
  function setView(cx, cy, w) {
    w = Math.min(Math.max(w, 120), full.w * 1.3);
    var h = w * aspect();
    view = { x: cx - w / 2, y: cy - h / 2, w: w, h: h };
    schedule();
  }
  // Flüssige Bewegung: Während Ziehen/Zoomen wird das zuletzt gezeichnete Bild nur per CSS-Transform verschoben und skaliert
  // (GPU, ohne die 1500 Gebiete neu zu zeichnen). Erst wenn die Bewegung ruht, wird der Ausschnitt neu gezeichnet.
  // Das SVG ist doppelt so groß wie die sichtbare Fläche, damit beim Verschieben Rand vorhanden ist.
  var base = null, settle = 0, moving = false;
  function schedule() {
    clearTimeout(settle);
    settle = setTimeout(function () { if (!moving) redraw(); }, 160);
    if (raf) return;
    raf = requestAnimationFrame(function () {
      raf = 0;
      if (!base) { redraw(); return; }
      var cw = surface.clientWidth, ch = surface.clientHeight;
      var s1 = cw / view.w, k = base.w / view.w;
      var tx = (base.x + base.w / 2 - view.x - view.w / 2) * s1, ty = (base.y + base.h / 2 - view.y - view.h / 2) * s1;
      if (Math.abs(tx) > cw * 0.42 || Math.abs(ty) > ch * 0.42 || k < 0.55 || k > 4) { redraw(); return; }
      svg.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + k + ")";
    });
  }
  function redraw() {
    clearTimeout(settle);
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    base = { x: view.x, y: view.y, w: view.w, h: view.h };
    svg.setAttribute("viewBox", (view.x - view.w / 2) + " " + (view.y - view.h / 2) + " " + view.w * 2 + " " + view.h * 2);
    svg.style.transform = "";
    scalePatterns();
  }
  function bboxOf(ids) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    ids.forEach(function (id) {
      var p = paths[id]; if (!p) return;
      var b = p.getBBox();
      x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height);
    });
    return x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function fit(ids, minW) {
    var b = (ids && ids.length && bboxOf(ids)) || full;
    var w = Math.max(b.w, b.h / aspect()) * 1.1;
    setView(b.x + b.w / 2, b.y + b.h / 2, Math.max(w, minW || 0));
  }
  function toMap(clientX, clientY) {
    var r = surface.getBoundingClientRect();
    var k = view.w / r.width, top = (r.height - view.h / k) / 2;
    return { x: view.x + (clientX - r.left) * k, y: view.y + (clientY - r.top - top) * k };
  }
  function zoomAt(clientX, clientY, f) {
    var m = toMap(clientX, clientY);
    var w = Math.min(Math.max(view.w / f, 120), full.w * 1.3), k = w / view.w;
    var cx = m.x - (m.x - (view.x + view.w / 2)) * k, cy = m.y - (m.y - (view.y + view.h / 2)) * k;
    setView(cx, cy, w);
  }
  function zoomCenter(f) {
    var r = surface.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, f);
  }

  // ---------- Bedienung ----------
  var pointers = {}, drag = null, pinch = null, spaceDown = false, stroke = null, hoverId = null;

  function regionAt(e) {
    var el = document.elementFromPoint(e.clientX, e.clientY);
    return el && el.parentNode === layer ? el.getAttribute("data-id") : null;
  }
  function panMode(e) {
    return !EDIT || spaceDown || e.button === 1 || tool === "verschieben" || e.pointerType === "touch" && Object.keys(pointers).length > 1;
  }

  function bindView() {
    root.querySelectorAll("[data-zoom]").forEach(function (b) {
      b.addEventListener("click", function () {
        var z = b.getAttribute("data-zoom");
        if (z === "fit") fit(Object.keys(stand.gebiete)); else zoomCenter(z === "in" ? 1.6 : 1 / 1.6);
      });
    });
    surface.addEventListener("wheel", function (e) {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, Math.pow(1.0018, -e.deltaY * (e.deltaMode === 1 ? 30 : 1)));
    }, { passive: false });
    surface.addEventListener("pointerdown", function (e) {
      surface.focus({ preventScroll: true });
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (ids.length === 2) {
        endStroke();
        var a = pointers[ids[0]], b = pointers[ids[1]];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) };
        drag = null;
        moving = true;
        return;
      }
      if (panMode(e)) {
        drag = { x: e.clientX, y: e.clientY, moved: false };
        moving = true;
        surface.setPointerCapture(e.pointerId);
        surface.classList.add("is-ziehen");
      } else if (e.button === 0) {
        e.preventDefault();
        startStroke(e);
      }
    });
    surface.addEventListener("pointermove", function (e) {
      if (pointers[e.pointerId]) pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (pinch && ids.length === 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch.d > 0) zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, d / pinch.d);
        pinch.d = d;
        return;
      }
      if (drag) {
        var k = view.w / surface.clientWidth, dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        setView(view.x + view.w / 2 - dx * k, view.y + view.h / 2 - dy * k, view.w);
        drag.x = e.clientX; drag.y = e.clientY;
        return;
      }
      if (stroke) { if (e.buttons === 0) endStroke(); else continueStroke(e); return; }
      if (e.pointerType !== "touch") hoverLater(e);
    });
    function up(e) {
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      if (drag && !drag.moved && !EDIT && e.button !== 1) { var hit = regionAt(e); hover(hit); if (hit) openInfo(hit); }  // Klick/Antippen: Angaben zum Gebiet
      if (drag) { drag = null; surface.classList.remove("is-ziehen"); }
      if (moving && !Object.keys(pointers).length) { moving = false; redraw(); }
      endStroke();
    }
    surface.addEventListener("pointerup", up);
    surface.addEventListener("pointercancel", up);
    surface.addEventListener("pointerleave", function (e) { if (!stroke && !drag && e.pointerType !== "touch") hover(null); });
    surface.addEventListener("keydown", function (e) {
      var step = view.w * 0.1;
      var keys = { "+": function () { zoomCenter(1.4); }, "=": function () { zoomCenter(1.4); }, "-": function () { zoomCenter(1 / 1.4); },
        "0": function () { fit(Object.keys(stand.gebiete)); },
        ArrowLeft: function () { setView(view.x + view.w / 2 - step, view.y + view.h / 2, view.w); },
        ArrowRight: function () { setView(view.x + view.w / 2 + step, view.y + view.h / 2, view.w); },
        ArrowUp: function () { setView(view.x + view.w / 2, view.y + view.h / 2 - step, view.w); },
        ArrowDown: function () { setView(view.x + view.w / 2, view.y + view.h / 2 + step, view.w); } };
      if (keys[e.key] && !e.ctrlKey && !e.metaKey) { e.preventDefault(); keys[e.key](); }
    });
    var form = root.querySelector(".karte-suche");
    if (form) {
      var input = form.querySelector("input");
      form.addEventListener("submit", function (e) { e.preventDefault(); find(input.value); });
      input.addEventListener("change", function () { if (searchIndex[input.value]) find(input.value); });
    }
  }

  var hoverPos = null, hoverRaf = 0;
  function hoverLater(e) {
    // Trefferprüfung auf den komplexen Umrissen höchstens einmal je Bild
    hoverPos = { clientX: e.clientX, clientY: e.clientY };
    if (!hoverRaf) hoverRaf = requestAnimationFrame(function () { hoverRaf = 0; hover(regionAt(hoverPos)); });
  }
  function hover(id) {
    if (id === hoverId) return;
    hoverId = id;
    hilite.innerHTML = id ? '<path d="' + geo.gebiete[id].d + '"/>' : "";
    if (!id) { info.innerHTML = ""; info.classList.remove("is-sichtbar"); return; }
    var g = geo.gebiete[id], s = state(stand.gebiete[id]);
    info.innerHTML = '<strong>' + esc(g.n) + "</strong> · " + esc(geo.laender[g.c] || g.c) + "<br>" +
      (s ? swatch(s, 12) + " " + esc(s.name) : esc(T.noState)) + " · " + fmt(g.a) + " km²";
    info.classList.add("is-sichtbar");
  }

  var searchIndex = {};
  function fillSearch() {
    var list = root.querySelector("#karte-gebiete");
    if (!list) return;
    var opts = [];
    Object.keys(geo.gebiete).forEach(function (k) {
      var g = geo.gebiete[k], label = g.n + " (" + (geo.laender[g.c] || g.c) + ")";
      searchIndex[label] = k;
      opts.push(label);
    });
    opts.sort(function (a, b) { return a.localeCompare(b, "de"); });
    list.innerHTML = opts.map(function (o) { return '<option value="' + esc(o) + '">'; }).join("");
  }
  function find(q) {
    q = q.trim();
    var id = searchIndex[q];
    if (!id) {
      var low = q.toLowerCase();
      id = Object.keys(geo.gebiete).find(function (k) { return geo.gebiete[k].n.toLowerCase() === low; }) ||
           Object.keys(geo.gebiete).find(function (k) { return geo.gebiete[k].n.toLowerCase().indexOf(low) === 0; });
    }
    if (!id || !q) { info.textContent = T.notFound; info.classList.add("is-sichtbar"); return; }
    fit([id], 900);
    hoverId = null;
    hover(id);
  }

  // ---------- Legende (Anzeige) ----------
  function focusState(sid) {
    root.classList.toggle("is-fokus", !!sid);
    Object.keys(paths).forEach(function (k) { paths[k].classList.toggle("is-fokus", !!sid && stand.gebiete[k] === sid); });
  }
  function bindLegend() {
    var pinned = null;
    document.querySelectorAll(".karte-legende-item[data-staat]").forEach(function (b) {
      var sid = b.getAttribute("data-staat");
      b.addEventListener("mouseenter", function () { if (!pinned) focusState(sid); });
      b.addEventListener("mouseleave", function () { if (!pinned) focusState(null); });
      b.addEventListener("click", function () {
        pinned = pinned === sid ? null : sid;
        document.querySelectorAll(".karte-legende-item[data-staat]").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-staat") === pinned)); });
        focusState(pinned);
        if (pinned) fit(Object.keys(stand.gebiete).filter(function (k) { return stand.gebiete[k] === sid; }));
      });
    });
  }

  // ---------- Angaben zum Gebiet (Fenster) ----------
  var infoDlg, infoData = null, infoReq = null;
  function loadInfo() {
    if (!infoReq) {
      infoReq = fetch(cfg.info + (cfg.version ? "?version=" + cfg.version : ""), { credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw r; return r.json(); })
        .then(function (j) { infoData = j; return j; })
        .catch(function (e) { infoReq = null; throw e; });
    }
    return infoReq;
  }
  function bindInfo() {
    infoDlg = document.querySelector("[data-gebiet]");
    if (!infoDlg) return;
    infoDlg.querySelector("[data-gebiet-zu]").addEventListener("click", function () { infoDlg.close(); });
    // Ältere Browser ohne overflow: clip: die Fläche darf nie intern scrollen (sonst stimmen die Klickpositionen nicht)
    surface.addEventListener("scroll", function () { surface.scrollTop = 0; surface.scrollLeft = 0; });
    infoDlg.addEventListener("click", function (e) { if (e.target === infoDlg) infoDlg.close(); });  // Klick neben das Fenster
    loadInfo().catch(function () {});
  }
  function pop(id) { return infoData && infoData.bev[id] ? infoData.bev[id] : null; }
  function row(k, v) { return "<tr><th scope=\"row\">" + esc(k) + "</th><td>" + v + "</td></tr>"; }
  function pct(a, b) { return b ? (a / b * 100).toLocaleString(document.documentElement.lang === "en" ? "en-GB" : "de-DE", { maximumFractionDigits: 1 }) + " %" : "–"; }
  function regentHtml(s, r) {
    if (!r) return esc(T.noFaction);
    var names = r.personen.map(function (p) {
      var n = p.url ? '<a href="' + esc(p.url) + '">' + esc(p.name) + "</a>" : esc(p.name);
      return "<strong>" + n + "</strong>" + (p.titel.length ? " <span class=\"karte-titel\">" + esc(p.titel.join(" · ")) + "</span>" : "");
    }).join("<br>");
    if (r.art === "kanzler") return (names || esc(T.noKanzler)) + (names ? '<span class="karte-hinweis">' + esc(T.kanzlerNote) + "</span>" : "");
    if (r.art === "landesherr") return names || esc(T.vacant.replace("{f}", r.fraktion || s.name));
    return esc(T.noFaction);
  }
  function openInfo(id) {
    if (!infoDlg) return;
    loadInfo().then(function () { showInfo(id); }).catch(function () {
      infoDlg.querySelector("[data-gebiet-inhalt]").innerHTML = '<div class="form-status err" role="status">' + esc(T.infoError) + "</div>";
      if (!infoDlg.open) infoDlg.showModal();
    });
  }
  function showInfo(id) {
    var g = geo.gebiete[id], s = state(stand.gebiete[id]), p = pop(id), years = {};
    var html = '<span class="eyebrow">' + esc(geo.laender[g.c] || g.c) + " · " + esc(id) + '</span><h2 id="karte-gebiet-titel">' + esc(g.n) + "</h2>";
    if (s) html += '<p class="karte-gebiet-staat">' + swatch(s, 20) + " " + esc(s.name) + "</p>";
    else html += '<p class="karte-gebiet-staat">' + swatch(null, 20) + " " + esc(T.notReich) + "</p>";
    var rows = [];
    if (s) rows.push(row(T.regent, regentHtml(s, infoData.regenten[s.id])));
    rows.push(row(T.population, p ? fmt(p[0]) + " " + esc(T.inhabitants) : esc(T.noData)));
    rows.push(row(T.area, fmt(g.a) + " km²"));
    if (p && g.a) rows.push(row(T.density, fmt(Math.round(p[0] / g.a)) + " " + esc(T.perKm2)));
    if (p) years[p[1]] = 1;
    html += '<table class="styles-table is-grid karte-gebiet-tabelle"><tbody>' + rows.join("") + "</tbody></table>";
    if (s) {
      var ids = Object.keys(stand.gebiete), n = 0, a = 0, b = 0, ra = 0, rb = 0;
      ids.forEach(function (k) {
        var gg = geo.gebiete[k], pp = pop(k);
        ra += gg.a; if (pp) { rb += pp[0]; years[pp[1]] = 1; }
        if (stand.gebiete[k] === s.id) { n++; a += gg.a; if (pp) b += pp[0]; }
      });
      html += '<h3 class="karte-gebiet-h">' + esc(T.state) + ": " + esc(s.name) + "</h3>" +
        '<table class="styles-table is-grid karte-gebiet-tabelle"><tbody>' +
        row(T.population, fmt(b) + " " + esc(T.inhabitants)) + row(T.area, fmt(a) + " km²") + row(T.regionCount, fmt(n)) +
        row(T.sharePop, pct(b, rb)) + row(T.shareArea, pct(a, ra)) + "</tbody></table>";
    }
    if (s) html += renameHtml(s, infoData.regenten[s.id]);
    var yl = Object.keys(years).sort();
    if (yl.length) html += '<p class="karte-quelle">' + esc(T.source.replace("{j}", yl[yl.length - 1])) + "</p>";
    infoDlg.querySelector("[data-gebiet-inhalt]").innerHTML = html;
    var r = s && infoData.regenten[s.id];
    infoDlg.querySelector("[data-gebiet-wiki]").innerHTML = r && r.wiki ? '<a class="btn btn-navy" href="' + esc(r.wiki) + '">' + esc(T.wikiLink) + "</a>" : "";
    bindRename(id, s);
    if (!infoDlg.open) infoDlg.showModal();
  }

  // Namensänderung: nur für den Regenten des Teilstaats (Prüfung auch auf dem Server)
  function day(ts) { return new Date(ts * 1000).toLocaleDateString(document.documentElement.lang === "en" ? "en-GB" : "de-DE"); }
  function renameHtml(s, r) {
    var ich = infoData.ich;
    if (!ich) {
      if (infoData.angemeldet || !r || r.art !== "landesherr" || cfg.version) return "";
      return '<p class="karte-quelle">' + esc(T.loginHint) + ' <a href="' + esc(cfg.anmelden) + '">' + esc(T.login) + "</a></p>";
    }
    if (ich.regent_von.indexOf(s.id) < 0) return "";
    var a = ich.antraege[s.id], status = "", offen = a && a.status === "offen";
    if (a) {
      var key = { offen: "pending", angenommen: "accepted", abgelehnt: "rejected" }[a.status];
      status = '<div class="form-status ' + (a.status === "abgelehnt" ? "err" : "ok") + '" role="status">' + esc(T[key].replace("{d}", day(a.zeit)).replace("{n}", a.neu)) +
        (a.status === "abgelehnt" && a.antwort ? "<br>" + esc(T.answer) + ": " + esc(a.antwort) : "") + "</div>";
    }
    var form = offen ? "" :
      '<p>' + esc(T.renameIntro) + '</p><button type="button" class="btn btn-line btn-small" data-antrag-oeffnen>' + esc(T.renameBtn) + "</button>" +
      '<form class="form karte-antrag" data-antrag hidden>' +
      '<div class="field"><label for="ka-neu">' + esc(T.newName) + '</label><input id="ka-neu" maxlength="80" required value="' + esc(s.name) + '"></div>' +
      '<div class="field"><label for="ka-grund">' + esc(T.reason) + '</label><textarea id="ka-grund" rows="4" maxlength="1000" required></textarea></div>' +
      '<div data-antrag-meldung></div><button class="btn btn-navy btn-small" type="submit">' + esc(T.send) + "</button></form>";
    return '<h3 class="karte-gebiet-h">' + esc(T.renameH) + "</h3>" + status + form;
  }
  function bindRename(id, s) {
    var open = infoDlg.querySelector("[data-antrag-oeffnen]"), form = infoDlg.querySelector("[data-antrag]");
    if (!open || !form) return;
    open.addEventListener("click", function () { open.hidden = true; form.hidden = false; form.querySelector("#ka-neu").select(); });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = form.querySelector("button[type=submit]"), box = form.querySelector("[data-antrag-meldung]");
      btn.disabled = true;
      fetch(cfg.antrag, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf: cfg.csrf, staat: s.id, neu: form.querySelector("#ka-neu").value, begruendung: form.querySelector("#ka-grund").value }) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) { box.innerHTML = '<div class="form-status err" role="status">' + esc(j.fehler || T.saveError) + "</div>"; btn.disabled = false; return; }
          infoData.ich.antraege[s.id] = j.antrag;
          showInfo(id);
        })
        .catch(function () { box.innerHTML = '<div class="form-status err" role="status">' + esc(T.saveError) + "</div>"; btn.disabled = false; });
    });
  }

  // ---------- Editor ----------
  var tool = EDIT ? "malen" : "verschieben", active = null, undo = [], redo = [];
  var side, list, msg, saveBtn, noteInput, basis = cfg.basis;

  function initEditor() {
    root.classList.add("is-editor");
    side = document.querySelector(".karte-editor");
    list = side.querySelector("[data-staaten]");
    msg = side.querySelector("[data-meldung]");
    saveBtn = side.querySelector('[data-aktion="speichern"]');
    noteInput = side.querySelector("[data-bemerkung]");
    var s0 = sorted()[0];
    active = s0 ? s0.id : null;
    renderStates();
    setTool("malen");
    side.querySelectorAll("[data-werkzeug]").forEach(function (b) { b.addEventListener("click", function () { setTool(b.getAttribute("data-werkzeug")); }); });
    side.querySelector('[data-aktion="undo"]').addEventListener("click", doUndo);
    side.querySelector('[data-aktion="redo"]').addEventListener("click", doRedo);
    side.querySelector('[data-aktion="neu"]').addEventListener("click", function () { openDialog(null); });
    saveBtn.addEventListener("click", doSave);
    var sel = side.querySelector("[data-land]");
    sel.innerHTML = '<option value="">' + esc(T.countryPick) + "</option>" + Object.keys(cfg.laender).map(function (c) {
      return '<option value="' + c + '">' + esc(cfg.laender[c]) + "</option>";
    }).join("");
    side.querySelector('[data-aktion="land"]').addEventListener("click", function () {
      if (!sel.value) { sel.focus(); return; }
      var step = newStep();
      Object.keys(geo.gebiete).forEach(function (k) { if (geo.gebiete[k].c === sel.value) assign(step, k, active); });
      commit(step);
    });
    side.querySelector('[data-aktion="verwerfen"]').addEventListener("click", function (e) {
      if (dirty().n && !confirm(T.leave)) e.preventDefault();
    });
    window.addEventListener("beforeunload", function (e) { if (dirty().n) { e.preventDefault(); e.returnValue = T.leave; } });
    document.addEventListener("keydown", function (e) {
      var typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) || document.querySelector("dialog[open]");
      if ((e.ctrlKey || e.metaKey) && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) doRedo(); else doUndo(); }
      else if ((e.ctrlKey || e.metaKey) && !typing && e.key.toLowerCase() === "y") { e.preventDefault(); doRedo(); }
      else if (e.key === " " && (document.activeElement === surface || document.activeElement === document.body)) { e.preventDefault(); spaceDown = true; surface.classList.add("is-verschieben"); }
    });
    document.addEventListener("keyup", function (e) { if (e.key === " ") { spaceDown = false; surface.classList.toggle("is-verschieben", tool === "verschieben"); } });
    bindDialog();
    updateStatus();
  }

  function setTool(t) {
    tool = t;
    side.querySelectorAll("[data-werkzeug]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-werkzeug") === t)); });
    surface.classList.toggle("is-verschieben", t === "verschieben");
    surface.classList.toggle("is-pipette", t === "pipette");
  }

  function counts() {
    var c = {};
    Object.keys(stand.gebiete).forEach(function (k) { var s = stand.gebiete[k]; c[s] = (c[s] || 0) + 1; });
    return c;
  }
  function renderStates() {
    var c = counts();
    var rows = [{ id: null, name: T.unassigned }].concat(sorted());
    list.innerHTML = rows.map(function (s) {
      var real = s.id !== null;
      return '<li class="karte-staat"><button type="button" class="karte-legende-item" data-waehlen="' + (s.id || "") + '" aria-pressed="' + (s.id === active) + '">' +
        swatch(real ? s : null) + '<span class="karte-legende-name">' + esc(s.name) + "</span>" +
        (real ? '<span class="karte-legende-zahl">' + (c[s.id] || 0) + "</span>" : "") + "</button>" +
        (real ? '<button type="button" class="link-arrow karte-staat-edit" data-bearbeiten="' + s.id + '" aria-label="' + esc(T.edit + ": " + s.name) + '">' + esc(T.edit) + "</button>" : "") + "</li>";
    }).join("");
    list.querySelectorAll("[data-waehlen]").forEach(function (b) {
      b.addEventListener("click", function () { active = b.getAttribute("data-waehlen") || null; if (tool !== "malen") setTool("malen"); renderStates(); });
      var sid = b.getAttribute("data-waehlen");
      if (sid) {
        b.addEventListener("mouseenter", function () { focusState(sid); });
        b.addEventListener("mouseleave", function () { focusState(null); });
      }
    });
    list.querySelectorAll("[data-bearbeiten]").forEach(function (b) {
      b.addEventListener("click", function () { openDialog(state(b.getAttribute("data-bearbeiten"))); });
    });
  }

  // Ein Bearbeitungsschritt: geänderte Gebiete (alt/neu) und ggf. die Teilstaaten vorher/nachher
  function newStep() { return { gebiete: {}, vorher: null, nachher: null }; }
  function assign(step, id, sid) {
    var old = stand.gebiete[id] || null;
    if (old === sid) return;
    if (!(id in step.gebiete)) step.gebiete[id] = [old, sid]; else step.gebiete[id][1] = sid;
    if (sid) stand.gebiete[id] = sid; else delete stand.gebiete[id];
    paint(id);
  }
  function commit(step) {
    if (!Object.keys(step.gebiete).length && !step.nachher) return;
    undo.push(step);
    if (undo.length > 200) undo.shift();
    redo = [];
    after();
  }
  function after() {
    renderStates();
    if (hoverId) { var h = hoverId; hoverId = null; hover(h); }
    updateStatus();
  }
  function applyStep(step, back) {
    if (step.nachher) { stand.staaten = clone(back ? step.vorher : step.nachher); buildPatterns(); }
    Object.keys(step.gebiete).forEach(function (k) {
      var v = step.gebiete[k][back ? 0 : 1];
      if (v) stand.gebiete[k] = v; else delete stand.gebiete[k];
      paint(k);
    });
    if (step.nachher) paintAll();
    if (active && !state(active)) active = null;
  }
  function doUndo() { var s = undo.pop(); if (!s) return; applyStep(s, true); redo.push(s); after(); }
  function doRedo() { var s = redo.pop(); if (!s) return; applyStep(s, false); undo.push(s); after(); }

  function startStroke(e) {
    var id = regionAt(e);
    if (tool === "pipette") {
      if (id !== null) { active = stand.gebiete[id] || null; setTool("malen"); renderStates(); }
      return;
    }
    stroke = { step: newStep(), sid: e.shiftKey ? null : active };
    if (id) assign(stroke.step, id, stroke.sid);
  }
  function continueStroke(e) {
    var id = regionAt(e);
    if (id) assign(stroke.step, id, stroke.sid);
    hover(id);
  }
  function endStroke() {
    if (!stroke) return;
    var s = stroke.step;
    stroke = null;
    commit(s);
  }

  function dirty() {
    var a = stand.gebiete, b = saved.gebiete, n = 0, seen = {};
    Object.keys(a).forEach(function (k) { seen[k] = 1; if (a[k] !== b[k]) n++; });
    Object.keys(b).forEach(function (k) { if (!seen[k]) n++; });
    if (JSON.stringify(stand.staaten) !== JSON.stringify(saved.staaten)) n++;
    return { n: n };
  }
  function updateStatus() {
    var d = dirty().n;
    side.querySelector("[data-stand]").textContent = d ? T.changes.replace("{n}", d) : T.noChanges;
    saveBtn.disabled = !d;
    side.querySelector('[data-aktion="undo"]').disabled = !undo.length;
    side.querySelector('[data-aktion="redo"]').disabled = !redo.length;
  }
  function say(text, kind) { msg.innerHTML = text ? '<div class="form-status ' + kind + '" role="status">' + esc(text) + "</div>" : ""; }

  function doSave() {
    saveBtn.disabled = true;
    say("", "");
    fetch(cfg.speichern, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf: cfg.csrf, basis: basis, stand: stand, bemerkung: noteInput.value }) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
      .then(function (res) {
        if (res.j.ok) {
          basis = res.j.version; saved = clone(stand); noteInput.value = ""; undo = []; redo = [];
          say(T.saved, "ok");
        } else if (res.j.konflikt) {
          say(T.conflict.replace("{name}", res.j.name), "err");
        } else {
          say(res.j.fehler || T.saveError, "err");
        }
        updateStatus();
      })
      .catch(function () { say(T.saveError, "err"); updateStatus(); });
  }

  // ---------- Dialog: Teilstaat anlegen / bearbeiten ----------
  var dlg, editing = null;
  function bindDialog() {
    dlg = document.querySelector("[data-dialog]");
    var f = { name: dlg.querySelector("#ks-name"), farbe: dlg.querySelector("#ks-farbe"), muster: dlg.querySelector("#ks-muster"), farbe2: dlg.querySelector("#ks-farbe2"), fraktion: dlg.querySelector("#ks-fraktion") };
    function current() { return { id: editing ? editing.id : "neu", name: f.name.value.trim(), farbe: f.farbe.value.toLowerCase(), muster: f.muster.value, farbe2: f.farbe2.value.toLowerCase(), fraktion: f.fraktion.value }; }
    function preview() {
      var s = current();
      dlg.querySelector("[data-farbe2]").hidden = s.muster === "voll";
      dlg.querySelector("[data-vorschau]").innerHTML = swatch(s, 56);
    }
    [f.farbe, f.muster, f.farbe2].forEach(function (el) { el.addEventListener("input", preview); });
    dlg.preview = preview;
    dlg.fields = f;
    dlg.addEventListener("close", function () {
      if (dlg.returnValue !== "ok") return;
      var s = current(), step = newStep();
      step.vorher = clone(stand.staaten);
      if (editing) {
        var t = state(editing.id);
        t.name = s.name; t.farbe = s.farbe; t.muster = s.muster; t.farbe2 = s.farbe2; t.fraktion = s.fraktion;
      } else {
        var max = stand.staaten.reduce(function (m, x) { return Math.max(m, parseInt(x.id.slice(1), 10) || 0); }, 0);
        s.id = "s" + (max + 1);
        stand.staaten.push(s);
        active = s.id;
      }
      step.nachher = clone(stand.staaten);
      buildPatterns();
      paintAll();
      commit(step);
    });
    dlg.querySelector('button[value="ok"]').addEventListener("click", function (e) {
      var s = current(), err = "";
      if (!s.name) err = T.nameEmpty;
      else if (stand.staaten.some(function (x) { return x.name.toLowerCase() === s.name.toLowerCase() && (!editing || x.id !== editing.id); })) err = T.nameTaken;
      var box = dlg.querySelector("[data-dialog-fehler]");
      box.hidden = !err; box.textContent = err;
      if (err) e.preventDefault();
    });
    dlg.querySelector('[data-aktion="loeschen"]').addEventListener("click", function () {
      if (!editing) return;
      var n = counts()[editing.id] || 0;
      if (!confirm(T.confirmDelete.replace("{name}", editing.name).replace("{n}", n))) return;
      var step = newStep();
      step.vorher = clone(stand.staaten);
      Object.keys(stand.gebiete).forEach(function (k) { if (stand.gebiete[k] === editing.id) assign(step, k, null); });
      stand.staaten = stand.staaten.filter(function (x) { return x.id !== editing.id; });
      step.nachher = clone(stand.staaten);
      if (active === editing.id) active = null;
      buildPatterns();
      dlg.close("cancel");
      commit(step);
    });
  }
  function openDialog(s) {
    editing = s;
    var f = dlg.fields;
    dlg.querySelector("[data-dialog-titel]").textContent = s ? T.editState : T.newState;
    f.name.value = s ? s.name : "";
    f.farbe.value = s ? s.farbe : "#c9a43a";
    f.muster.value = s ? s.muster : "voll";
    f.farbe2.value = s ? s.farbe2 : "#ffffff";
    f.fraktion.value = s ? s.fraktion || "" : "";
    if (f.fraktion.value !== (s ? s.fraktion || "" : "")) f.fraktion.value = "";  // Rolle existiert nicht mehr
    dlg.querySelector("[data-dialog-fehler]").hidden = true;
    dlg.querySelector('[data-aktion="loeschen"]').hidden = !s;
    dlg.preview();
    dlg.returnValue = "";
    dlg.showModal();
    f.name.focus();
  }
})();
