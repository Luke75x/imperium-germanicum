/* Allgemeines Organigramm des Reiches (/informationen/organigramm/): Anzeige und Editor.
   Konfiguration aus #og-cfg (vom Wiki-Dienst, Modul staatsaufbau.py), Amtsträger und Mitgliederzahlen aus info.json (Discord-Rollen, live).
   Organe stehen an festen Positionen (knoten.x/y), Rahmen (Senatskanzlei, Streitkräfte …) werden um ihre Organe gezeichnet,
   Beziehungen (kanten) als Pfeile in der Farbe ihrer Art; mehrere Pfeile zwischen denselben Organen liegen nebeneinander.
   Anzeige wie die Reichskarte: Zoomen (Mausrad, Knöpfe, Tasten, zwei Finger), Verschieben, Organ bzw. Beziehung unter dem Zeiger,
   Suche nach Organen und Amtsträgern, Legende hebt eine Beziehungsart hervor, Klick auf ein Organ öffnet ein Fenster (Amtsträger,
   Mitglieder, Beschreibung, alle Beziehungen), Herunterladen als Bild (PNG, helle Farben, mit Legende).
   Editor (nur Server-Admins): Organe ziehen, Klick öffnet den Dialog (Texte DE/EN, Darstellung, Rahmen, Beziehungen, Rollen,
   Dekret-IDs, Mitgliederrolle, Verweis), Neues Organ, Löschen, Rückgängig/Wiederholen, Speichern mit Bemerkung und Konflikterkennung.
   Farben der Beziehungsarten stehen als Tokens in wiki.css (.og-cols), das Bild nutzt die hellen Werte aus PNG unten. */
