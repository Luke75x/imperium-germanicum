/* Organigramm der Reichsverwaltung (/informationen/die-reichsbehoerden/organigramm/): Anzeige und Editor.
   Konfiguration aus #org-cfg (vom Wiki-Dienst, Modul organigramm.py), Amtsträger aus info.json (Discord-Rollen, live).
   Anzeige wie die Reichskarte: Zoomen (Mausrad, Knöpfe, Tasten, zwei Finger), Verschieben, Amt unter dem Zeiger, Suche nach Ämtern und
   Amtsträgern, Gliederung in der Seitenleiste hebt Zweige hervor, Zweige auf- und zuklappen (⊕/⊖), Klick auf ein Amt öffnet ein
   Fenster (Leitung, Amtsträger, Angehörige, Aufgaben), Herunterladen als Bild (PNG, helle Farben, gezeichnet im Browser).
   Layout: Kinder nebeneinander; besteht ein Zweig nur aus Ämtern ohne eigene Untergliederung, stehen sie eingerückt untereinander.
   Editor (nur Server-Admins): Klick auf ein Amt öffnet es im Dialog (Texte DE/EN, Darstellung, Übergeordnet, Rollen, Dekret-IDs,
   Angehörige, Verweis), Neues Amt, Untergeordnetes Amt, Verschieben unter Gleichrangigen, Löschen, Rückgängig/Wiederholen,
   Speichern mit Bemerkung und Konflikterkennung. Farben aus den Tokens in site.css (CSS-Klassen), das Bild nutzt die hellen Werte. */
(function () {
  "use strict";
  var root = document.querySelector("[data-org]");
  var cfgEl = document.getElementById("org-cfg");
  if (!root || !cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent);
  var T = cfg.i18n;
  var EN = cfg.lang === "en";
  var EDIT = cfg.modus === "bearbeiten";
  var surface = root.querySelector(".karte-flaeche");
  var info = root.querySelector(".karte-info");
  var stand = clone(cfg.stand);
  var saved = clone(cfg.stand);
  var personen = [];
  var collapsed = {};
  var boxes = {}, pos = {}, full = { x: 0, y: 0, w: 1, h: 1 }, view = { x: 0, y: 0, w: 1, h: 1 };
  var svg = null, raf = 0, focusSet = null, hoverId = null;

  // Maße des Layouts (SVG-Einheiten = CSS-Pixel bei Zoom 1)
  var BW = 248, PAD = 14, GX = 26, GY = 58, IND = 30, SG = 14;

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fmt(n) { return n.toLocaleString(EN ? "en-GB" : "de-DE"); }
  function node(id) { for (var i = 0; i < stand.knoten.length; i++) if (stand.knoten[i].id === id) return stand.knoten[i]; return null; }
  function kids(id) { return stand.knoten.filter(function (k) { return (k.eltern || "") === (id || ""); }); }
  function roots() { return kids(""); }
  function L(k, f) { return (EN && k[f + "_en"]) || k[f] || ""; }
  function descendants(id) {
    var out = [];
    kids(id).forEach(function (k) { out.push(k.id); out = out.concat(descendants(k.id)); });
    return out;
  }
  function ancestors(id) {
    var out = [], k = node(id), guard = 0;
    while (k && k.eltern && guard++ < 500) { out.push(k.eltern); k = node(k.eltern); }
    return out;
  }
  function holders(k) {
    return personen.filter(function (p) {
      if (k.nutzer.indexOf(p.id) >= 0) return true;
      var any = k.rollen.some(function (r) { return p.rollen.indexOf(r) >= 0; });
      return any && (!k.zusatz || p.rollen.indexOf(k.zusatz) >= 0);
    });
  }
  function members(k) { return k.angehoerige ? personen.filter(function (p) { return p.rollen.indexOf(k.angehoerige) >= 0; }).length : null; }
  function staffed(k) { return k.rollen.length || k.nutzer.length; }
  function linkOf(k) {
    if (!k.link) return "";
    return k.link.charAt(0) === "/" && k.link.indexOf("/en/") !== 0 ? cfg.prefix + k.link : k.link;
  }

  // ---------- Text messen und umbrechen ----------
  var meas = document.createElement("canvas").getContext("2d");
  var css = getComputedStyle(document.documentElement);
  var SERIF = css.getPropertyValue("--serif").trim() || "Georgia, serif";
  var SANS = css.getPropertyValue("--sans").trim() || "sans-serif";
  var F = {
    kurz: { font: "600 10.5px " + SANS, lh: 16, sp: 1.5 },
    titel: { font: "600 18px " + SERIF, lh: 22 },
    gruppe: { font: "600 16px " + SERIF, lh: 20 },
    leitung: { font: "400 12.5px " + SANS, lh: 17 },
    person: { font: "600 13px " + SANS, lh: 18 },
    leer: { font: "italic 400 12.5px " + SANS, lh: 18 }
  };
  function width(text, f) { meas.font = f.font; return meas.measureText(text).width + (f.sp || 0) * text.length; }
  function wrap(text, f, max, maxLines) {
    var words = String(text).split(/\s+/).filter(Boolean), lines = [], cur = "";
    words.forEach(function (w) {
      var t = cur ? cur + " " + w : w;
      if (cur && width(t, f) > max) { lines.push(cur); cur = w; } else cur = t;
    });
    if (cur) lines.push(cur);
    if (maxLines && lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      var last = lines[maxLines - 1];
      while (last && width(last + " …", f) > max) last = last.replace(/\s*\S+$/, "");
      lines[maxLines - 1] = last + " …";
    }
    return lines;
  }

  // Inhalt eines Kastens: Zeilen mit Schrift, Klasse und Abstand
  function measure(k) {
    var inner = BW - 2 * PAD, rows = [], y = PAD, group = k.art === "gruppe";
    function add(lines, f, cls, gap) {
      y += gap || 0;
      lines.forEach(function (t) { rows.push({ t: t, f: f, cls: cls, y: y + f.lh * 0.78 }); y += f.lh; });
    }
    var kurz = L(k, "kurz");
    if (kurz) add(wrap(kurz.toUpperCase(), F.kurz, inner, 2), F.kurz, "org-t-kurz");
    add(wrap(L(k, "titel"), group ? F.gruppe : F.titel, inner, 3), group ? F.gruppe : F.titel, "org-t-titel", kurz ? 2 : 0);
    var leitung = L(k, "leitung");
    if (leitung) add(wrap(leitung, F.leitung, inner, 3), F.leitung, "org-t-leitung", 4);
    var sep = null;
    if (staffed(k)) {
      var h = holders(k);
      y += 10; sep = y - 5;
      if (!h.length) add([T.vacant], F.leer, "org-t-leer");
      else {
        var show = h.length > 3 ? h.slice(0, 2) : h;
        show.forEach(function (p) { add(wrap(p.name, F.person, inner - 14, 1), F.person, "org-t-person"); rows[rows.length - 1].dot = true; });
        if (h.length > 3) add([T.more.replace("{n}", h.length - 2)], F.leer, "org-t-leer");
      }
    }
    return { w: BW, h: Math.round(y + PAD), rows: rows, sep: sep };
  }

  // ---------- Layout ----------
  function visibleKids(id) { return collapsed[id] ? [] : kids(id); }
  function stacked(id) {
    var ks = kids(id);
    return ks.length > 0 && ks.every(function (k) { return !kids(k.id).length; });
  }
  var sizes = {};
  function size(id) {
    var b = boxes[id], ks = visibleKids(id), s;
    if (!ks.length) s = { w: b.w, h: b.h };
    else if (stacked(id)) {
      var mw = 0, sh = 0;
      ks.forEach(function (k) { var c = size(k.id); mw = Math.max(mw, c.w); sh += c.h; });
      s = { w: Math.max(b.w, IND + mw), h: b.h + GY * 0.5 + sh + (ks.length - 1) * SG };
    } else {
      var tw = 0, mh = 0;
      ks.forEach(function (k) { var c = size(k.id); tw += c.w; mh = Math.max(mh, c.h); });
      tw += (ks.length - 1) * GX;
      s = { w: Math.max(b.w, tw), h: b.h + GY + mh };
    }
    sizes[id] = s;
    return s;
  }
  var lines = [];
  function place(id, x, y) {
    var b = boxes[id], s = sizes[id], ks = visibleKids(id);
    if (!ks.length) { pos[id] = { x: x + (s.w - b.w) / 2, y: y }; return; }
    if (stacked(id)) {
      pos[id] = { x: x, y: y };
      var cy = y + b.h + GY * 0.5, lx = x + IND / 2, last = 0;
      ks.forEach(function (k) {
        place(k.id, x + IND, cy);
        var my = cy + Math.min(boxes[k.id].h / 2, 30);
        lines.push({ kid: k.id, d: "M" + lx + " " + my + "H" + (x + IND) });
        last = my;
        cy += sizes[k.id].h + SG;
      });
      lines.push({ kid: id, trunk: ks.map(function (k) { return k.id; }), d: "M" + lx + " " + (y + b.h) + "V" + last });
      return;
    }
    var tw = -GX;
    ks.forEach(function (k) { tw += sizes[k.id].w + GX; });
    pos[id] = { x: x + (s.w - b.w) / 2, y: y };
    var px = pos[id].x + b.w / 2, my = y + b.h + GY / 2, cx = x + (s.w - tw) / 2, xs = [];
    ks.forEach(function (k) {
      place(k.id, cx, y + b.h + GY);
      var kx = pos[k.id].x + boxes[k.id].w / 2;
      xs.push(kx);
      lines.push({ kid: k.id, d: "M" + kx + " " + my + "V" + (y + b.h + GY) });
      cx += sizes[k.id].w + GX;
    });
    lines.push({ kid: id, trunk: ks.map(function (k) { return k.id; }), d: "M" + px + " " + (y + b.h) + "V" + my +
      (ks.length > 1 ? "M" + Math.min.apply(null, xs) + " " + my + "H" + Math.max.apply(null, xs) : "M" + px + " " + my + "H" + xs[0]) });
  }
  function layout() {
    boxes = {}; pos = {}; sizes = {}; lines = [];
    stand.knoten.forEach(function (k) { boxes[k.id] = measure(k); });
    var x = 0, h = 0;
    roots().forEach(function (k) { var s = size(k.id); place(k.id, x, 0); x += s.w + GX * 2; h = Math.max(h, s.h); });
    full = { x: 0, y: 0, w: Math.max(1, x - GX * 2), h: Math.max(1, h) };
  }

  // ---------- Zeichnen ----------
  function render() {
    layout();
    var out = ['<svg xmlns="http://www.w3.org/2000/svg" class="org-svg" preserveAspectRatio="xMidYMid meet"><g class="org-linien">'];
    lines.forEach(function (l) { out.push('<path data-kid="' + l.kid + '"' + (l.trunk ? ' data-trunk="' + l.trunk.join(" ") + '"' : "") + ' d="' + l.d + '"/>'); });
    out.push("</g><g class=\"org-kaesten\">");
    stand.knoten.forEach(function (k) {
      var b = boxes[k.id], p = pos[k.id];
      if (!p) return;
      var g = ['<g class="org-knoten org-art-' + k.art + '" data-id="' + k.id + '" transform="translate(' + p.x + " " + p.y + ')">',
        '<rect class="org-box" width="' + b.w + '" height="' + b.h + '"/>'];
      if (k.art !== "gruppe") g.push('<rect class="org-akzent" width="' + b.w + '" height="3"/>');
      b.rows.forEach(function (r) {
        var tx = PAD + (r.dot ? 14 : 0);
        if (r.dot) g.push('<circle class="org-punkt" cx="' + (PAD + 4) + '" cy="' + (r.y - 4) + '" r="3"/>');
        g.push('<text class="' + r.cls + '" x="' + tx + '" y="' + r.y + '">' + esc(r.t) + "</text>");
      });
      if (b.sep) g.push('<path class="org-trenner" d="M' + PAD + " " + b.sep + "H" + (b.w - PAD) + '"/>');
      if (kids(k.id).length) {
        var c = collapsed[k.id], n = descendants(k.id).length;
        g.push('<g class="org-schalter" data-toggle="' + k.id + '" transform="translate(' + b.w / 2 + " " + b.h + ')" role="button" aria-label="' +
          esc((c ? T.expand : T.collapse) + ": " + L(k, "titel")) + '"><circle class="org-schalter-feld" r="16"/><circle r="10"/>' +
          '<path d="M-5 0H5' + (c ? "M0 -5V5" : "") + '"/></g>');
        if (c) g.push('<text class="org-t-zahl" x="' + (b.w / 2 + 16) + '" y="' + (b.h + 4) + '">' + esc(T.nSub.replace("{n}", n)) + "</text>");
      }
      g.push("</g>");
      out.push(g.join(""));
    });
    out.push("</g></svg>");
    surface.innerHTML = out.join("");
    svg = surface.querySelector("svg");
    applyFocus();
    applyView();
    buildOutline();
  }

  // ---------- Ausschnitt ----------
  function aspect() { return surface.clientHeight / Math.max(1, surface.clientWidth); }
  function clampW(w) { return Math.min(Math.max(w, 260), Math.max(full.w, full.h / aspect(), 600) * 3); }
  function setView(cx, cy, w) {
    w = clampW(w);
    var h = w * aspect();
    view = { x: cx - w / 2, y: cy - h / 2, w: w, h: h };
    if (!raf) raf = requestAnimationFrame(function () { raf = 0; applyView(); });
  }
  function applyView() { if (svg) svg.setAttribute("viewBox", view.x + " " + view.y + " " + view.w + " " + view.h); }
  function bboxOf(ids) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    ids.forEach(function (id) {
      var p = pos[id], b = boxes[id];
      if (!p) return;
      x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + b.w); y1 = Math.max(y1, p.y + b.h);
    });
    return x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function fit(ids, minW) {
    var b = (ids && ids.length && bboxOf(ids)) || full;
    var w = Math.max(b.w, b.h / aspect()) * 1.08 + 40;
    setView(b.x + b.w / 2, b.y + b.h / 2, Math.max(w, minW || 0));
  }
  function zoomAt(clientX, clientY, f) {
    // Punkt unter dem Zeiger bleibt stehen
    var r = surface.getBoundingClientRect();
    var fx = (clientX - r.left) / r.width, fy = (clientY - r.top) / r.height;
    var mx = view.x + fx * view.w, my = view.y + fy * view.h, w = clampW(view.w / f);
    setView(mx - (fx - 0.5) * w, my - (fy - 0.5) * w * aspect(), w);
  }
  function zoomCenter(f) {
    var r = surface.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, f);
  }
  // Nach Auf-/Zuklappen bleibt das betroffene Amt an seiner Stelle auf dem Bildschirm
  function keepPlace(id, change) {
    var before = pos[id] ? { x: pos[id].x, y: pos[id].y } : null;
    change();
    render();
    if (before && pos[id]) setView(view.x + view.w / 2 + pos[id].x - before.x, view.y + view.h / 2 + pos[id].y - before.y, view.w);
  }
  function toggle(id) { keepPlace(id, function () { collapsed[id] = !collapsed[id]; }); }
  function reveal(id) { ancestors(id).forEach(function (a) { collapsed[a] = false; }); }

  // ---------- Hervorhebung ----------
  function setFocus(id) {
    focusSet = id ? [id].concat(descendants(id), ancestors(id)) : null;
    applyFocus();
  }
  function applyFocus() {
    if (!svg) return;
    root.classList.toggle("is-fokus", !!focusSet);
    svg.querySelectorAll(".org-knoten").forEach(function (g) {
      g.classList.toggle("is-fokus", !!focusSet && focusSet.indexOf(g.getAttribute("data-id")) >= 0);
      g.classList.toggle("is-hover", g.getAttribute("data-id") === hoverId);
    });
    svg.querySelectorAll(".org-linien path").forEach(function (p) {
      var kid = p.getAttribute("data-kid"), trunk = p.getAttribute("data-trunk");
      var on = !!focusSet && (trunk ? focusSet.indexOf(kid) >= 0 && trunk.split(" ").some(function (t) { return focusSet.indexOf(t) >= 0; }) : focusSet.indexOf(kid) >= 0);
      p.classList.toggle("is-fokus", on);
    });
  }
  function hover(id) {
    if (id === hoverId) return;
    hoverId = id;
    applyFocus();
    var k = id && node(id);
    if (!k) { info.innerHTML = ""; info.classList.remove("is-sichtbar"); return; }
    var h = holders(k), parts = ["<strong>" + esc(L(k, "titel")) + "</strong>"];
    if (L(k, "leitung")) parts.push(esc(T.lead) + ": " + esc(L(k, "leitung")));
    if (staffed(k)) parts.push(esc(h.length > 1 ? T.holders : T.holder) + ": " + (h.length ? esc(h.map(function (p) { return p.name; }).join(", ")) : esc(T.vacant)));
    var m = members(k);
    if (m !== null) parts.push(esc(T.members) + ": " + fmt(m));
    info.innerHTML = parts.join("<br>");
    info.classList.add("is-sichtbar");
  }

  // ---------- Bedienung ----------
  var pointers = {}, drag = null, pinch = null;
  function hitAt(x, y) {
    var el = document.elementFromPoint(x, y);
    if (!el || !surface.contains(el)) return null;
    var t = el.closest("[data-toggle]");
    if (t) return { toggle: t.getAttribute("data-toggle") };
    var g = el.closest(".org-knoten");
    return g ? { id: g.getAttribute("data-id") } : null;
  }
  function bindView() {
    root.querySelectorAll("[data-zoom]").forEach(function (b) {
      b.addEventListener("click", function () {
        var z = b.getAttribute("data-zoom");
        if (z === "fit") fit(); else zoomCenter(z === "in" ? 1.4 : 1 / 1.4);
      });
    });
    root.querySelectorAll("[data-alle]").forEach(function (b) {
      b.addEventListener("click", function () {
        var zu = b.getAttribute("data-alle") === "zu";
        collapsed = {};
        // „Alle zuklappen“ lässt die oberen beiden Ebenen offen
        if (zu) stand.knoten.forEach(function (k) { if (ancestors(k.id).length >= 1 && kids(k.id).length) collapsed[k.id] = true; });
        render(); fit();
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
        var a = pointers[ids[0]], b = pointers[ids[1]];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
        drag = null;
        return;
      }
      if (e.button !== 0 && e.button !== 1 && e.pointerType === "mouse") return;
      drag = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
      surface.setPointerCapture(e.pointerId);
    });
    surface.addEventListener("pointermove", function (e) {
      if (pointers[e.pointerId]) pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (pinch && ids.length === 2) {
        // zwei Finger: verschieben (Mittelpunkt) und zoomen (Abstand)
        var a = pointers[ids[0]], b = pointers[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y);
        var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, kk = view.w / surface.clientWidth;
        setView(view.x + view.w / 2 - (mx - pinch.mx) * kk, view.y + view.h / 2 - (my - pinch.my) * kk, view.w);
        if (pinch.d > 0) zoomAt(mx, my, d / pinch.d);
        pinch.d = d; pinch.mx = mx; pinch.my = my;
        return;
      }
      if (drag) {
        if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 5) { drag.moved = true; surface.classList.add("is-ziehen"); }
        if (drag.moved) {
          var k = view.w / surface.clientWidth;
          setView(view.x + view.w / 2 - (e.clientX - drag.x) * k, view.y + view.h / 2 - (e.clientY - drag.y) * k, view.w);
        }
        drag.x = e.clientX; drag.y = e.clientY;
        return;
      }
      if (e.pointerType === "mouse") { var h = hitAt(e.clientX, e.clientY); hover(h && h.id ? h.id : null); }
    });
    function up(e) {
      var wasPinch = !!pinch;
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      if (drag && !drag.moved && !wasPinch && e.type === "pointerup" && e.button !== 1) {
        var hit = hitAt(e.clientX, e.clientY);
        if (hit && hit.toggle) toggle(hit.toggle);
        else if (hit && hit.id) { hover(hit.id); open(hit.id); }
      }
      if (drag) { drag = null; surface.classList.remove("is-ziehen"); }
    }
    surface.addEventListener("pointerup", up);
    surface.addEventListener("pointercancel", up);
    surface.addEventListener("pointerleave", function (e) { if (!drag && e.pointerType === "mouse") hover(null); });
    surface.addEventListener("keydown", function (e) {
      var step = view.w * 0.1;
      var keys = { "+": function () { zoomCenter(1.4); }, "=": function () { zoomCenter(1.4); }, "-": function () { zoomCenter(1 / 1.4); },
        "0": function () { fit(); },
        ArrowLeft: function () { setView(view.x + view.w / 2 - step, view.y + view.h / 2, view.w); },
        ArrowRight: function () { setView(view.x + view.w / 2 + step, view.y + view.h / 2, view.w); },
        ArrowUp: function () { setView(view.x + view.w / 2, view.y + view.h / 2 - step, view.w); },
        ArrowDown: function () { setView(view.x + view.w / 2, view.y + view.h / 2 + step, view.w); } };
      if (keys[e.key] && !e.ctrlKey && !e.metaKey) { e.preventDefault(); keys[e.key](); }
    });
    var form = root.querySelector(".karte-suche");
    var input = form.querySelector("input");
    form.addEventListener("submit", function (e) { e.preventDefault(); find(input.value); });
    input.addEventListener("change", function () { if (searchIndex[input.value]) find(input.value); });
    window.addEventListener("resize", function () { setView(view.x + view.w / 2, view.y + view.h / 2, view.w); });
  }

  // ---------- Suche (Ämter und Amtsträger) ----------
  var searchIndex = {};
  function fillSearch() {
    searchIndex = {};
    stand.knoten.forEach(function (k) {
      searchIndex[L(k, "titel")] = k.id;
      if (L(k, "kurz") && !searchIndex[L(k, "kurz")]) searchIndex[L(k, "kurz")] = k.id;
      holders(k).forEach(function (p) { searchIndex[p.name + " – " + L(k, "titel")] = k.id; });
    });
    var opts = Object.keys(searchIndex).sort(function (a, b) { return a.localeCompare(b, "de"); });
    root.querySelector("#org-liste").innerHTML = opts.map(function (o) { return '<option value="' + esc(o) + '">'; }).join("");
  }
  function find(q) {
    q = q.trim();
    var low = q.toLowerCase(), id = searchIndex[q];
    if (!id && q) {
      var keys = Object.keys(searchIndex);
      var hit = keys.find(function (s) { return s.toLowerCase() === low; }) || keys.find(function (s) { return s.toLowerCase().indexOf(low) === 0; }) ||
        keys.find(function (s) { return s.toLowerCase().indexOf(low) >= 0; });
      id = hit && searchIndex[hit];
    }
    if (!id) { info.textContent = T.notFound; info.classList.add("is-sichtbar"); return; }
    reveal(id);
    render();
    fit([id], 760);
    hoverId = null;
    hover(id);
  }

  // ---------- Gliederung (Seitenleiste) ----------
  var pinned = null;
  function buildOutline() {
    var box = document.querySelector("[data-gliederung]");
    if (!box) return;
    function list(id) {
      var ks = kids(id);
      if (!ks.length) return "";
      return "<ul>" + ks.map(function (k) {
        return '<li><button type="button" class="karte-legende-item org-gliederung-item org-art-' + k.art + '" data-id="' + k.id + '" aria-pressed="' +
          String(pinned === k.id) + '"><span class="karte-legende-name">' + esc(L(k, "titel")) + "</span>" +
          (staffed(k) ? '<span class="karte-legende-zahl">' + (holders(k).length ? fmt(holders(k).length) : "–") + "</span>" : "") + "</button>" + list(k.id) + "</li>";
      }).join("") + "</ul>";
    }
    box.innerHTML = list("");
    box.querySelectorAll("[data-id]").forEach(function (b) {
      var id = b.getAttribute("data-id");
      b.addEventListener("pointerenter", function (e) { if (!pinned && e.pointerType === "mouse") setFocus(id); });
      b.addEventListener("pointerleave", function (e) { if (!pinned && e.pointerType === "mouse") setFocus(null); });
      b.addEventListener("click", function () {
        if (EDIT) { openEditor(id); return; }
        pinned = pinned === id ? null : id;
        if (pinned) { reveal(id); collapsed[id] = false; render(); }
        box.querySelectorAll("[data-id]").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-id") === pinned)); });
        setFocus(pinned);
        if (pinned) fit([id].concat(descendants(id)));
      });
    });
  }

  // ---------- Fenster (Anzeige) ----------
  function open(id) { if (EDIT) openEditor(id); else openInfo(id); }
  var infoDlg = document.querySelector("[data-amt]");
  if (infoDlg) {
    infoDlg.querySelector("[data-amt-zu]").addEventListener("click", function () { infoDlg.close(); });
    infoDlg.addEventListener("click", function (e) {
      if (e.target === infoDlg) { infoDlg.close(); return; }  // Klick neben das Fenster
      var j = e.target.closest("[data-springe]");
      if (j) { e.preventDefault(); var to = j.getAttribute("data-springe"); reveal(to); render(); fit([to], 760); showInfo(to); }
    });
  }
  function row(k, v) { return '<tr><th scope="row">' + esc(k) + "</th><td>" + v + "</td></tr>"; }
  function personHtml(p, k) {
    var n = esc(p.name);
    var extra = p.titel.slice();
    if (k.nutzer.indexOf(p.id) >= 0) extra.push(T.byDecree);
    return "<strong>" + n + "</strong>" + (extra.length ? ' <span class="karte-titel">' + esc(extra.join(" · ")) + "</span>" : "");
  }
  function jump(k) { return '<button type="button" class="link-arrow org-sprung" data-springe="' + k.id + '">' + esc(L(k, "titel")) + "</button>"; }
  function openInfo(id) { if (infoDlg) { showInfo(id); if (!infoDlg.open) infoDlg.showModal(); } }
  function showInfo(id) {
    var k = node(id), rows = [];
    var html = (L(k, "kurz") ? '<span class="eyebrow">' + esc(L(k, "kurz")) + "</span>" : "") + '<h2 id="org-amt-titel">' + esc(L(k, "titel")) + "</h2>";
    if (L(k, "leitung")) rows.push(row(T.lead, esc(L(k, "leitung"))));
    if (staffed(k)) {
      var h = holders(k);
      rows.push(row(h.length > 1 ? T.holders : T.holder, h.length ? h.map(function (p) { return personHtml(p, k); }).join("<br>") : esc(T.vacant)));
    }
    var m = members(k);
    if (m !== null) rows.push(row(T.members, fmt(m)));
    var up = k.eltern && node(k.eltern);
    if (up) rows.push(row(T.superior, jump(up)));
    var ks = kids(id);
    if (ks.length) rows.push(row(T.sub, ks.map(jump).join("<br>")));
    if (rows.length) html += '<table class="styles-table is-grid karte-gebiet-tabelle"><tbody>' + rows.join("") + "</tbody></table>";
    var text = L(k, "text");
    if (text) html += '<h3 class="karte-gebiet-h">' + esc(T.tasks) + '</h3><div class="prose org-text">' +
      text.split(/\n\s*\n/).map(function (p) { return "<p>" + esc(p.trim()) + "</p>"; }).join("") + "</div>";
    if (k.rollen.length) {
      var names = k.rollen.map(function (r) { return "„" + (roleName(r) || r) + "“"; }).join(" " + T.or + " ");
      if (EN) names = names.replace(/„/g, "“").replace(/“(?=\s|$)/g, "”");
      var note = T.rolesNote.replace("{r}", names + (k.zusatz ? " " + T.rolesAnd.replace("{z}", roleName(k.zusatz) || k.zusatz) : ""));
      html += '<p class="karte-feldhinweis">' + esc(note) + "</p>";
    }
    infoDlg.querySelector("[data-amt-inhalt]").innerHTML = html;
    var link = linkOf(k);
    infoDlg.querySelector("[data-amt-link]").innerHTML = link ? '<a class="btn btn-navy" href="' + esc(link) + '">' + esc(T.toPage) + "</a>" : "";
    infoDlg.querySelector("[data-amt-inhalt]").focus();
  }
  // Rollennamen: Editor bekommt sie in cfg.rollen, die Anzeige aus den Rollen der Amtsträger nicht; dort reicht die Liste in info.json
  var roleNames = cfg.rollen || {};
  function roleName(id) { return roleNames[id] || ""; }

  // ---------- Bild herunterladen ----------
  var PNG = { paper: "#fbf9f4", ivory: "#f5f1e8", white: "#ffffff", ink: "#161a2e", ink2: "#3a3e52", muted: "#646778", rule: "#ddd5c3",
    ruleStrong: "#bfb294", gold: "#c9a43a", gold6: "#9a7618", gold3: "#e4cb7a", navy: "#12183c" };
  function download() {
    var M = 64, HEAD = 110, S = 2;
    var cw = full.w + 2 * M, ch = full.h + HEAD + M + 40;
    var c = document.createElement("canvas");
    c.width = Math.round(cw * S); c.height = Math.round(ch * S);
    var g = c.getContext("2d");
    g.scale(S, S);
    g.fillStyle = PNG.paper; g.fillRect(0, 0, cw, ch);
    g.fillStyle = PNG.gold; g.fillRect(0, 0, cw, 6);
    g.fillStyle = PNG.ink; g.font = "600 34px " + SERIF; g.textBaseline = "alphabetic";
    g.fillText(T.png, M, 64);
    g.fillStyle = PNG.muted; g.font = "400 14px " + SANS;
    g.fillText("Imperium Germanicum · " + T.asOf + " " + (cfg.stand_datum || ""), M, 90);
    g.translate(M - full.x, HEAD - full.y);
    g.strokeStyle = PNG.ruleStrong; g.lineWidth = 1.5;
    lines.forEach(function (l) { g.stroke(new Path2D(l.d)); });
    stand.knoten.forEach(function (k) {
      var b = boxes[k.id], p = pos[k.id];
      if (!p) return;
      var crown = k.art === "krone";
      g.fillStyle = crown ? PNG.navy : k.art === "saeule" || k.art === "gruppe" ? PNG.ivory : PNG.white;
      g.fillRect(p.x, p.y, b.w, b.h);
      g.strokeStyle = crown || k.art === "kanzlei" ? PNG.gold : PNG.rule; g.lineWidth = k.art === "kanzlei" ? 2 : 1;
      if (k.art === "gruppe") g.setLineDash([4, 3]);
      g.strokeRect(p.x + 0.5, p.y + 0.5, b.w - 1, b.h - 1);
      g.setLineDash([]);
      if (k.art !== "gruppe") { g.fillStyle = crown || k.art === "kanzlei" ? PNG.gold : k.art === "saeule" ? PNG.navy : PNG.gold; g.fillRect(p.x, p.y, b.w, 3); }
      if (b.sep) { g.strokeStyle = crown ? "rgba(255,255,255,.25)" : PNG.rule; g.lineWidth = 1; g.beginPath(); g.moveTo(p.x + PAD, p.y + b.sep); g.lineTo(p.x + b.w - PAD, p.y + b.sep); g.stroke(); }
      b.rows.forEach(function (r) {
        var col = { "org-t-kurz": crown ? PNG.gold3 : PNG.gold6, "org-t-titel": crown ? "#ffffff" : PNG.ink, "org-t-leitung": crown ? "#d9dbe6" : PNG.muted,
          "org-t-person": crown ? "#ffffff" : PNG.ink2, "org-t-leer": crown ? "#d9dbe6" : PNG.muted }[r.cls];
        g.font = r.f.font; g.fillStyle = col;
        if ("letterSpacing" in g) g.letterSpacing = (r.f.sp || 0) + "px";
        var tx = p.x + PAD + (r.dot ? 14 : 0);
        if (r.dot) { g.fillStyle = PNG.gold; g.beginPath(); g.arc(p.x + PAD + 4, p.y + r.y - 4, 3, 0, Math.PI * 2); g.fill(); g.fillStyle = col; }
        g.fillText(r.t, tx, p.y + r.y);
        if ("letterSpacing" in g) g.letterSpacing = "0px";
      });
    });
    g.setTransform(S, 0, 0, S, 0, 0);
    g.fillStyle = PNG.muted; g.font = "400 12px " + SANS;
    g.fillText("imperiumgermanicum.de", M, ch - 24);
    c.toBlob(function (blob) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = EN ? "organisation-chart.png" : "organigramm.png";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
    }, "image/png");
  }
  var dl = document.querySelector("[data-bild]");
  if (dl) dl.addEventListener("click", download);

  // ---------- Editor ----------
  var undo = [], redo = [], basis = cfg.basis, dlg, editing = null, isNew = false, chips = [];
  function snapshot() { return JSON.stringify(stand); }
  function remember(before) { undo.push(before); if (undo.length > 200) undo.shift(); redo = []; updateStatus(); }
  function dirty() {
    var a = {}, n = 0;
    saved.knoten.forEach(function (k) { a[k.id] = JSON.stringify(k); });
    stand.knoten.forEach(function (k) { if (a[k.id] !== JSON.stringify(k)) n++; delete a[k.id]; });
    n += Object.keys(a).length;
    if (!n && saved.knoten.map(function (k) { return k.id; }).join() !== stand.knoten.map(function (k) { return k.id; }).join()) n = 1;
    return n;
  }
  function updateStatus() {
    var d = dirty(), txt = d ? T.changes.replace("{n}", d) : T.noChanges;
    document.querySelectorAll("[data-stand]").forEach(function (el) { el.textContent = txt; });
    root.querySelector('[data-aktion="speichern"]').disabled = !d;
    root.querySelector('[data-aktion="undo"]').disabled = !undo.length;
    root.querySelector('[data-aktion="redo"]').disabled = !redo.length;
  }
  function step(dir) {
    var from = dir < 0 ? undo : redo, to = dir < 0 ? redo : undo;
    if (!from.length) return;
    to.push(snapshot());
    stand = JSON.parse(from.pop());
    render(); fillSearch(); updateStatus();
  }
  function newId() {
    var m = 0;
    stand.knoten.forEach(function (k) { m = Math.max(m, parseInt(k.id.slice(1), 10) || 0); });
    return "n" + (m + 1);
  }
  function blank(parent) {
    return { id: newId(), eltern: parent || "", art: "amt", titel: "", titel_en: "", kurz: "", kurz_en: "", leitung: "", leitung_en: "",
      text: "", text_en: "", rollen: [], zusatz: "", nutzer: [], angehoerige: "", link: "" };
  }
  var FIELDS = ["titel", "titel_en", "kurz", "kurz_en", "leitung", "leitung_en", "text", "text_en", "link"];
  function fld(name) { return dlg.querySelector("#of-" + name); }
  function drawChips() {
    dlg.querySelector("[data-chips]").innerHTML = chips.map(function (r) {
      return '<li><span>' + esc(roleName(r) || r) + '</span><button type="button" class="btn btn-line btn-small" data-weg="' + r + '" aria-label="' +
        esc(T.remove + ": " + (roleName(r) || r)) + '">×</button></li>';
    }).join("");
  }
  function openEditor(id, parent) {
    if (!dlg) return;
    isNew = !id;
    editing = id ? clone(node(id)) : blank(parent);
    dlg.querySelector("[data-dialog-titel]").textContent = isNew ? T.newOffice : T.editOffice;
    FIELDS.forEach(function (f) { fld(f).value = editing[f] || ""; });
    fld("art").value = editing.art;
    fld("zusatz").value = editing.zusatz;
    fld("angehoerige").value = editing.angehoerige;
    fld("nutzer").value = editing.nutzer.join(", ");
    chips = editing.rollen.slice();
    drawChips();
    // Übergeordnet: alle Ämter außer diesem und seinen untergeordneten, eingerückt nach Ebene
    var bad = isNew ? [] : [editing.id].concat(descendants(editing.id)), opts = ['<option value="">' + esc(T.top) + "</option>"];
    (function walk(pid, depth) {
      kids(pid).forEach(function (k) {
        if (bad.indexOf(k.id) >= 0) return;
        opts.push('<option value="' + k.id + '">' + new Array(depth + 1).join(" ") + esc(k.titel) + "</option>");
        walk(k.id, depth + 1);
      });
    })("", 0);
    fld("eltern").innerHTML = opts.join("");
    fld("eltern").value = editing.eltern;
    dlg.querySelectorAll('[data-aktion="links"], [data-aktion="rechts"], [data-aktion="kind"], [data-aktion="loeschen"]').forEach(function (b) { b.hidden = isNew; });
    showError("");
    if (!dlg.open) dlg.showModal();
    fld("titel").focus();
  }
  function showError(t) { var e = dlg.querySelector("[data-dialog-fehler]"); e.textContent = t; e.hidden = !t; }
  function readForm() {
    var k = clone(editing);
    FIELDS.forEach(function (f) { k[f] = fld(f).value.trim(); });
    k.art = fld("art").value; k.eltern = fld("eltern").value; k.zusatz = fld("zusatz").value; k.angehoerige = fld("angehoerige").value;
    k.rollen = chips.slice();
    var ids = fld("nutzer").value.split(/[\s,;]+/).filter(Boolean);
    if (ids.some(function (x) { return !/^[0-9]{5,22}$/.test(x); })) { showError(T.idsBad); return null; }
    k.nutzer = ids;
    if (!k.titel) { showError(T.nameEmpty); return null; }
    if (k.link && !/^\/[^\/\\\s]/.test(k.link)) { showError(T.linkBad); return null; }
    return k;
  }
  // Formular übernehmen; gibt das Amt zurück oder null bei Fehlern
  function apply() {
    var k = readForm();
    if (!k) return null;
    var before = snapshot(), old = node(k.id);
    if (old && JSON.stringify(old) === JSON.stringify(k)) return k;
    if (old) {
      var parentChanged = old.eltern !== k.eltern;
      stand.knoten[stand.knoten.indexOf(old)] = k;
      if (parentChanged) {  // ans Ende der neuen Gleichrangigen
        stand.knoten.splice(stand.knoten.indexOf(k), 1);
        stand.knoten.push(k);
      }
    } else stand.knoten.push(k);
    if (k.eltern) { collapsed[k.eltern] = false; reveal(k.eltern); }
    remember(before);
    editing = clone(k); isNew = false;
    render(); fillSearch();
    return k;
  }
  function move(dir) {
    var k = apply();
    if (!k) return;
    var sib = kids(k.eltern), i = sib.findIndex(function (s) { return s.id === k.id; }), j = i + dir;
    if (j < 0 || j >= sib.length) return;
    var before = snapshot(), a = stand.knoten.indexOf(node(k.id)), b = stand.knoten.indexOf(sib[j]);
    var tmp = stand.knoten[a]; stand.knoten[a] = stand.knoten[b]; stand.knoten[b] = tmp;
    remember(before);
    render();
  }
  function remove() {
    var k = node(editing.id), d = descendants(k.id);
    if (!window.confirm((d.length ? T.confirmDelete : T.confirmDelete1).replace("{name}", k.titel).replace("{n}", d.length))) return;
    var before = snapshot(), gone = [k.id].concat(d);
    stand.knoten = stand.knoten.filter(function (x) { return gone.indexOf(x.id) < 0; });
    remember(before);
    dlg.close("cancel");
    render(); fillSearch();
  }
  function initEditor() {
    dlg = document.querySelector("[data-dialog]");
    var form = dlg.querySelector("form");
    form.addEventListener("submit", function (e) {
      if (e.submitter && e.submitter.value === "cancel") return;
      e.preventDefault();
      if (apply()) dlg.close("ok");
    });
    fld("rolle").addEventListener("change", function () {
      var v = fld("rolle").value;
      if (v && chips.indexOf(v) < 0) { chips.push(v); drawChips(); }
      fld("rolle").value = "";
    });
    dlg.querySelector("[data-chips]").addEventListener("click", function (e) {
      var b = e.target.closest("[data-weg]");
      if (b) { chips = chips.filter(function (r) { return r !== b.getAttribute("data-weg"); }); drawChips(); }
    });
    dlg.querySelector('[data-aktion="links"]').addEventListener("click", function () { move(-1); });
    dlg.querySelector('[data-aktion="rechts"]').addEventListener("click", function () { move(1); });
    dlg.querySelector('[data-aktion="kind"]').addEventListener("click", function () { var k = apply(); if (k) openEditor(null, k.id); });
    dlg.querySelector('[data-aktion="loeschen"]').addEventListener("click", remove);
    root.querySelector('[data-aktion="neu"]').addEventListener("click", function () { openEditor(null, roots().length === 1 ? roots()[0].id : ""); });
    root.querySelector('[data-aktion="undo"]').addEventListener("click", function () { step(-1); });
    root.querySelector('[data-aktion="redo"]').addEventListener("click", function () { step(1); });
    document.addEventListener("keydown", function (e) {
      if (!(e.ctrlKey || e.metaKey) || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || document.querySelector("dialog[open]")) return;
      var key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); step(-1); }
      else if (key === "y" || key === "z" && e.shiftKey) { e.preventDefault(); step(1); }
    });
    window.addEventListener("beforeunload", function (e) { if (dirty()) { e.preventDefault(); e.returnValue = T.leave; } });
    // Speichern mit Bemerkung
    var sdlg = document.querySelector("[data-speichern]"), note = sdlg.querySelector("#org-bemerkung"), msg = sdlg.querySelector("[data-meldung]");
    function say(text, kind) {
      var h = text ? '<div class="form-status ' + kind + '" role="status">' + esc(text) + "</div>" : "";
      msg.innerHTML = h;
      var side = document.querySelector("[data-meldung-seite]");
      if (side) side.innerHTML = kind === "ok" ? h : "";
    }
    root.querySelector('[data-aktion="speichern"]').addEventListener("click", function () { say("", ""); sdlg.showModal(); note.focus(); });
    sdlg.querySelector("form").addEventListener("submit", function (e) {
      if (e.submitter && e.submitter.value === "cancel") return;
      e.preventDefault();
      var btn = sdlg.querySelector('button[value="ok"]');
      btn.disabled = true;
      fetch(cfg.speichern, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf: cfg.csrf, basis: basis, stand: stand, bemerkung: note.value }) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          btn.disabled = false;
          if (j.ok) {
            basis = j.version; saved = clone(stand); note.value = ""; undo = []; redo = [];
            say(T.saved, "ok"); sdlg.close("ok");
          } else if (j.konflikt) say(T.conflict.replace("{name}", j.name), "err");
          else say(j.fehler || T.saveError, "err");
          updateStatus();
        })
        .catch(function () { btn.disabled = false; say(T.saveError, "err"); });
    });
    updateStatus();
  }

  // ---------- Start ----------
  function load() {
    return fetch(cfg.info + (cfg.version ? "?version=" + cfg.version : EDIT ? "?alle=1" : ""), { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw r; return r.json(); })
      .then(function (j) { personen = j.personen || []; (j.rollen || []).forEach(function (r) { if (!roleNames[r.id]) roleNames[r.id] = r.name; }); })
      .catch(function () { info.textContent = T.infoError; info.classList.add("is-sichtbar"); });
  }
  var fonts = document.fonts && document.fonts.load ? Promise.all([document.fonts.load(F.titel.font), document.fonts.load(F.person.font),
    document.fonts.load(F.leitung.font), document.fonts.load(F.leer.font)]).catch(function () {}) : Promise.resolve();
  Promise.all([load(), fonts]).then(function () {
    render();
    // Auf schmalen Bildschirmen zuerst die oberen drei Ebenen lesbar zeigen; „Ganzes Organigramm“ zeigt alles
    var top = roots()[0];
    if (surface.clientWidth < 600 && top) {
      // schmaler Bildschirm: oben an der Spitze beginnen, Kästen in lesbarer Größe
      var w = BW + 2 * GX;
      setView(pos[top.id].x + BW / 2, pos[top.id].y - GX + w * aspect() / 2, w);
    } else fit();
    fillSearch();
    bindView();
    if (EDIT) initEditor();
  }).catch(function () {
    var l = surface.querySelector(".karte-laden");
    if (l) l.textContent = T.loadError;
  });
})();