(function () {
  "use strict";
  var root = document.querySelector("[data-og]");
  var cfgEl = document.getElementById("og-cfg");
  if (!root || !cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent);
  var T = cfg.i18n;
  var EN = cfg.lang === "en";
  var EDIT = cfg.modus === "bearbeiten";
  var surface = root.querySelector(".karte-flaeche");
  var info = root.querySelector(".karte-info");
  var stand = clone(cfg.stand);
  var saved = clone(cfg.stand);
  var personen = [], zahlen = {};
  var boxes = {}, frames = [], edges = [], full = { x: 0, y: 0, w: 1, h: 1 }, view = { x: 0, y: 0, w: 1, h: 1 };
  var svg = null, raf = 0, focus = null, hoverId = null, roleNames = cfg.rollen || {};

  var PAD = 14, FRAME = 26, FRAME_LABEL = 34;

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fmt(n) { return n.toLocaleString(EN ? "en-GB" : "de-DE"); }
  function node(id) { for (var i = 0; i < stand.knoten.length; i++) if (stand.knoten[i].id === id) return stand.knoten[i]; return null; }
  function frameOf(id) { for (var i = 0; i < stand.rahmen.length; i++) if (stand.rahmen[i].id === id) return stand.rahmen[i]; return null; }
  function L(k, f) { return (EN && k[f + "_en"]) || k[f] || ""; }
  function holders(k) {
    return personen.filter(function (p) {
      if (k.nutzer.indexOf(p.id) >= 0) return true;
      return k.rollen.some(function (r) { return p.rollen.indexOf(r) >= 0; }) && (!k.zusatz || p.rollen.indexOf(k.zusatz) >= 0);
    });
  }
  function staffed(k) { return k.rollen.length || k.nutzer.length; }
  function members(k) { return k.angehoerige && zahlen[k.angehoerige] != null ? zahlen[k.angehoerige] : null; }
  function linkOf(k) { return !k.link ? "" : k.link.indexOf("/en/") !== 0 ? cfg.prefix + k.link : k.link; }
  function roleName(id) { return roleNames[id] || ""; }

  // ---------- Text messen und umbrechen ----------
  var meas = document.createElement("canvas").getContext("2d");
  var css = getComputedStyle(document.documentElement);
  var SERIF = css.getPropertyValue("--serif").trim() || "Georgia, serif";
  var SANS = css.getPropertyValue("--sans").trim() || "sans-serif";
  var F = {
    kurz: { font: "600 10.5px " + SANS, lh: 16, sp: 1.5 },
    titel: { font: "600 17px " + SERIF, lh: 20 },
    krone: { font: "600 21px " + SERIF, lh: 24 },
    person: { font: "400 12.5px " + SANS, lh: 17 },
    leer: { font: "italic 400 12.5px " + SANS, lh: 18 },
    rahmen: { font: "600 17px " + SERIF, lh: 20 }
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
  // Ein Organ: Wappen, Siegel oder Krone (ohne Bild: Initialen im Kreis), darunter Name und Amtsträger, alles mittig
  var NW = 200;
  function imgSize(k) { return k.form === "krone" ? 124 : k.form === "volk" ? 88 : 96; }
  function initials(t) {
    return t.split(/\s+/).filter(function (w) { return !/^(der|die|das|des|the)$/i.test(w); }).slice(0, 2).map(function (w) { return w.charAt(0).toUpperCase(); }).join("");
  }
  function measure(k) {
    var img = imgSize(k), rows = [], y = img + 12, inner = NW - 8;
    function add(lines, f, cls) { lines.forEach(function (t) { rows.push({ t: t, f: f, cls: cls, y: y + f.lh * 0.78 }); y += f.lh; }); }
    add(wrap(L(k, "titel"), k.form === "krone" ? F.krone : F.titel, inner, 2), k.form === "krone" ? F.krone : F.titel, "org-t-titel");
    if (staffed(k)) {
      var h = holders(k);
      y += 2;
      if (!h.length) add([T.vacant], F.leer, "org-t-leer");
      else if (h.length > 2) add([T.nHolders.replace("{n}", h.length)], F.person, "org-t-person");
      else h.forEach(function (p) { add(wrap(p.name, F.person, inner, 1), F.person, "org-t-person"); });
    }
    var cw = img;
    rows.forEach(function (r) { cw = Math.max(cw, width(r.t, r.f)); });
    return { w: NW, h: Math.round(y + 4), img: img, rows: rows, cw: Math.min(NW, cw + 12) };
  }

  // ---------- Geometrie ----------
  function layout() {
    boxes = {};
    stand.knoten.forEach(function (k) { var b = measure(k); b.x = k.x; b.y = k.y; boxes[k.id] = b; });
    frames = stand.rahmen.map(function (r) {
      var ids = stand.knoten.filter(function (k) { return k.rahmen === r.id; }).map(function (k) { return k.id; });
      var bb = bboxOf(ids);
      if (!bb) return null;
      return { r: r, x: bb.x - FRAME, y: bb.y - FRAME, w: bb.w + 2 * FRAME, h: bb.h + FRAME + FRAME_LABEL };
    }).filter(Boolean);
    // Beziehungen: gerade Pfeile von Rand zu Rand; mehrere zwischen denselben Organen nebeneinander
    var pairs = {};
    stand.kanten.forEach(function (e) {
      var key = [e.von, e.nach].sort().join("|");
      (pairs[key] = pairs[key] || []).push(e);
    });
    edges = [];
    Object.keys(pairs).forEach(function (key) {
      var list = pairs[key], n = list.length;
      list.forEach(function (e, i) {
        var a = core(boxes[e.von]), b = core(boxes[e.nach]);
        if (!a || !b) return;
        var ax = a.x + a.w / 2, ay = a.y + a.h / 2, bx = b.x + b.w / 2, by = b.y + b.h / 2;
        var dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy) || 1;
        // Versatz immer bezogen auf die sortierte Richtung, damit Hin- und Rückpfeil nicht aufeinanderliegen
        // mehrere Pfeile zwischen denselben Organen: leicht gebogen und gefächert, damit jeder einzeln erkennbar bleibt
        var s = key.indexOf(e.von) === 0 ? 1 : -1, off = (i - (n - 1) / 2) * 12;
        var ox = -dy / len * off * s, oy = dx / len * off * s;
        var p1 = border(a, ax + ox, ay + oy, dx, dy), p2 = border(b, bx + ox, by + oy, -dx, -dy);
        var g = { e: e, x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
        if (n > 1 && off) {
          g.cx = (p1.x + p2.x) / 2 + ox * 1.6; g.cy = (p1.y + p2.y) / 2 + oy * 1.6;
          g.d = "M" + r1(p1.x) + " " + r1(p1.y) + "Q" + r1(g.cx) + " " + r1(g.cy) + " " + r1(p2.x) + " " + r1(p2.y);
        } else g.d = "M" + r1(p1.x) + " " + r1(p1.y) + "L" + r1(p2.x) + " " + r1(p2.y);
        edges.push(g);
      });
    });
    var all = bboxOf(stand.knoten.map(function (k) { return k.id; })) || { x: 0, y: 0, w: 1, h: 1 };
    frames.forEach(function (f) {
      var x1 = Math.max(all.x + all.w, f.x + f.w), y1 = Math.max(all.y + all.h, f.y + f.h);
      all.x = Math.min(all.x, f.x); all.y = Math.min(all.y, f.y); all.w = x1 - all.x; all.h = y1 - all.y;
    });
    full = all;
  }
  // sichtbarer Kern eines Organs (Siegel und Name), an dessen Rand die Pfeile enden
  function core(b) { return b ? { x: b.x + (b.w - b.cw) / 2, y: b.y - 4, w: b.cw, h: b.h + 4 } : null; }
  function r1(v) { return Math.round(v * 10) / 10; }
  function border(b, cx, cy, dx, dy) {
    // Schnittpunkt des Strahls vom (versetzten) Mittelpunkt in Richtung (dx, dy) mit dem Kasten, etwas Abstand
    var hw = b.w / 2 + 3, hh = b.h / 2 + 3;
    var mx = b.x + b.w / 2, my = b.y + b.h / 2, ox = cx - mx, oy = cy - my;
    var tx = dx > 0 ? (hw - ox) / dx : dx < 0 ? (-hw - ox) / dx : Infinity;
    var ty = dy > 0 ? (hh - oy) / dy : dy < 0 ? (-hh - oy) / dy : Infinity;
    var t = Math.min(tx, ty);
    return { x: cx + dx * t, y: cy + dy * t };
  }
  function bboxOf(ids) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    ids.forEach(function (id) {
      var b = boxes[id];
      if (!b) return;
      x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h);
    });
    return x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  // ---------- Zeichnen ----------
  function render() {
    layout();
    var out = ['<svg xmlns="http://www.w3.org/2000/svg" class="org-svg og-svg" preserveAspectRatio="xMidYMid meet"><defs>'];
    cfg.arten.forEach(function (a) {
      out.push('<marker id="og-m-' + a + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path class="og-f-' + a + '" d="M0 0L10 5L0 10Z"/></marker>');
    });
    out.push('</defs><g class="og-rahmen">');
    frames.forEach(function (f) {
      out.push('<g data-rahmen="' + f.r.id + '"><rect x="' + f.x + '" y="' + f.y + '" width="' + f.w + '" height="' + f.h + '"/><text x="' + (f.x + f.w / 2) +
        '" y="' + (f.y + f.h - 13) + '" text-anchor="middle">' + esc(L(f.r, "titel")) + "</text></g>");
    });
    out.push('</g><g class="og-kanten">');
    edges.forEach(function (g) {
      var a = g.e.art;
      out.push('<g data-e="' + g.e.id + '"><path class="og-k-' + a + '" d="' + g.d + '"' + (a === "gliederung" ? "" : ' marker-end="url(#og-m-' + a + ')"') +
        '/><path class="og-treffer" d="' + g.d + '"/></g>');
    });
    out.push('</g><g class="org-kaesten">');
    stand.knoten.forEach(function (k) {
      var b = boxes[k.id], ix = (b.w - b.img) / 2;
      var g = ['<g class="org-knoten og-knoten og-form-' + k.form + '" data-id="' + k.id + '" transform="translate(' + b.x + " " + b.y + ')">',
        '<rect class="og-feld" x="-8" y="-8" width="' + (b.w + 16) + '" height="' + (b.h + 12) + '" rx="4"/>'];
      if (k.bild) g.push('<image href="' + cfg.bilder + k.bild + '.webp" x="' + ix + '" y="0" width="' + b.img + '" height="' + b.img + '" preserveAspectRatio="xMidYMid meet"/>');
      else g.push('<circle class="og-initial-kreis" cx="' + b.w / 2 + '" cy="' + b.img / 2 + '" r="' + (b.img / 2 - 2) + '"/><text class="og-initial" x="' + b.w / 2 +
        '" y="' + (b.img / 2 + 10) + '" text-anchor="middle">' + esc(initials(L(k, "titel"))) + "</text>");
      b.rows.forEach(function (r) { g.push('<text class="' + r.cls + '" x="' + b.w / 2 + '" y="' + r.y + '" text-anchor="middle">' + esc(r.t) + "</text>"); });
      g.push("</g>");
      out.push(g.join(""));
    });
    out.push("</g></svg>");
    surface.innerHTML = out.join("");
    svg = surface.querySelector("svg");
    applyFocus();
    applyView();
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
  function fit(ids, minW) {
    var b = (ids && ids.length && bboxOf(ids)) || full;
    setView(b.x + b.w / 2, b.y + b.h / 2, Math.max(Math.max(b.w, b.h / aspect()) * 1.06 + 40, minW || 0));
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
  function toChart(clientX, clientY) {
    var r = surface.getBoundingClientRect();
    return { x: view.x + (clientX - r.left) / r.width * view.w, y: view.y + (clientY - r.top) / r.height * view.h };
  }

  // ---------- Hervorhebung ----------
  // focus = { nodes: [ids], edges: [ids] } oder null
  function focusNode(id) {
    if (!id) return null;
    var es = stand.kanten.filter(function (e) { return e.von === id || e.nach === id; });
    var ns = [id];
    es.forEach(function (e) { ns.push(e.von, e.nach); });
    return { nodes: ns, edges: es.map(function (e) { return e.id; }) };
  }
  function focusArt(art) {
    if (!art) return null;
    var es = stand.kanten.filter(function (e) { return e.art === art; }), ns = [];
    es.forEach(function (e) { ns.push(e.von, e.nach); });
    return { nodes: ns, edges: es.map(function (e) { return e.id; }) };
  }
  var pinnedFocus = null;
  function setFocus(f) { focus = f; applyFocus(); }
  function applyFocus() {
    if (!svg) return;
    var f = focus || pinnedFocus;
    root.classList.toggle("is-fokus", !!f);
    svg.querySelectorAll(".org-knoten").forEach(function (g) {
      var id = g.getAttribute("data-id");
      g.classList.toggle("is-fokus", !!f && f.nodes.indexOf(id) >= 0);
      g.classList.toggle("is-hover", id === hoverId);
    });
    svg.querySelectorAll("[data-e]").forEach(function (g) { g.classList.toggle("is-fokus", !!f && f.edges.indexOf(g.getAttribute("data-e")) >= 0); });
  }
  function showInfo(html) {
    info.innerHTML = html || "";
    info.classList.toggle("is-sichtbar", !!html);
  }
  function hoverNode(id) {
    if (id === hoverId && id) return;
    hoverId = id;
    setFocus(focusNode(id));
    var k = id && node(id);
    if (!k) { showInfo(""); return; }
    var parts = ["<strong>" + esc(L(k, "titel")) + "</strong>"];
    if (staffed(k)) {
      var h = holders(k);
      parts.push(esc(h.length > 1 ? T.holders : T.holder) + ": " + (h.length ? esc(h.map(function (p) { return p.name; }).join(", ")) : esc(T.vacant)));
    }
    var m = members(k);
    if (m !== null) parts.push(esc(T.members) + ": " + fmt(m));
    var n = stand.kanten.filter(function (e) { return e.von === id || e.nach === id; }).length;
    if (n) parts.push(esc(T.relations) + ": " + n);
    showInfo(parts.join("<br>"));
  }
  function hoverEdge(eid) {
    hoverId = null;
    var e = stand.kanten.find(function (x) { return x.id === eid; });
    if (!e) return;
    setFocus({ nodes: [e.von, e.nach], edges: [e.id] });
    showInfo(swatch(e.art) + " <strong>" + esc(L(node(e.von), "titel")) + "</strong> " + esc(T.arten[e.art].aktiv) + " <strong>" + esc(L(node(e.nach), "titel")) + "</strong>");
  }
  function swatch(a) {
    return '<svg class="og-strich" viewBox="0 0 28 12" width="22" height="10" aria-hidden="true"><path class="og-k-' + a + '" d="M1 6H21"/>' +
      (a === "gliederung" ? "" : '<path class="og-spitze og-f-' + a + '" d="M19 1L27 6L19 11Z"/>') + "</svg>";
  }

  // ---------- Bedienung ----------
  var pointers = {}, drag = null, pinch = null, moveNode = null;
  function hitAt(x, y) {
    var el = document.elementFromPoint(x, y);
    if (!el || !surface.contains(el)) return null;
    var g = el.closest(".org-knoten");
    if (g) return { id: g.getAttribute("data-id") };
    var e = el.closest("[data-e]");
    return e ? { edge: e.getAttribute("data-e") } : null;
  }
  function bindView() {
    root.querySelectorAll("[data-zoom]").forEach(function (b) {
      b.addEventListener("click", function () {
        var z = b.getAttribute("data-zoom");
        if (z === "fit") fit(); else zoomCenter(z === "in" ? 1.4 : 1 / 1.4);
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
        if (moveNode && moveNode.moved) { stand = JSON.parse(moveNode.before); render(); }
        drag = null; moveNode = null;
        return;
      }
      if (e.button !== 0 && e.button !== 1 && e.pointerType === "mouse") return;
      var hit = EDIT && e.button === 0 ? hitAt(e.clientX, e.clientY) : null;
      if (hit && hit.id) {
        var k = node(hit.id), p = toChart(e.clientX, e.clientY);
        moveNode = { id: hit.id, dx: p.x - k.x, dy: p.y - k.y, sx: e.clientX, sy: e.clientY, moved: false, before: snapshot() };
      }
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
        if (drag.moved && moveNode) {
          // Editor: Organ verschieben (Raster 10)
          var p = toChart(e.clientX, e.clientY), k = node(moveNode.id);
          var nx = Math.round((p.x - moveNode.dx) / 10) * 10, ny = Math.round((p.y - moveNode.dy) / 10) * 10;
          if (nx !== k.x || ny !== k.y) { k.x = nx; k.y = ny; moveNode.moved = true; scheduleRender(); }
        } else if (drag.moved) {
          var kx = view.w / surface.clientWidth;
          setView(view.x + view.w / 2 - (e.clientX - drag.x) * kx, view.y + view.h / 2 - (e.clientY - drag.y) * kx, view.w);
        }
        drag.x = e.clientX; drag.y = e.clientY;
        return;
      }
      if (e.pointerType === "mouse") {
        var h = hitAt(e.clientX, e.clientY);
        if (h && h.id) hoverNode(h.id);
        else if (h && h.edge) hoverEdge(h.edge);
        else if (hoverId || focus) { hoverId = null; setFocus(null); showInfo(""); }
      }
    });
    function up(e) {
      var wasPinch = !!pinch;
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      if (moveNode && moveNode.moved) { remember(moveNode.before); fillSearch(); }
      else if (drag && !drag.moved && !wasPinch && e.type === "pointerup" && e.button !== 1) {
        var hit = hitAt(e.clientX, e.clientY);
        if (hit && hit.id) { hoverNode(hit.id); open(hit.id); }
        else if (hit && hit.edge) hoverEdge(hit.edge);
      }
      moveNode = null;
      if (drag) { drag = null; surface.classList.remove("is-ziehen"); }
    }
    surface.addEventListener("pointerup", up);
    surface.addEventListener("pointercancel", up);
    surface.addEventListener("pointerleave", function (e) { if (!drag && e.pointerType === "mouse") { hoverId = null; setFocus(null); showInfo(""); } });
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
    var form = root.querySelector(".karte-suche"), input = form.querySelector("input");
    form.addEventListener("submit", function (e) { e.preventDefault(); find(input.value); });
    input.addEventListener("change", function () { if (searchIndex[input.value]) find(input.value); });
    window.addEventListener("resize", function () { setView(view.x + view.w / 2, view.y + view.h / 2, view.w); });
  }
  var renderRaf = 0;
  function scheduleRender() { if (!renderRaf) renderRaf = requestAnimationFrame(function () { renderRaf = 0; render(); }); }

  // ---------- Suche ----------
  var searchIndex = {};
  function fillSearch() {
    searchIndex = {};
    stand.knoten.forEach(function (k) {
      searchIndex[L(k, "titel")] = k.id;
      holders(k).forEach(function (p) { searchIndex[p.name + " – " + L(k, "titel")] = k.id; });
    });
    var opts = Object.keys(searchIndex).sort(function (a, b) { return a.localeCompare(b, "de"); });
    root.querySelector("#og-liste").innerHTML = opts.map(function (o) { return '<option value="' + esc(o) + '">'; }).join("");
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
    if (!id) { showInfo(esc(T.notFound)); return; }
    fit([id], 720);
    hoverId = null;
    hoverNode(id);
  }

  // ---------- Legende ----------
  var pinnedArt = null;
  function bindLegend() {
    document.querySelectorAll(".og-aside [data-art]").forEach(function (b) {
      var art = b.getAttribute("data-art");
      b.addEventListener("pointerenter", function (e) { if (!pinnedArt && e.pointerType === "mouse") setFocus(focusArt(art)); });
      b.addEventListener("pointerleave", function (e) { if (!pinnedArt && e.pointerType === "mouse") setFocus(null); });
      b.addEventListener("click", function () {
        pinnedArt = pinnedArt === art ? null : art;
        pinnedFocus = focusArt(pinnedArt);
        document.querySelectorAll(".og-aside [data-art]").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-art") === pinnedArt)); });
        setFocus(null);
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
      if (j) { e.preventDefault(); var to = j.getAttribute("data-springe"); fit([to], 720); hoverNode(to); fillInfo(to); }
    });
  }
  function row(k, v) { return '<tr><th scope="row">' + k + "</th><td>" + v + "</td></tr>"; }
  function personHtml(p, k) {
    var n = p.url ? '<a href="' + esc(p.url) + '">' + esc(p.name) + "</a>" : esc(p.name);
    var extra = p.titel.slice();
    if (k.nutzer.indexOf(p.id) >= 0) extra.push(T.byDecree);
    return "<strong>" + n + "</strong>" + (extra.length ? ' <span class="karte-titel">' + esc(extra.join(" · ")) + "</span>" : "");
  }
  function jump(id) { return '<button type="button" class="link-arrow org-sprung" data-springe="' + id + '">' + esc(L(node(id), "titel")) + "</button>"; }
  function openInfo(id) { if (infoDlg) { fillInfo(id); if (!infoDlg.open) infoDlg.showModal(); } }
  function fillInfo(id) {
    var k = node(id), rows = [];
    var html = '<div class="og-amt-kopf">' + (k.bild ? '<img src="' + cfg.bilder + k.bild + '.webp" alt="" width="84" height="84">' : "") + "<div>" +
      (L(k, "kurz") ? '<span class="eyebrow">' + esc(L(k, "kurz")) + "</span>" : "") + '<h2 id="og-amt-titel">' + esc(L(k, "titel")) + "</h2></div></div>";
    if (staffed(k)) {
      var h = holders(k);
      rows.push(row(esc(h.length > 1 ? T.holders : T.holder), h.length ? h.map(function (p) { return personHtml(p, k); }).join("<br>") : esc(T.vacant)));
    }
    var m = members(k);
    if (m !== null) rows.push(row(esc(T.members), fmt(m)));
    if (rows.length) html += '<table class="styles-table is-grid karte-gebiet-tabelle"><tbody>' + rows.join("") + "</tbody></table>";
    var text = L(k, "text");
    if (text) html += '<h3 class="karte-gebiet-h">' + esc(T.about) + '</h3><div class="prose org-text">' +
      text.split(/\n\s*\n/).map(function (p) { return "<p>" + esc(p.trim()) + "</p>"; }).join("") + "</div>";
    // Beziehungen: ausgehend (Aktiv) und eingehend (Passiv), je Art gruppiert, in Legendenreihenfolge
    var rel = [];
    cfg.arten.forEach(function (a) {
      var aus = stand.kanten.filter(function (e) { return e.art === a && e.von === id; }).map(function (e) { return jump(e.nach); });
      var ein = stand.kanten.filter(function (e) { return e.art === a && e.nach === id; }).map(function (e) { return jump(e.von); });
      if (aus.length) rel.push(row(swatch(a) + " " + esc(T.arten[a].aktiv), aus.join("<br>")));
      if (ein.length) rel.push(row(swatch(a) + " " + esc(T.arten[a].passiv), ein.join("<br>")));
    });
    if (rel.length) html += '<h3 class="karte-gebiet-h">' + esc(T.relations) + '</h3><table class="styles-table is-grid karte-gebiet-tabelle og-rel"><tbody>' + rel.join("") + "</tbody></table>";
    var notes = [];
    if (k.rollen.length) {
      var q = EN ? ["“", "”"] : ["„", "“"];
      var names = k.rollen.map(function (r) { return q[0] + (roleName(r) || r) + q[1]; }).join(" " + T.or + " ");
      notes.push(T.rolesNote.replace("{r}", names + (k.zusatz ? " " + T.rolesAnd.replace("{z}", roleName(k.zusatz) || k.zusatz) : "")));
    }
    if (k.angehoerige && roleName(k.angehoerige)) notes.push(T.membersNote.replace("{r}", roleName(k.angehoerige)));
    if (notes.length) html += '<p class="karte-feldhinweis">' + esc(notes.join(" ")) + "</p>";
    infoDlg.querySelector("[data-amt-inhalt]").innerHTML = html;
    var link = linkOf(k);
    infoDlg.querySelector("[data-amt-link]").innerHTML = link ? '<a class="btn btn-navy" href="' + esc(link) + '">' + esc(T.toPage) + "</a>" : "";
    infoDlg.querySelector("[data-amt-inhalt]").focus();
  }

  // ---------- Bild herunterladen ----------
  var PNG = { paper: "#fbf9f4", ivory: "#f5f1e8", white: "#ffffff", ink: "#161a2e", ink2: "#3a3e52", muted: "#646778", rule: "#ddd5c3",
    ruleStrong: "#bfb294", gold: "#c9a43a", gold6: "#9a7618", gold3: "#e4cb7a", navy: "#12183c", navyLine: "#2b3570" };
  var ART_FARBE = { vorschlag: "#3b4aa3", wahl: "#8645ad", ernennung: "#d4890f", ausfertigung: "#2e8b57", bildung: "#2a96cc",
    beschluss: "#ad9152", veto: "#b8322a", kontrolle: "#161a2e", gliederung: "#bfb294" };
  function download() {
    preload();
    Promise.all(Object.keys(images).map(function (k) { return images[k].decode ? images[k].decode().catch(function () {}) : null; })).then(draw);
  }
  function draw() {
    var M = 64, HEAD = 120, S = 2, LEG = 250;
    var cw = full.w + 2 * M + LEG, ch = Math.max(full.h, cfg.arten.length * 26 + 60) + HEAD + M + 30;
    var c = document.createElement("canvas");
    c.width = Math.round(cw * S); c.height = Math.round(ch * S);
    var g = c.getContext("2d");
    g.scale(S, S);
    g.fillStyle = PNG.paper; g.fillRect(0, 0, cw, ch);
    g.fillStyle = PNG.gold; g.fillRect(0, 0, cw, 6);
    g.fillStyle = PNG.ink; g.font = "600 34px " + SERIF;
    g.fillText(T.png, M, 64);
    g.fillStyle = PNG.muted; g.font = "400 14px " + SANS;
    g.fillText("Imperium Germanicum · " + T.asOf + " " + (cfg.stand_datum || ""), M, 90);
    // Legende rechts
    var lx = cw - M - LEG + 30, ly = HEAD;
    g.font = "600 17px " + SERIF; g.fillStyle = PNG.ink; g.fillText(T.legend, lx, ly + 4);
    cfg.arten.forEach(function (a, i) {
      var y = ly + 30 + i * 26;
      arrow(g, { x1: lx, y1: y, x2: lx + 34, y2: y }, a);
      g.fillStyle = PNG.ink2; g.font = "400 14px " + SANS; g.fillText(T.arten[a].aktiv, lx + 46, y + 5);
    });
    g.save();
    g.translate(M - full.x, HEAD - full.y);
    frames.forEach(function (f) {
      g.fillStyle = PNG.ivory; g.fillRect(f.x, f.y, f.w, f.h);
      g.strokeStyle = PNG.ruleStrong; g.lineWidth = 1; g.setLineDash([5, 4]); g.strokeRect(f.x + 0.5, f.y + 0.5, f.w - 1, f.h - 1); g.setLineDash([]);
      g.fillStyle = PNG.muted; g.font = F.rahmen.font; g.textAlign = "center"; g.fillText(L(f.r, "titel"), f.x + f.w / 2, f.y + f.h - 13); g.textAlign = "left";
    });
    edges.forEach(function (e) { arrow(g, e, e.e.art); });
    stand.knoten.forEach(function (k) {
      var b = boxes[k.id], im = images[k.bild];
      if (im && im.complete && im.naturalWidth) {
        var sc = Math.min(b.img / im.naturalWidth, b.img / im.naturalHeight), w = im.naturalWidth * sc, h = im.naturalHeight * sc;
        g.drawImage(im, b.x + (b.w - w) / 2, b.y + (b.img - h) / 2, w, h);
      } else {
        g.fillStyle = PNG.navy; g.beginPath(); g.arc(b.x + b.w / 2, b.y + b.img / 2, b.img / 2 - 2, 0, Math.PI * 2); g.fill();
        g.fillStyle = PNG.gold3; g.font = "600 28px " + SERIF; g.textAlign = "center"; g.fillText(initials(L(k, "titel")), b.x + b.w / 2, b.y + b.img / 2 + 10);
      }
      g.textAlign = "center";
      b.rows.forEach(function (r) {
        g.font = r.f.font; g.fillStyle = { "org-t-titel": PNG.ink, "org-t-person": PNG.ink2, "org-t-leer": PNG.muted }[r.cls];
        g.fillText(r.t, b.x + b.w / 2, b.y + r.y);
      });
      g.textAlign = "left";
    });
    g.restore();
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
  function arrow(g, e, art) {
    var col = ART_FARBE[art], head = art === "gliederung" ? 0 : 10;
    var fx = e.cx != null ? e.cx : e.x1, fy = e.cy != null ? e.cy : e.y1, ang = Math.atan2(e.y2 - fy, e.x2 - fx);
    var ex = e.x2 - Math.cos(ang) * head * 0.8, ey = e.y2 - Math.sin(ang) * head * 0.8;
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1.8;
    g.beginPath(); g.moveTo(e.x1, e.y1);
    if (e.cx != null) g.quadraticCurveTo(e.cx, e.cy, ex, ey); else g.lineTo(ex, ey);
    g.stroke();
    if (!head) return;
    g.beginPath(); g.moveTo(e.x2, e.y2);
    g.lineTo(e.x2 - head * Math.cos(ang) + head * 0.5 * Math.sin(ang), e.y2 - head * Math.sin(ang) - head * 0.5 * Math.cos(ang));
    g.lineTo(e.x2 - head * Math.cos(ang) - head * 0.5 * Math.sin(ang), e.y2 - head * Math.sin(ang) + head * 0.5 * Math.cos(ang));
    g.closePath(); g.fill();
  }
  // Wappen für den Bild-Export vorladen (gleiche Herkunft, die Leinwand bleibt lesbar)
  var images = {};
  function preload() {
    stand.knoten.forEach(function (k) {
      if (k.bild && !images[k.bild]) { var im = new Image(); im.src = cfg.bilder + k.bild + ".webp"; images[k.bild] = im; }
    });
  }
  var dl = document.querySelector("[data-bild]");
  if (dl) dl.addEventListener("click", download);

  // ---------- Editor ----------
  var undo = [], redo = [], basis = cfg.basis, dlg, editing = null, isNew = false, chips = [], tmpKanten = [];
  function snapshot() { return JSON.stringify(stand); }
  function remember(before) { undo.push(before); if (undo.length > 200) undo.shift(); redo = []; updateStatus(); }
  function dirty() {
    var n = 0;
    ["knoten", "rahmen"].forEach(function (f) {
      var a = {};
      saved[f].forEach(function (x) { a[x.id] = JSON.stringify(x); });
      stand[f].forEach(function (x) { if (a[x.id] !== JSON.stringify(x)) n++; delete a[x.id]; });
      n += Object.keys(a).length;
    });
    var key = function (e) { return e.von + ">" + e.nach + ">" + e.art; };
    var ka = saved.kanten.map(key), kb = stand.kanten.map(key);
    n += ka.filter(function (x) { return kb.indexOf(x) < 0; }).length + kb.filter(function (x) { return ka.indexOf(x) < 0; }).length;
    return n;
  }
  function updateStatus() {
    if (!EDIT) return;
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
  function nextId(list, p) {
    var m = 0;
    list.forEach(function (x) { m = Math.max(m, parseInt(String(x.id).slice(1), 10) || 0); });
    return p + (m + 1);
  }
  var FIELDS = ["titel", "titel_en", "kurz", "kurz_en", "text", "text_en", "link"];
  function fld(name) { return dlg.querySelector("#of-" + name); }
  function drawChips() {
    dlg.querySelector("[data-chips]").innerHTML = chips.map(function (r) {
      return "<li><span>" + esc(roleName(r) || r) + '</span><button type="button" class="btn btn-line btn-small" data-weg="' + r + '" aria-label="' +
        esc(T.remove + ": " + (roleName(r) || r)) + '">×</button></li>';
    }).join("");
  }
  function titleOf(id) { return id === editing.id ? (fld("titel").value.trim() || T.thisBody) : node(id) ? node(id).titel : id; }
  function drawKanten() {
    var list = tmpKanten.filter(function (e) { return e.von === editing.id || e.nach === editing.id; });
    dlg.querySelector("[data-kanten]").innerHTML = list.length ? list.map(function (e) {
      return '<li><span class="og-beziehung">' + swatch(e.art) + " " + esc(titleOf(e.von)) + " <em>" + esc(T.arten[e.art].aktiv) + "</em> " + esc(titleOf(e.nach)) +
        '</span><button type="button" class="btn btn-line btn-small" data-kante-weg="' + e.id + '" aria-label="' + esc(T.remove) + '">×</button></li>';
    }).join("") : '<li class="karte-feldhinweis">' + esc(T.noRelations) + "</li>";
  }
  function openEditor(id) {
    if (!dlg) return;
    isNew = !id;
    if (isNew) {
      var c = { x: view.x + view.w / 2 - 115, y: view.y + view.h / 2 - 40 };
      editing = { id: nextId(stand.knoten, "k"), titel: "", titel_en: "", kurz: "", kurz_en: "", text: "", text_en: "", form: "organ", bild: "",
        x: Math.round(c.x / 10) * 10, y: Math.round(c.y / 10) * 10, rahmen: "", rollen: [], zusatz: "", nutzer: [], angehoerige: "", link: "" };
    } else editing = clone(node(id));
    tmpKanten = clone(stand.kanten);
    dlg.querySelector("[data-dialog-titel]").textContent = isNew ? T.newBody : T.editBody;
    FIELDS.forEach(function (f) { fld(f).value = editing[f] || ""; });
    fld("form").value = editing.form;
    if (editing.bild && !fld("bild").querySelector('option[value="' + editing.bild + '"]')) fld("bild").insertAdjacentHTML("beforeend", '<option value="' + editing.bild + '">' + editing.bild + "</option>");
    fld("bild").value = editing.bild || "";
    showEmblem();
    fld("zusatz").value = editing.zusatz;
    fld("angehoerige").value = editing.angehoerige;
    fld("nutzer").value = editing.nutzer.join(", ");
    var fr = frameOf(editing.rahmen);
    fld("rahmen").value = fr ? fr.titel : "";
    dlg.querySelector("#og-rahmen-liste").innerHTML = stand.rahmen.map(function (r) { return '<option value="' + esc(r.titel) + '">'; }).join("");
    fld("ziel").innerHTML = stand.knoten.filter(function (k) { return k.id !== editing.id; }).sort(function (a, b) { return a.titel.localeCompare(b.titel, "de"); })
      .map(function (k) { return '<option value="' + k.id + '">' + esc(k.titel) + "</option>"; }).join("");
    chips = editing.rollen.slice();
    drawChips();
    drawKanten();
    dlg.querySelector('[data-aktion="loeschen"]').hidden = isNew;
    showError("");
    if (!dlg.open) dlg.showModal();
    fld("titel").focus();
  }
  function showEmblem() {
    var v = fld("bild").value;
    dlg.querySelector("[data-bild-vorschau]").innerHTML = v ? '<img src="' + cfg.bilder + v + '.webp" alt="" width="64" height="64">' : "";
  }
  function showError(t) { var e = dlg.querySelector("[data-dialog-fehler]"); e.textContent = t; e.hidden = !t; }
  function apply() {
    var k = clone(editing);
    FIELDS.forEach(function (f) { k[f] = fld(f).value.trim(); });
    k.form = fld("form").value; k.bild = fld("bild").value; k.zusatz = fld("zusatz").value; k.angehoerige = fld("angehoerige").value;
    k.rollen = chips.slice();
    var ids = fld("nutzer").value.split(/[\s,;]+/).filter(Boolean);
    if (ids.some(function (x) { return !/^[0-9]{5,22}$/.test(x); })) { showError(T.idsBad); return false; }
    k.nutzer = ids;
    if (!k.titel) { showError(T.nameEmpty); return false; }
    if (k.link && !/^\/[^\/\\\s]/.test(k.link)) { showError(T.linkBad); return false; }
    var before = snapshot();
    // Rahmen über seinen Namen: vorhandenen nehmen oder neu anlegen; leere Rahmen entfallen
    var rt = fld("rahmen").value.trim();
    if (!rt) k.rahmen = "";
    else {
      var fr = stand.rahmen.find(function (r) { return r.titel.toLowerCase() === rt.toLowerCase(); });
      if (!fr) { fr = { id: nextId(stand.rahmen, "r"), titel: rt, titel_en: "" }; stand.rahmen.push(fr); }
      k.rahmen = fr.id;
    }
    var old = node(k.id);
    if (old) stand.knoten[stand.knoten.indexOf(old)] = k; else stand.knoten.push(k);
    stand.kanten = tmpKanten;
    stand.rahmen = stand.rahmen.filter(function (r) { return stand.knoten.some(function (x) { return x.rahmen === r.id; }); });
    if (before !== snapshot()) remember(before);
    render(); fillSearch();
    return true;
  }
  function initEditor() {
    dlg = document.querySelector("[data-dialog]");
    dlg.querySelector("form").addEventListener("submit", function (e) {
      if (e.submitter && e.submitter.value === "cancel") return;
      e.preventDefault();
      if (apply()) dlg.close("ok");
    });
    fld("bild").addEventListener("change", showEmblem);
    fld("rolle").addEventListener("change", function () {
      var v = fld("rolle").value;
      if (v && chips.indexOf(v) < 0) { chips.push(v); drawChips(); }
      fld("rolle").value = "";
    });
    dlg.querySelector("[data-chips]").addEventListener("click", function (e) {
      var b = e.target.closest("[data-weg]");
      if (b) { chips = chips.filter(function (r) { return r !== b.getAttribute("data-weg"); }); drawChips(); }
    });
    dlg.querySelector("[data-kanten]").addEventListener("click", function (e) {
      var b = e.target.closest("[data-kante-weg]");
      if (b) { tmpKanten = tmpKanten.filter(function (x) { return x.id !== b.getAttribute("data-kante-weg"); }); drawKanten(); }
    });
    dlg.querySelector('[data-aktion="kante"]').addEventListener("click", function () {
      var other = fld("ziel").value, art = fld("art").value, aus = fld("richtung").value === "aus";
      if (!other) return;
      var e = { id: nextId(tmpKanten, "e"), von: aus ? editing.id : other, nach: aus ? other : editing.id, art: art };
      if (!tmpKanten.some(function (x) { return x.von === e.von && x.nach === e.nach && x.art === e.art; })) tmpKanten.push(e);
      drawKanten();
    });
    dlg.querySelector('[data-aktion="loeschen"]').addEventListener("click", function () {
      var k = node(editing.id), n = stand.kanten.filter(function (e) { return e.von === k.id || e.nach === k.id; }).length;
      if (!window.confirm(T.confirmDelete.replace("{name}", k.titel).replace("{n}", n))) return;
      var before = snapshot();
      stand.knoten = stand.knoten.filter(function (x) { return x.id !== k.id; });
      stand.kanten = stand.kanten.filter(function (e) { return e.von !== k.id && e.nach !== k.id; });
      stand.rahmen = stand.rahmen.filter(function (r) { return stand.knoten.some(function (x) { return x.rahmen === r.id; }); });
      remember(before);
      dlg.close("cancel");
      render(); fillSearch();
    });
    root.querySelector('[data-aktion="neu"]').addEventListener("click", function () { openEditor(null); });
    root.querySelector('[data-aktion="undo"]').addEventListener("click", function () { step(-1); });
    root.querySelector('[data-aktion="redo"]').addEventListener("click", function () { step(1); });
    document.addEventListener("keydown", function (e) {
      if (!(e.ctrlKey || e.metaKey) || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || document.querySelector("dialog[open]")) return;
      var key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); step(-1); }
      else if (key === "y" || key === "z" && e.shiftKey) { e.preventDefault(); step(1); }
    });
    window.addEventListener("beforeunload", function (e) { if (dirty()) { e.preventDefault(); e.returnValue = T.leave; } });
    var sdlg = document.querySelector("[data-speichern]"), note = sdlg.querySelector("#og-bemerkung"), msg = sdlg.querySelector("[data-meldung]");
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
            // Der Dienst vergibt die Kennungen der Beziehungen neu; seinen Stand übernehmen
            basis = j.version; stand = j.stand || stand; saved = clone(stand); note.value = ""; undo = []; redo = [];
            render(); say(T.saved, "ok"); sdlg.close("ok");
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
      .then(function (j) {
        personen = j.personen || []; zahlen = j.zahlen || {};
        (j.rollen || []).forEach(function (r) { if (!roleNames[r.id]) roleNames[r.id] = r.name; });
      })
      .catch(function () { showInfo(esc(T.infoError)); });
  }
  var fonts = document.fonts && document.fonts.load ? Promise.all([F.titel.font, F.person.font, F.leer.font, F.kurz.font].map(function (f) {
    return document.fonts.load(f);
  })).catch(function () {}) : Promise.resolve();
  Promise.all([load(), fonts]).then(function () {
    render();
    preload();
    var top = stand.knoten.slice().sort(function (a, b) { return a.y - b.y; })[0];
    if (surface.clientWidth < 600 && top) {
      // schmaler Bildschirm: oben am Souverän beginnen, Kästen in lesbarer Größe
      var b = boxes[top.id], w = 420;
      setView(b.x + b.w / 2, b.y - 30 + w * aspect() / 2, w);
    } else fit();
    fillSearch();
    bindView();
    bindLegend();
    if (EDIT) initEditor();
  }).catch(function () {
    var l = surface.querySelector(".karte-laden");
    if (l) l.textContent = T.loadError;
  });
})();
