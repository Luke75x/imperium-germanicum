/* Reichskarte (/karte/): Anzeige und Editor.
   Konfiguration aus #karte-cfg (vom Wiki-Dienst, Modul karte.py), Geodaten aus /karte/geo.json (NUTS-3-Gebiete als SVG-Pfade).
   Anzeige: Zoomen (Mausrad, Knöpfe, Tasten, zwei Finger), Verschieben, Gebiet unter dem Zeiger, Suche, Legende hebt Teilstaaten hervor.
   Klick auf ein Gebiet (Anzeige): Fenster mit Teilstaat, Regent (Landesherr + Fraktionsrolle bzw. Kanzler), Bevölkerung, Fläche;
   angemeldete Regenten beantragen dort einen neuen Namen für einen Bezirk ihres Teilstaats (entscheidet der Kanzler per Discord-DM
   des Bots). Gebietsnamen im Rollenspiel stehen in stand.namen; der heutige amtliche Name bleibt sichtbar.
   Editor (nur Server-Admins): Gebiete per Klick/Ziehen zuweisen, Pipette, ganze Länder, Teilstaaten anlegen/ändern/löschen,
   Rückgängig/Wiederholen, Speichern mit Bemerkung und Konflikterkennung. Auf dem Handy (bis 900 px): Vollbild-Karte mit Leiste unten
   (Teilstaat, Zuweisen/Verschieben, Rückgängig, Speichern), die Seitenleiste öffnet sich als Blatt; Antippen weist zu,
   zwei Finger verschieben und zoomen. Farben der Karte kommen aus den Tokens in site.css. */
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
  if (!stand.gebaeude) stand.gebaeude = [];
  var saved = clone(stand);
  var gsel = null, gdrag = null, gAlt = null;   // gewähltes Gebäude (Editor), ziehendes Gebäude
  var geo, svg, defs, layer, hilite, paths = {}, full, view = { x: 0, y: 0, w: 1 };
  var raf = 0, kk = null, beschr = null, komp = null, detailTimer = 0, mask, flu, netzEl, schGrob = [], schFein = [], schSeen = null, schSeenF = null, schProv = null, ansicht = null;

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fmt(n) { return n.toLocaleString(document.documentElement.lang === "en" ? "en-GB" : "de-DE"); }
  function state(id) { for (var i = 0; i < stand.staaten.length; i++) if (stand.staaten[i].id === id) return stand.staaten[i]; return null; }
  function gname(id) { return (stand.namen && stand.namen[id]) || geo.gebiete[id].n; }
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
  function paintAll() { Object.keys(paths).forEach(paint); detailsNeu(); }

  // ---------- Details: Grenzen, Teilstaatsnamen, Orte ----------
  // Grenzen und Namen hängen an der Zuordnung der Gebiete und werden deshalb nach jeder Änderung neu berechnet.
  function detailsNeu() {
    clearTimeout(detailTimer);
    detailTimer = setTimeout(function () { komp = null; grenzen(); beschriften(); }, 30);
  }
  function kantenListe() { return (feinAn && fein && fein.kanten) || geo.kanten || []; }
  function grenzen() {
    if (!kk || !geo.kanten) return;
    var kreis = [], land = [], staat = [];
    kantenListe().forEach(function (e) {
      if (!sichtbarKante(e)) return;
      var sa = stand.gebiete[e[0]] || "", sb = stand.gebiete[e[1]] || "";
      if (sa !== sb) staat.push(e[2]);
      else if (geo.gebiete[e[0]].c !== geo.gebiete[e[1]].c) land.push(e[2]);
      else kreis.push(e[2]);
    });
    kk.kreis.setAttribute("d", kreis.join(""));
    kk.land.setAttribute("d", land.join(""));
    kk.staat.setAttribute("d", staat.join(""));
  }
  // Zusammenhängende Teile eines Teilstaats (über gemeinsame Grenzabschnitte) mit Schwerpunkt und Fläche
  function komponenten() {
    if (komp) return komp;
    var nb = {};
    kantenListe().forEach(function (e) {
      if ((stand.gebiete[e[0]] || "") === (stand.gebiete[e[1]] || "")) { (nb[e[0]] = nb[e[0]] || []).push(e[1]); (nb[e[1]] = nb[e[1]] || []).push(e[0]); }
    });
    var seen = {}, out = [];
    Object.keys(stand.gebiete).forEach(function (id) {
      if (seen[id] || !stand.gebiete[id] || !geo.mitte[id]) return;
      var st = [id], c = { staat: stand.gebiete[id], ids: [], a: 0, x: 0, y: 0 };
      seen[id] = 1;
      while (st.length) {
        var k = st.pop(), m = geo.mitte[k];
        c.ids.push(k); c.a += m[2]; c.x += m[0] * m[2]; c.y += m[1] * m[2];
        (nb[k] || []).forEach(function (n) { if (!seen[n] && stand.gebiete[n] === c.staat) { seen[n] = 1; st.push(n); } });
      }
      c.x /= c.a; c.y /= c.a;
      // liegt der Schwerpunkt außerhalb (Hufeisenform), nimm den nächsten Gebietsmittelpunkt
      var best = null, bd = Infinity;
      c.ids.forEach(function (k) { var m = geo.mitte[k], d = Math.hypot(m[0] - c.x, m[1] - c.y); if (d < bd) { bd = d; best = m; } });
      if (best && bd > Math.sqrt(c.a) * 0.12) { c.x = best[0]; c.y = best[1]; }
      out.push(c);
    });
    return (komp = out.sort(function (a, b) { return b.a - a.a; }));
  }
  function dunkel(hex) {
    var n = parseInt(String(hex).slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140;
  }
  // Kartenstufe wie bei Kacheln: 0 = ganze Welt auf 256 px … je höher, desto näher
  function stufe() { return Math.log(geo.breite / (base || view).w) / Math.LN2 + Math.log(Math.max(300, surface.clientWidth) / 256) / Math.LN2; }
  // ---------- Behördengebäude ----------
  function typen() { return cfg.gebaeudeTypen || []; }
  function typIndex(id) { var t = typen(); for (var i = 0; i < t.length; i++) if (t[i].id === id) return (t[i].farbe || 0) % 8; return 6; }
  function typ(id) { var t = typen(); for (var i = 0; i < t.length; i++) if (t[i].id === id) return t[i]; return null; }
  function typName(id) { var t = typen(); for (var i = 0; i < t.length; i++) if (t[i].id === id) return t[i].name; return id; }
  function gebaeudeById(id) { var a = stand.gebaeude || []; for (var i = 0; i < a.length; i++) if (a[i].id === id) return a[i]; return null; }
  function gebaeudeAn(p) {
    // nächstes Gebäude in Reichweite (Kartenkoordinaten p)
    var rad = 11 * (base || view).w / Math.max(1, surface.clientWidth), best = null, bd = rad;
    (stand.gebaeude || []).forEach(function (g) { var d = Math.hypot(g.x - p.x, g.y - p.y); if (d < bd) { bd = d; best = g; } });
    return best;
  }

  function beschriften() {
    if (!beschr || !geo.orte || !base) return;
    var zt = stufe();
    var u = base.w / Math.max(1, surface.clientWidth);     // Kartenpixel je Bildschirmpixel
    var x0 = base.x - base.w / 4, x1 = base.x + base.w * 1.25, y0 = base.y - base.h / 4, y1 = base.y + base.h * 1.25;
    var belegt = [], out = [];
    function frei(x, y, w, h) {
      for (var i = 0; i < belegt.length; i++) { var b = belegt[i]; if (x < b[2] && x + w > b[0] && y < b[3] && y + h > b[1]) return false; }
      belegt.push([x, y, x + w, y + h]); return true;
    }
    function breite(t, px) { return t.length * px * 0.56 * u; }
    function text(t, x, y, px, cls, stil, anker, rot) {
      return '<text class="' + cls + '" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" font-size="' + (px * u).toFixed(2) + '" stroke-width="' + (px * u * 0.28).toFixed(2) + '"' +
        (anker ? ' text-anchor="' + anker + '"' : "") + (stil ? ' style="' + stil + '"' : "") +
        (rot ? ' transform="rotate(' + rot + " " + x.toFixed(1) + " " + y.toFixed(1) + ')"' : "") + ">" + esc(t) + "</text>";
    }
    function sichtbar(x, y) { return x > x0 && x < x1 && y > y0 && y < y1; }
    // Orte nach eigener Mindeststufe, Hauptstädte zuerst
    var orte = fein && feinAn ? geo.orte.concat(fein.orte || []) : geo.orte;
    var kand = orte.filter(function (o) { return o[3] <= zt && sichtbar(o[1], o[2]); }).sort(function (a, b) { return a[4] - b[4] || a[3] - b[3]; });
    function ort(o) {
      var rang = o[4], px = rang === 1 ? 12.5 : rang === 2 ? 11.5 : 10.5, r = (rang === 1 ? 3.4 : rang === 2 ? 2.8 : 2.2) * u;
      var w = breite(o[0], px) + r * 3, h = px * 1.2 * u;
      if (!frei(o[1] - r, o[2] - h / 2, w, h)) return;
      out.push('<circle class="bs-punkt r' + rang + '" cx="' + o[1] + '" cy="' + o[2] + '" r="' + r.toFixed(2) + '"/>' +
        text(o[0], o[1] + r * 1.9, o[2] + px * 0.35 * u, px, "bs-ort r" + rang, ""));
    }
    // Hauptstädte der Teilstaaten: Stern mit fettem Namen, ab der Stufe der Teilstaaten, vor allen anderen Namen
    if (zt >= 3.4 && !root.classList.contains("ohne-hauptstaedte")) {
      stand.staaten.forEach(function (s) {
        var h = s.hauptstadt;
        if (!h || !sichtbar(h.x, h.y)) return;
        var px = 13.5, r = 6.2 * u, w = breite(h.name, px) + r * 3.2, hh = px * 1.3 * u;
        if (!frei(h.x - r, h.y - hh / 2, w, hh)) return;
        var pts = [];
        for (var i = 0; i < 10; i++) { var a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.45 : r; pts.push((h.x + Math.cos(a) * rr).toFixed(1) + "," + (h.y + Math.sin(a) * rr).toFixed(1)); }
        out.push('<polygon class="bs-hs" points="' + pts.join(" ") + '" stroke-width="' + (1.4 * u).toFixed(2) + '"/>' +
          text(h.name, h.x + r * 1.5, h.y + px * 0.35 * u, px, "bs-ort bs-hs-name", ""));
      });
    }
    // Behördengebäude (von der RP-Leitung gesetzt): Symbol ab Stufe 4, Name ab Stufe 6 (wo Platz ist)
    if (zt >= 4 && !root.classList.contains("ohne-behoerden")) {
      (stand.gebaeude || []).forEach(function (g) {
        if (!sichtbar(g.x, g.y)) return;
        var r = 8 * u, ti = typIndex(g.typ), gew = EDIT && g.id === gsel;
        var d = 'M' + (g.x - r * .62).toFixed(1) + ' ' + (g.y - r * .08).toFixed(1) + 'L' + g.x.toFixed(1) + ' ' + (g.y - r * .66).toFixed(1) + 'L' + (g.x + r * .62).toFixed(1) + ' ' + (g.y - r * .08).toFixed(1) + 'Z' +
          [-.4, 0, .4].map(function (k) { return 'M' + (g.x + r * k).toFixed(1) + ' ' + (g.y + r * .02).toFixed(1) + 'V' + (g.y + r * .5).toFixed(1); }).join("") +
          'M' + (g.x - r * .62).toFixed(1) + ' ' + (g.y + r * .62).toFixed(1) + 'H' + (g.x + r * .62).toFixed(1);
        out.push('<g class="bs-geb t' + ti + (gew ? ' gew' : '') + '"><rect x="' + (g.x - r).toFixed(1) + '" y="' + (g.y - r).toFixed(1) + '" width="' + (2 * r).toFixed(1) + '" height="' + (2 * r).toFixed(1) + '" rx="' + (r * .28).toFixed(1) + '" stroke-width="' + ((gew ? 2.6 : 1.5) * u).toFixed(2) + '"/>' +
          '<path d="' + d + '" stroke-width="' + (1.3 * u).toFixed(2) + '"/></g>');
        belegt.push([g.x - r, g.y - r, g.x + r, g.y + r]);
        if (zt < 6) return;
        var px = 11.5, w = breite(g.name, px) + r * 3, hh = px * 1.3 * u;
        if (frei(g.x + r * 1.3, g.y - hh / 2, w, hh)) out.push(text(g.name, g.x + r * 1.9, g.y + px * 0.35 * u, px, "bs-ort bs-geb-name", ""));
      });
    }
    kand.filter(function (o) { return o[4] === 1; }).forEach(ort);
    // Teilstaaten: Name im größten Teil jedes Staats, kleinere Teile erst bei starker Vergrößerung
    komponenten().forEach(function (c) {
      var s = state(c.staat); if (!s || !sichtbar(c.x, c.y)) return;
      var breitePx = Math.sqrt(c.a) / u;
      if (breitePx < 46) return;
      var px = Math.max(11, Math.min(16, breitePx * 0.11));
      var wort = s.name.split(" "), mitte = Math.ceil(wort.length / 2);
      var zeilen = s.name.length > 14 && wort.length > 1 ? [wort.slice(0, mitte).join(" "), wort.slice(mitte).join(" ")] : [s.name];
      var w = 0; zeilen.forEach(function (t) { w = Math.max(w, breite(t, px)); });
      var h = zeilen.length * px * 1.15 * u;
      if (!frei(c.x - w / 2, c.y - h / 2, w, h)) return;
      var d = dunkel(s.farbe) && s.muster === "voll";
      zeilen.forEach(function (t, i) {
        out.push(text(t, c.x, c.y - h / 2 + (i + 0.85) * px * 1.15 * u, px, "bs-staat " + (d ? "hell" : "dunkel"), "", "middle"));
      });
    });
    kand.filter(function (o) { return o[4] !== 1; }).forEach(ort);
    // Flüsse (entlang der Linie gedreht), Ländernamen und Meere
    (geo.flussnamen || []).forEach(function (m) {
      if (m[4] > zt || !sichtbar(m[1], m[2])) return;
      var px = 10.5, w = breite(m[0], px);
      if (!frei(m[1] - w / 2, m[2] - px * u, w, px * 2 * u)) return;
      out.push(text(m[0], m[1], m[2] - 2 * u, px, "bs-fluss", "", "middle", m[3]));
    });
    (geo.laender_namen || []).forEach(function (m) {
      if (zt < m[3] || zt > m[4] + 1.5 || !sichtbar(m[1], m[2]) || (m[5] && zt > 4.6)) return;
      var px = Math.max(10.5, Math.min(15, 9 + zt * 0.8)), t = m[0].toUpperCase();
      var w = breite(t, px) * 1.25;
      if (!frei(m[1] - w / 2, m[2] - px * u, w, px * 2 * u)) return;
      out.push(text(t, m[1], m[2], px, "bs-land", "", "middle"));
    });
    geo.meere.forEach(function (m) {
      if (zt < m[4] - 0.2 || zt > m[5] + 1 || !sichtbar(m[1], m[2])) return;
      var px = 12 + Math.min(zt, 5) * 0.6, w = breite(m[0], px) * 1.1;
      if (!frei(m[1] - w / 2, m[2] - px * u, w, px * 2 * u)) return;
      out.push(text(m[0], m[1], m[2], px, "bs-meer", "", "middle", m[3]));
    });
    beschr.innerHTML = out.join("");
    var kreisOp = root.classList.contains("mit-grenzen") ? 0.85 : Math.max(0, Math.min(0.6, (zt - 5.2) * 0.45));
    kk.kreis.style.opacity = kreisOp;
    kk.land.style.opacity = zt < 4 ? 0.55 : 0.85;
    ["L-gren", "L-gren-f"].forEach(function (c) { svg.querySelector("." + c).style.opacity = zt < 3 ? 0.6 : 0.9; });
    svg.querySelector(".L-prov").style.opacity = Math.max(0, Math.min(0.7, (zt - 5.8) * 0.5));
    if (flu) {
      flu.classList.toggle("f-nah", zt > 6);
      for (var k = 1; k <= 4; k++) flu.querySelectorAll(".fl" + k).forEach(function (e) { e.style.opacity = k === 1 ? 1 : k === 2 ? (zt > 3.8 ? 1 : 0) : k === 3 ? (zt > 5 ? 1 : 0) : (zt > 6 ? 1 : 0); });
    }
    netzEl.style.opacity = zt > 6.5 ? 0 : 0.6;
    kk.staat.style.strokeWidth = (zt < 3.5 ? 0.8 : zt < 4.6 ? 1.3 : 1.7) + "px";
    if (flu) flu.style.opacity = zt < 3 ? 0.55 : zt < 4 ? 0.8 : 0.95;
  }

  // ---------- Feine Ebene: genauere Grenzen, Seen, Flüsse, Orte (wird beim Hineinzoomen nachgeladen) ----------
  var fein = null, feinLaden = false, feinAn = false;
  function lod(zt) {
    if (zt >= 6.0 && !fein && !feinLaden && cfg.geoFein) {
      feinLaden = true;
      holeJson([cfg.geoFein, cfg.geoFeinAlt], 4).then(function (f) { fein = f; feinBauen(); lod(stufe()); })
        .catch(function () { feinLaden = false; });
    }
    var an = !!fein && zt >= 6.0;
    if (an !== feinAn) { feinAn = an; feinSchalten(); }
  }
  // Hintergrunddaten liegen in räumlichen Blöcken [x0, y0, x1, y1, Pfad]; gezeichnet werden nur die Blöcke im sichtbaren Bereich
  function schicht(g, chunks, pcls) {
    return { g: g, pcls: pcls, it: chunks.map(function (c) { return { c: c, el: null, an: false }; }) };
  }
  function schichtZeigen(S) {
    if (!S || !ansicht) return;
    var v = ansicht;
    S.it.forEach(function (o) {
      var c = o.c, vis = c[2] >= v.x0 && c[0] <= v.x1 && c[3] >= v.y0 && c[1] <= v.y1;
      if (vis && !o.el) {
        o.el = document.createElementNS(NS, "path");
        o.el.setAttribute("d", c[4]);
        if (S.pcls) o.el.setAttribute("class", S.pcls);
        S.g.appendChild(o.el);
      }
      if (o.el && vis !== o.an) { o.an = vis; o.el.style.display = vis ? "" : "none"; }
    });
  }
  function schichtenZeigen() {
    schGrob.forEach(schichtZeigen); schichtZeigen(schSeen);
    if (feinAn) { schFein.forEach(schichtZeigen); schichtZeigen(schSeenF); schichtZeigen(schProv); }
  }
  function feinBauen() {
    var w = geo.breite;
    function m(lon, lat) { return [(lon + 180) / 360 * w, (0.5 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / (2 * Math.PI)) * w]; }
    var a = m(-32, 74), b = m(80, 22);
    // Meer-Rechteck deckt die grobe Ebene im Ausschnitt ab; darauf liegt die feine Ebene
    mask.setAttribute("d", "M" + a[0] + " " + a[1] + "H" + b[0] + "V" + b[1] + "H" + a[0] + "Z");
    function sch(cls, chunks, pcls) { return schicht(svg.querySelector("." + cls), chunks || [], pcls); }
    var fk = fein.fluesse || {};
    schFein = [sch("L-land-f", fein.land), sch("L-gren-f", fein.grenzen, "kk-welt")];
    [1, 2, 3, 4].forEach(function (k) { schFein.push(sch("L-fl" + k + "f", fk[k])); });
    schSeenF = sch("L-seen-f", fein.seen);
    schProv = sch("L-prov", fein.provinzen, "kk-prov");
  }
  function feinSchalten() {
    ["L-land-f", "L-gren-f", "L-seen-f"].concat([1, 2, 3, 4].map(function (k) { return "L-fl" + k + "f"; })).forEach(function (c) {
      svg.querySelector("." + c).style.display = feinAn ? "" : "none";
    });
    mask.style.display = feinAn ? "" : "none";
    svg.querySelector(".L-seen").style.display = feinAn ? "none" : "";
    if (!feinAn) Object.keys(paths).forEach(function (id) { if (paths[id].getAttribute("data-fein")) { paths[id].setAttribute("d", geo.gebiete[id].d); paths[id].removeAttribute("data-fein"); } });
    redraw();
  }
  // Feine Gebietspfade nur dort, wo gerade etwas sichtbar ist (Rest bleibt grob und wird beim Verschieben nachgezogen)
  function feinGebiete() {
    if (!feinAn || !ansicht) return;
    var v = ansicht;
    Object.keys(paths).forEach(function (id) {
      var b = geo.gebiete[id].b, p = paths[id];
      if (b && b[2] >= v.x0 && b[0] <= v.x1 && b[3] >= v.y0 && b[1] <= v.y1 && !p.getAttribute("data-fein")) { p.setAttribute("d", fein.gebiete[id]); p.setAttribute("data-fein", "1"); }
    });
  }
  function sichtbarKante(e) {
    var v = ansicht; if (!v) return true;
    var a = geo.gebiete[e[0]].b, b = geo.gebiete[e[1]].b; if (!a || !b) return true;
    return Math.min(a[2], b[2]) >= v.x0 && Math.max(a[0], b[0]) <= v.x1 && Math.min(a[3], b[3]) >= v.y0 && Math.max(a[1], b[1]) <= v.y1;
  }

  // ---------- Aufbau ----------
  // Laden mit Wiederholungen: abwechselnd die statische Datei (nginx) und die Route des Dienstes, mit Zeitlimit und wachsender Wartezeit
  function holeJson(urls, versuche) {
    var n = 0;
    urls = urls.filter(Boolean);
    return new Promise(function (ok, fehl) {
      (function los() {
        var url = urls[n % urls.length], ctl = window.AbortController ? new AbortController() : null, timer = setTimeout(function () { if (ctl) ctl.abort(); }, 60000);
        fetch(url, ctl ? { signal: ctl.signal, credentials: "same-origin" } : { credentials: "same-origin" })
          .then(function (r) { if (!r.ok) throw r; return r.json(); })
          .then(function (j) { clearTimeout(timer); if (!j || !j.gebiete) throw new Error("unvollständig"); ok(j); })
          .catch(function () {
            clearTimeout(timer); n++;
            if (n >= versuche) { fehl(); return; }
            var l = surface.querySelector(".karte-laden");
            if (l && !geo) l.textContent = T.loadingRetry.replace("{n}", n + 1);
            setTimeout(los, Math.min(6000, 600 * Math.pow(2, n - 1)));
          });
      })();
    });
  }
  function kartePruefenUndLaden() {
    var l = surface.querySelector(".karte-laden");
    if (l) l.textContent = T.loading;
    holeJson([cfg.geo, cfg.geoAlt], 6).then(init).catch(function () {
      var box = surface.querySelector(".karte-laden") || surface;
      box.innerHTML = "";
      var p = document.createElement("p"); p.className = "karte-laden"; p.textContent = T.loadError;
      var b = document.createElement("button"); b.type = "button"; b.className = "btn btn-navy btn-small"; b.textContent = T.retry;
      b.addEventListener("click", function () { surface.innerHTML = '<p class="karte-laden"></p>'; kartePruefenUndLaden(); });
      var img = document.createElement("img"); img.src = cfg.bild; img.alt = ""; img.style.cssText = "max-width:100%;margin-top:12px;opacity:.85";
      box.appendChild(p); box.appendChild(b); box.appendChild(img);
    });
  }
  kartePruefenUndLaden();

  function init(g) {
    geo = g;
    full = { x: 0, y: 0, w: g.breite, h: g.hoehe };
    var html = ['<svg xmlns="' + NS + '" class="karte-svg" preserveAspectRatio="xMidYMid meet"><defs></defs><g class="karte-hg">'];
    html.push('<g class="L-land"></g><g class="L-gren"></g><path class="karte-maske" style="display:none"/><g class="L-land-f" style="display:none"></g><g class="L-gren-f" style="display:none"></g></g>');
    html.push('<g class="karte-netz">' + g.netz.map(function (d) { return '<path d="' + d + '"/>'; }).join("") + "</g>");
    html.push('<g class="karte-gebiete">');
    Object.keys(g.gebiete).forEach(function (k) { html.push('<path data-id="' + k + '" d="' + g.gebiete[k].d + '"/>'); });
    html.push('</g><g class="karte-wasser"><g class="L-seen"></g><g class="L-seen-f" style="display:none"></g></g>');
    html.push('<g class="karte-fluesse">' + [1, 2, 3, 4].map(function (k) { return '<g class="fl' + k + ' L-fl' + k + '"></g><g class="fl' + k + ' L-fl' + k + 'f" style="display:none"></g>'; }).join("") + "</g>");
    html.push('<g class="karte-kanten"><g class="L-prov"></g><path class="kk-kreis"/><path class="kk-land"/><path class="kk-staat"/></g><g class="karte-beschr"></g><g class="karte-markierung"></g></svg>');
    surface.innerHTML = html.join("");
    svg = surface.querySelector("svg");
    defs = svg.querySelector("defs");
    layer = svg.querySelector(".karte-gebiete");
    hilite = svg.querySelector(".karte-markierung");
    kk = { kreis: svg.querySelector(".kk-kreis"), land: svg.querySelector(".kk-land"), staat: svg.querySelector(".kk-staat") };
    beschr = svg.querySelector(".karte-beschr");
    mask = svg.querySelector(".karte-maske"); netzEl = svg.querySelector(".karte-netz"); flu = svg.querySelector(".karte-fluesse");
    function sch(cls, chunks, pcls) { return schicht(svg.querySelector("." + cls), chunks || [], pcls); }
    schGrob = [sch("L-land", g.land), sch("L-gren", g.grenzen, "kk-welt")];
    [1, 2, 3, 4].forEach(function (k) { schGrob.push(sch("L-fl" + k, (g.fluesse || {})[k])); });
    schSeen = sch("L-seen", g.seen);
    layer.querySelectorAll("path").forEach(function (p) { paths[p.getAttribute("data-id")] = p; });
    buildPatterns();
    paintAll();
    fillSearch();
    root.classList.toggle("mit-grenzen", EDIT);
    root.querySelectorAll("[data-ebene]").forEach(function (c) {
      c.addEventListener("change", function () { root.classList.toggle("ohne-" + c.getAttribute("data-ebene"), !c.checked); beschriften(); });
    });
    var cb = root.querySelector("[data-grenzen]");
    if (cb) { cb.checked = EDIT; cb.addEventListener("change", function () { root.classList.toggle("mit-grenzen", cb.checked); beschriften(); }); }
    fit(Object.keys(stand.gebiete));
    bindView();
    if (EDIT) initEditor(); else { bindLegend(); bindInfo(); gebaeudeListe(); }
    window.addEventListener("resize", function () { setView(view.x + view.w / 2, view.y + view.h / 2, view.w); });
  }

  // ---------- Ausschnitt ----------
  function aspect() { return surface.clientHeight / Math.max(1, surface.clientWidth); }
  function setView(cx, cy, w) {
    w = Math.min(Math.max(w, 30), full.w * 1.05);
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
      if (Math.abs(tx) > cw * 0.2 || Math.abs(ty) > ch * 0.2 || k < 0.75 || k > 4) { redraw(); return; }
      svg.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + k + ")";
    });
  }
  function redraw() {
    clearTimeout(settle);
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    base = { x: view.x, y: view.y, w: view.w, h: view.h };
    svg.setAttribute("viewBox", (view.x - view.w / 4) + " " + (view.y - view.h / 4) + " " + view.w * 1.5 + " " + view.h * 1.5);
    svg.style.transform = "";
    ansicht = { x0: view.x - view.w / 4, x1: view.x + view.w * 1.25, y0: view.y - view.h / 4, y1: view.y + view.h * 1.25 };
    lod(stufe());
    scalePatterns();
    feinGebiete();
    schichtenZeigen();
    grenzen();
    beschriften();
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
    var w = Math.min(Math.max(view.w / f, 30), full.w * 1.05), k = w / view.w;
    var cx = m.x - (m.x - (view.x + view.w / 2)) * k, cy = m.y - (m.y - (view.y + view.h / 2)) * k;
    setView(cx, cy, w);
  }
  function zoomCenter(f) {
    var r = surface.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, f);
  }

  // ---------- Bedienung ----------
  var pointers = {}, drag = null, pinch = null, spaceDown = false, stroke = null, hoverId = null;
  // Finger im Malmodus: erst Antippen oder Ziehen abwarten, damit ein zweiter Finger (Zoomen/Verschieben) nichts einfärbt
  var pendingTouch = null;

  function regionAt(e) {
    var el = document.elementFromPoint(e.clientX, e.clientY);
    return el && el.parentNode === layer ? el.getAttribute("data-id") : null;
  }
  function panMode(e) {
    return !EDIT || spaceDown || e.button === 1 || tool === "verschieben" || tool === "hauptstadt" || tool === "gebaeude" || e.pointerType === "touch" && Object.keys(pointers).length > 1;
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
        pendingTouch = null;
        endStroke();
        var a = pointers[ids[0]], b = pointers[ids[1]];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
        drag = null;
        moving = true;
        return;
      }
      if (EDIT && tool === "gebaeude" && e.button === 0 && ids.length === 1) {
        var gh = gebaeudeAn(toMap(e.clientX, e.clientY));
        if (gh) {   // Gebäude wählen und (beim Ziehen) verschieben
          gebaeudeWaehlen(gh.id);
          gdrag = { id: gh.id, vorher: clone(stand.gebaeude), moved: false, x: e.clientX, y: e.clientY };
          surface.setPointerCapture(e.pointerId);
          return;
        }
      }
      if (panMode(e)) {
        drag = { x: e.clientX, y: e.clientY, moved: false };
        moving = true;
        surface.setPointerCapture(e.pointerId);
        surface.classList.add("is-ziehen");
      } else if (e.pointerType === "touch") {
        pendingTouch = { clientX: e.clientX, clientY: e.clientY, shiftKey: false };
      } else if (e.button === 0) {
        e.preventDefault();
        startStroke(e);
      }
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
      if (gdrag) {
        if (Math.abs(e.clientX - gdrag.x) + Math.abs(e.clientY - gdrag.y) > 3) gdrag.moved = true;
        if (gdrag.moved) {
          var gg = gebaeudeById(gdrag.id), pm = toMap(e.clientX, e.clientY);
          if (gg) { gg.x = Math.round(pm.x * 10) / 10; gg.y = Math.round(pm.y * 10) / 10; detailsNeu(); }
        }
        return;
      }
      if (drag) {
        var k = view.w / surface.clientWidth, dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        setView(view.x + view.w / 2 - dx * k, view.y + view.h / 2 - dy * k, view.w);
        drag.x = e.clientX; drag.y = e.clientY;
        return;
      }
      if (pendingTouch && Math.hypot(e.clientX - pendingTouch.clientX, e.clientY - pendingTouch.clientY) > 10) {
        var start = pendingTouch;
        pendingTouch = null;
        startStroke(start);
      }
      if (stroke) { if (e.buttons === 0) endStroke(); else continueStroke(e); return; }
      if (e.pointerType !== "touch") { hoverLater(e); gebaeudeHover(e); }
    });
    function up(e) {
      if (pendingTouch && e.type === "pointerup") { startStroke(pendingTouch); hover(regionAt(pendingTouch)); }  // Antippen weist zu
      pendingTouch = null;
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      if (gdrag) {
        var gs = gdrag; gdrag = null;
        if (gs.moved) { var st = newStep(); st.gVorher = gs.vorher; st.gNachher = clone(stand.gebaeude); commit(st); }
        endStroke(); return;
      }
      if (drag && !drag.moved && EDIT && tool === "gebaeude" && e.button === 0 && e.type === "pointerup") gebaeudeSetzen(toMap(e.clientX, e.clientY));
      if (drag && !drag.moved && !EDIT && e.button !== 1) { var gi = gebaeudeAn(toMap(e.clientX, e.clientY)); if (gi) { gebaeudeInfo(gi); drag = null; surface.classList.remove("is-ziehen"); if (moving && !Object.keys(pointers).length) { moving = false; redraw(); } endStroke(); return; } }
      if (drag && !drag.moved && EDIT && tool === "hauptstadt" && e.button === 0 && e.type === "pointerup") hauptstadtSetzen(toMap(e.clientX, e.clientY));
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
    hilite.innerHTML = id ? '<path d="' + paths[id].getAttribute("d") + '"/>' : "";
    if (!id) { info.innerHTML = ""; info.classList.remove("is-sichtbar"); return; }
    var g = geo.gebiete[id], s = state(stand.gebiete[id]);
    info.innerHTML = '<strong>' + esc(gname(id)) + "</strong>" + (gname(id) !== g.n ? " (" + esc(T.today) + ": " + esc(g.n) + ")" : "") +
      " · " + esc(geo.laender[g.c] || g.c) + "<br>" +
      (s ? swatch(s, 12) + " " + esc(s.name) : esc(T.noState)) + " · " + fmt(g.a) + " km²";
    info.classList.add("is-sichtbar");
  }

  var searchIndex = {};
  function fillSearch() {
    var list = root.querySelector("#karte-gebiete");
    if (!list) return;
    var opts = [];
    Object.keys(geo.gebiete).forEach(function (k) {
      var g = geo.gebiete[k], land = " (" + (geo.laender[g.c] || g.c) + ")";
      [g.n].concat(stand.namen && stand.namen[k] ? [stand.namen[k]] : []).forEach(function (n) {
        searchIndex[n + land] = k;
        opts.push(n + land);
      });
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
           Object.keys(geo.gebiete).find(function (k) { return gname(k).toLowerCase() === low; }) ||
           Object.keys(geo.gebiete).find(function (k) { return geo.gebiete[k].n.toLowerCase().indexOf(low) === 0 || gname(k).toLowerCase().indexOf(low) === 0; });
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
      b.addEventListener("pointerenter", function (e) { if (!pinned && e.pointerType === "mouse") focusState(sid); });
      b.addEventListener("pointerleave", function (e) { if (!pinned && e.pointerType === "mouse") focusState(null); });
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
      var t = (p.titel || []).concat(p.aemter || []);
      return "<strong>" + esc(p.name) + "</strong>" + (t.length ? " <span class=\"karte-titel\">" + esc(t.join(" · ")) + "</span>" : "");
    }).join("<br>");
    if (r.art === "landesherr") return names || esc(T.vacant.replace("{f}", r.fraktion || s.name));
    // kein eigener Regent: der Souverän, vertreten durch den Kanzler
    var v = (r.vertreter || []).map(function (p) { return "<strong>" + esc(p.name) + "</strong>"; }).join(" " + esc(T.und) + " ");
    return (names || esc(T.noKanzler)) + (v ? '<br><span class="karte-hinweis">' + esc(T.vertreten) + " " + v + "</span>" : "");
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
    var html = '<span class="eyebrow">' + esc(geo.laender[g.c] || g.c) + " · " + esc(id) + '</span><h2 id="karte-gebiet-titel">' + esc(gname(id)) + "</h2>";
    if (s) html += '<p class="karte-gebiet-staat">' + swatch(s, 20) + " " + esc(s.name) + "</p>";
    else html += '<p class="karte-gebiet-staat">' + swatch(null, 20) + " " + esc(T.notReich) + "</p>";
    var rows = [];
    if (gname(id) !== g.n) rows.push(row(T.todayName, esc(g.n)));
    if (s) rows.push(row(T.regent, regentHtml(s, infoData.regenten[s.id])));
    if (s && s.hauptstadt) rows.push(row(T.capital, "<strong>" + esc(s.hauptstadt.name) + "</strong>"));
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
      html += '<h3 class="karte-gebiet-h">' + (infoData.regenten[s.id] && infoData.regenten[s.id].art === "reich" ? esc(T.reich) : esc(T.state) + ": " + esc(s.name)) + "</h3>" +
        '<table class="styles-table is-grid karte-gebiet-tabelle"><tbody>' +
        row(T.population, fmt(b) + " " + esc(T.inhabitants)) + row(T.area, fmt(a) + " km²") + row(T.regionCount, fmt(n)) +
        row(T.sharePop, pct(b, rb)) + row(T.shareArea, pct(a, ra)) + "</tbody></table>";
    }
    if (s) html += renameHtml(id, s, infoData.regenten[s.id]);
    var yl = Object.keys(years).sort();
    if (yl.length) html += '<p class="karte-quelle">' + esc(T.source.replace("{j}", yl[yl.length - 1])) + "</p>";
    infoDlg.querySelector("[data-gebiet-inhalt]").innerHTML = html;
    bindRename(id, s);
    if (!infoDlg.open) infoDlg.showModal();
  }

  // Namensänderung: nur für den Regenten des Teilstaats (Prüfung auch auf dem Server)
  function day(ts) { return new Date(ts * 1000).toLocaleDateString(document.documentElement.lang === "en" ? "en-GB" : "de-DE"); }
  function renameHtml(id, s, r) {
    var ich = infoData.ich;
    if (ich && ich.kanzler && !cfg.version) {
      // Kanzler: Namen unmittelbar festlegen (statt Antrag)
      return '<h3 class="karte-gebiet-h">' + esc(T.renameH) + "</h3><p>" + esc(T.kanzlerIntro) + "</p>" +
        '<form class="form karte-antrag" data-kname><div class="field"><label for="kn-name">' + esc(T.nameField) + '</label>' +
        '<input id="kn-name" maxlength="80" value="' + esc(gname(id)) + '"></div><div data-kname-meldung></div>' +
        '<div class="dialog-actions"><button class="btn btn-navy btn-small" type="submit">' + esc(T.setName) + "</button>" +
        (gname(id) !== geo.gebiete[id].n ? '<button class="btn btn-line btn-small" type="button" data-kreset>' + esc(T.resetName) + "</button>" : "") +
        "</div></form>";
    }
    if (!ich) {
      if (infoData.angemeldet || !r || r.art !== "landesherr" || cfg.version) return "";
      return '<p class="karte-quelle">' + esc(T.loginHint) + ' <a href="' + esc(cfg.anmelden) + '">' + esc(T.login) + "</a></p>";
    }
    if (ich.regent_von.indexOf(s.id) < 0) return "";
    var a = ich.antraege[id], status = "", offen = a && a.status === "offen";
    if (a) {
      var key = { offen: "pending", angenommen: "accepted", abgelehnt: "rejected" }[a.status];
      status = '<div class="form-status ' + (a.status === "abgelehnt" ? "err" : "ok") + '" role="status">' + esc(T[key].replace("{d}", day(a.zeit)).replace("{n}", a.neu)) +
        (a.status === "abgelehnt" && a.antwort ? "<br>" + esc(T.answer) + ": " + esc(a.antwort) : "") + "</div>";
    }
    var form = offen ? "" :
      '<p>' + esc(T.renameIntro) + '</p><button type="button" class="btn btn-line btn-small" data-antrag-oeffnen>' + esc(T.renameBtn) + "</button>" +
      '<form class="form karte-antrag" data-antrag hidden>' +
      '<div class="field"><label for="ka-neu">' + esc(T.newName) + '</label><input id="ka-neu" maxlength="80" required value="' + esc(gname(id)) + '"></div>' +
      '<div class="field"><label for="ka-grund">' + esc(T.reason) + '</label><textarea id="ka-grund" rows="4" maxlength="1000" required></textarea></div>' +
      '<div data-antrag-meldung></div><button class="btn btn-navy btn-small" type="submit">' + esc(T.send) + "</button></form>";
    return '<h3 class="karte-gebiet-h">' + esc(T.renameH) + "</h3>" + status + form;
  }
  function bindKanzler(id) {
    var form = infoDlg.querySelector("[data-kname]");
    if (!form) return;
    function send(name) {
      var box = form.querySelector("[data-kname-meldung]");
      fetch(cfg.gebietsname, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf: cfg.csrf, gebiet: id, name: name }) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) throw j;
          stand.namen = j.namen;
          fillSearch();
          hoverId = null;
          showInfo(id);
          infoDlg.querySelector("[data-kname-meldung]").innerHTML = '<div class="form-status ok" role="status">' + esc(T.nameSaved) + "</div>";
        })
        .catch(function () { box.innerHTML = '<div class="form-status err" role="status">' + esc(T.saveError) + "</div>"; });
    }
    form.addEventListener("submit", function (e) { e.preventDefault(); send(form.querySelector("#kn-name").value); });
    var reset = form.querySelector("[data-kreset]");
    if (reset) reset.addEventListener("click", function () { send(""); });
  }
  function bindRename(id, s) {
    bindKanzler(id);
    var open = infoDlg.querySelector("[data-antrag-oeffnen]"), form = infoDlg.querySelector("[data-antrag]");
    if (!open || !form) return;
    open.addEventListener("click", function () { open.hidden = true; form.hidden = false; form.querySelector("#ka-neu").select(); });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = form.querySelector("button[type=submit]"), box = form.querySelector("[data-antrag-meldung]");
      btn.disabled = true;
      fetch(cfg.antrag, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf: cfg.csrf, gebiet: id, neu: form.querySelector("#ka-neu").value, begruendung: form.querySelector("#ka-grund").value }) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) { box.innerHTML = '<div class="form-status err" role="status">' + esc(j.fehler || T.saveError) + "</div>"; btn.disabled = false; return; }
          infoData.ich.antraege[id] = j.antrag;
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
      else if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey && { m: "malen", p: "pipette", h: "hauptstadt", g: "gebaeude", v: "verschieben" }[e.key.toLowerCase()]) {
        setTool({ m: "malen", p: "pipette", h: "hauptstadt", g: "gebaeude", v: "verschieben" }[e.key.toLowerCase()]);
      }
      else if (e.key === " " && (document.activeElement === surface || document.activeElement === document.body)) { e.preventDefault(); spaceDown = true; surface.classList.add("is-verschieben"); }
    });
    document.addEventListener("keyup", function (e) { if (e.key === " ") { spaceDown = false; surface.classList.toggle("is-verschieben", tool === "verschieben"); } });
    bindGebaeude();
    bindDialog();
    updateStatus();
    setupMobile();
  }

  // ---------- Handy: Vollbild-Editor, Leiste unten, Seitenleiste als Blatt ----------
  var mobile = window.matchMedia("(max-width: 900px)"), bar = null;
  function setupMobile() {
    bar = document.createElement("div");
    bar.className = "karte-mobilleiste";
    bar.innerHTML = '<button type="button" class="karte-chip" data-m="staaten" aria-label="' + esc(T.chooseState) + '"></button>' +
      '<button type="button" class="btn btn-line btn-small" data-m="werkzeug"></button>' +
      '<button type="button" class="btn btn-line btn-small" data-m="undo" aria-label="' + esc(T.undo) + '">↶</button>' +
      '<button type="button" class="btn btn-navy btn-small" data-m="speichern">' + esc(T.save) + "</button>";
    root.appendChild(bar);
    var head = document.createElement("div");
    head.className = "karte-blatt-kopf";
    head.innerHTML = '<strong>' + esc(T.more) + '</strong><button type="button" class="btn btn-navy btn-small" data-m="zu">' + esc(T.sheetClose) + "</button>";
    side.insertBefore(head, side.firstChild);
    bar.querySelector('[data-m="staaten"]').addEventListener("click", function () { openSheet(list.previousElementSibling); });
    bar.querySelector('[data-m="werkzeug"]').addEventListener("click", function () { setTool(tool === "verschieben" ? "malen" : "verschieben"); });
    bar.querySelector('[data-m="undo"]').addEventListener("click", doUndo);
    bar.querySelector('[data-m="speichern"]').addEventListener("click", function () { openSheet(noteInput.closest(".aside-box")); });
    head.querySelector('[data-m="zu"]').addEventListener("click", closeSheet);
    function apply() {
      var on = mobile.matches;
      root.classList.toggle("is-mobil", on);
      side.classList.toggle("karte-blatt", on);
      document.documentElement.classList.toggle("karte-vollbild", on);
      if (!on) closeSheet();
      requestAnimationFrame(function () { fit(Object.keys(stand.gebiete)); });
    }
    mobile.addEventListener("change", apply);
    apply();
    updateBar();
  }
  function openSheet(target) {
    side.classList.add("is-offen");
    if (target) target.scrollIntoView({ block: "start" });
  }
  function closeSheet() { side.classList.remove("is-offen"); }
  function updateBar() {
    if (!bar) return;
    var s = state(active), d = dirty().n;
    bar.querySelector('[data-m="staaten"]').innerHTML = swatch(s, 22) + "<span>" + esc(s ? s.name : T.unassigned) + "</span>";
    var w = bar.querySelector('[data-m="werkzeug"]');
    w.textContent = tool === "verschieben" ? T.toolPan : tool === "pipette" ? T.toolPick : tool === "hauptstadt" ? T.toolCapital : tool === "gebaeude" ? T.toolBuilding : T.toolPaint;
    w.setAttribute("aria-pressed", String(tool !== "verschieben"));
    bar.querySelector('[data-m="undo"]').disabled = !undo.length;
    bar.querySelector('[data-m="speichern"]').textContent = T.save + (d ? " (" + d + ")" : "");
  }

  function setTool(t) {
    tool = t;
    side.querySelectorAll("[data-werkzeug]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-werkzeug") === t)); });
    surface.classList.toggle("is-verschieben", t === "verschieben" || t === "hauptstadt" || t === "gebaeude");
    surface.classList.toggle("is-pipette", t === "pipette");
    surface.classList.toggle("is-gebaeude", t === "gebaeude");
    var hin = side.querySelector("[data-hinweis]");
    if (hin && T.hints) hin.textContent = T.hints[t] || "";
    var sb = side.querySelector('[data-block="staaten"]'), gb = side.querySelector('[data-block="gebaeude"]');
    if (sb) sb.hidden = t === "gebaeude";   // je Werkzeug nur der passende Abschnitt
    if (gb) gb.hidden = t !== "gebaeude";
    if (t !== "gebaeude") gsel = null;
    updateBar();
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
      b.addEventListener("click", function () {
        active = b.getAttribute("data-waehlen") || null;
        if (tool !== "malen") setTool("malen");
        renderStates();
        if (root.classList.contains("is-mobil")) { focusState(null); closeSheet(); }  // Handy: nach der Wahl zurück zur Karte
      });
      var sid = b.getAttribute("data-waehlen");
      if (sid) {
        // nur mit der Maus: Touch-Geräte lösen kein „Verlassen“ aus, die Karte bliebe abgedunkelt
        b.addEventListener("pointerenter", function (e) { if (e.pointerType === "mouse") focusState(sid); });
        b.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") focusState(null); });
      }
    });
    list.querySelectorAll("[data-bearbeiten]").forEach(function (b) {
      b.addEventListener("click", function () { openDialog(state(b.getAttribute("data-bearbeiten"))); });
    });
    updateBar();
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
    if (!Object.keys(step.gebiete).length && !step.nachher && !step.gNachher) return;
    undo.push(step);
    if (undo.length > 200) undo.shift();
    redo = [];
    after();
  }
  function after() {
    renderStates();
    renderGebaeude();
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
    if (step.gNachher) { stand.gebaeude = clone(back ? step.gVorher : step.gNachher); if (gsel && !gebaeudeById(gsel)) gsel = null; detailsNeu(); }
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
    (function () {   // Gebäude: neue, geänderte und entfernte zählen
      var alt = {}, neu = {};
      (saved.gebaeude || []).forEach(function (g) { alt[g.id] = JSON.stringify(g); });
      (stand.gebaeude || []).forEach(function (g) { neu[g.id] = JSON.stringify(g); if (alt[g.id] !== neu[g.id]) n++; });
      Object.keys(alt).forEach(function (id) { if (!(id in neu)) n++; });
    })();
    return { n: n };
  }
  function updateStatus() {
    var d = dirty().n;
    side.querySelector("[data-stand]").textContent = d ? T.changes.replace("{n}", d) : T.noChanges;
    saveBtn.disabled = !d;
    side.querySelector('[data-aktion="undo"]').disabled = !undo.length;
    side.querySelector('[data-aktion="redo"]').disabled = !redo.length;
    updateBar();
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

  // ---------- Behördengebäude: Hover, Liste in der Ansicht ----------
  function gebaeudeSichtbar() { return stufe() >= 4 && !root.classList.contains("ohne-behoerden"); }
  function gebaeudeHover(e) {
    var an = gebaeudeSichtbar() && !drag && !gdrag && (stand.gebaeude || []).length ? gebaeudeAn(toMap(e.clientX, e.clientY)) : null;
    surface.classList.toggle("is-ueber-geb", !!an);
  }
  function gebaeudeZeigen(g, info) {
    var w = Math.min(view.w, Math.max(30, (base || view).w / 45));
    setView(g.x, g.y, w);
    redraw();
    if (info) gebaeudeInfo(g);
  }
  function gebaeudeListe() {
    // Ansicht: Verzeichnis aller Gebäude in der Seitenleiste (Klick zoomt heran und öffnet die Angaben); ?typ=<Typ> springt zum Gebäude dieses Typs
    var nav = document.querySelector("[data-gebaeude-nav]"), ul = nav && nav.querySelector("[data-gebaeude-liste]");
    var arr = (stand.gebaeude || []).slice().sort(function (a, b) { return typName(a.typ).localeCompare(typName(b.typ), "de") || a.name.localeCompare(b.name, "de"); });
    if (nav && ul && arr.length) {
      nav.hidden = false;
      ul.innerHTML = arr.map(function (g) {
        return '<li><button type="button" class="karte-legende-item ed-geb" data-geb="' + g.id + '"><span class="ed-geb-pkt t' + typIndex(g.typ) + '"></span><span class="ed-geb-t"><b>' + esc(g.name) + "</b><small>" + esc(typName(g.typ)) + "</small></span></button></li>";
      }).join("");
      ul.querySelectorAll("[data-geb]").forEach(function (b) {
        b.addEventListener("click", function () { var g = gebaeudeById(b.getAttribute("data-geb")); if (g) gebaeudeZeigen(g, true); });
      });
    }
    var q = /[?&]typ=([a-z0-9_-]+)/.exec(location.search);
    if (q) { var hit = arr.filter(function (g) { return g.typ === q[1]; })[0]; if (hit) setTimeout(function () { gebaeudeZeigen(hit, true); }, 400); }
  }

  // ---------- Behördengebäude: Setzen, Bearbeiten, Liste ----------
  var gf = null;
  function bindGebaeude() {
    gf = { form: side.querySelector("[data-g-form]"), typ: side.querySelector("[data-g-typ]"), name: side.querySelector("[data-g-name]"), text: side.querySelector("[data-g-text]"),
           liste: side.querySelector("[data-g-liste]"), leer: side.querySelector("[data-g-leer]"), zahl: side.querySelector("[data-g-zahl]"), del: side.querySelector("[data-g-loeschen]") };
    function geaendert() {
      var g = gebaeudeById(gsel);
      if (!g) return;
      var name = gf.name.value.trim();
      if (!name) { gf.name.value = g.name; return; }
      var step = newStep();
      step.gVorher = clone(stand.gebaeude);
      g.typ = gf.typ.value; g.name = name; g.text = gf.text.value.trim();
      step.gNachher = clone(stand.gebaeude);
      detailsNeu();
      commit(step);
    }
    [gf.typ, gf.name, gf.text].forEach(function (el) { el.addEventListener("change", geaendert); });
    gf.del.addEventListener("click", function () {
      var g = gebaeudeById(gsel);
      if (!g || !confirm(T.buildingDelete + ": " + g.name + "?")) return;
      var step = newStep();
      step.gVorher = clone(stand.gebaeude);
      stand.gebaeude = stand.gebaeude.filter(function (x) { return x.id !== g.id; });
      step.gNachher = clone(stand.gebaeude);
      gsel = null;
      detailsNeu();
      commit(step);
    });
    renderGebaeude();
  }
  function gebaeudeWaehlen(id) {
    gsel = id;
    renderGebaeude();
    detailsNeu();
  }
  function gebaeudeSetzen(p) {
    var typ = gf.typ.value || (typen()[0] || {}).id || "behoerde";
    var max = stand.gebaeude.reduce(function (m, x) { return Math.max(m, parseInt(x.id.slice(1), 10) || 0); }, 0);
    var g = { id: "b" + (max + 1), typ: typ, name: typName(typ), text: "", x: Math.round(p.x * 10) / 10, y: Math.round(p.y * 10) / 10 };
    var step = newStep();
    step.gVorher = clone(stand.gebaeude);
    stand.gebaeude.push(g);
    step.gNachher = clone(stand.gebaeude);
    gsel = g.id;
    detailsNeu();
    commit(step);
    gf.name.focus(); gf.name.select();
  }
  function renderGebaeude() {
    if (!gf) return;
    var arr = (stand.gebaeude || []).slice().sort(function (a, b) { return typName(a.typ).localeCompare(typName(b.typ), "de") || a.name.localeCompare(b.name, "de"); });
    gf.zahl.textContent = arr.length ? "(" + arr.length + ")" : "";
    var g = gebaeudeById(gsel);
    gf.form.hidden = !g;
    if (g) { gf.typ.value = g.typ; gf.name.value = g.name; gf.text.value = g.text || ""; }
    gf.leer.textContent = !arr.length ? T.buildingNone : !g ? T.buildingPick : "";
    gf.liste.innerHTML = arr.map(function (x) {
      return '<li><button type="button" class="ed-geb' + (x.id === gsel ? " gew" : "") + '" data-geb="' + x.id + '" aria-pressed="' + (x.id === gsel) + '"><span class="ed-geb-pkt t' + typIndex(x.typ) + '"></span>' +
        '<span class="ed-geb-t"><b>' + esc(x.name) + "</b><small>" + esc(typName(x.typ)) + "</small></span></button></li>";
    }).join("");
    gf.liste.querySelectorAll("[data-geb]").forEach(function (b) {
      b.addEventListener("click", function () {
        var x = gebaeudeById(b.getAttribute("data-geb"));
        gebaeudeWaehlen(x.id);
        var w = Math.min(view.w, Math.max(30, (base || view).w / 45));   // heranzoomen, damit Symbol und Name sichtbar sind
        setView(x.x, x.y, w);
        redraw();
        if (root.classList.contains("is-mobil")) closeSheet();
      });
    });
  }
  function gebaeudeInfo(g) {
    // Ansicht: Angaben zum Gebäude im vorhandenen Fenster
    if (!infoDlg) infoDlg = document.querySelector("[data-gebiet]");
    if (!infoDlg) return;
    var c = infoDlg.querySelector("[data-gebiet-inhalt]");
    var ty = typ(g.typ);
    c.innerHTML = '<h2 id="karte-gebiet-titel">' + esc(g.name) + '</h2><p class="eyebrow">' + esc(typName(g.typ)) + (ty && ty.gruppeName ? " · " + esc(ty.gruppeName) : "") + "</p>" + (g.text ? "<p>" + esc(g.text) + "</p>" : "") +
      (ty && ty.seite ? '<p><a class="btn btn-navy" href="' + esc(ty.seite) + '">' + esc(T.buildingPage || "Zur Seite") + "</a></p>" : "");
    infoDlg.showModal();
  }

  // ---------- Hauptstädte ----------
  function ortSuchen(name, sid) {
    // exakter Ortsname (ohne Groß-/Kleinschreibung); bei mehreren Treffern der innerhalb der Gebiete des Teilstaats
    var low = name.toLowerCase(), treffer = (geo.orte || []).filter(function (o) { return o[0].toLowerCase() === low; });
    if (treffer.length < 2) return treffer[0] || null;
    var ids = Object.keys(stand.gebiete).filter(function (k) { return stand.gebiete[k] === sid; });
    return treffer.filter(function (o) {
      return ids.some(function (k) { var b = geo.gebiete[k].b; return o[1] >= b[0] && o[1] <= b[2] && o[2] >= b[1] && o[2] <= b[3]; });
    })[0] || treffer[0];
  }
  function hauptstadtSetzenAn(t, name) {
    name = (name || "").trim();
    if (!name) { delete t.hauptstadt; return; }
    if (t.hauptstadt && t.hauptstadt.name === name) return;
    var o = ortSuchen(name, t.id);
    if (o) { t.hauptstadt = { name: name, x: o[1], y: o[2] }; return; }
    if (t.hauptstadt) { t.hauptstadt.name = name; return; }   // nur umbenannt
    var c = komponenten().filter(function (k) { return k.staat === t.id; })[0];   // sonst Mitte des größten zusammenhängenden Teils
    if (c) t.hauptstadt = { name: name, x: Math.round(c.x * 10) / 10, y: Math.round(c.y * 10) / 10 };
  }
  function hauptstadtSetzen(p) {
    var s = state(active);
    if (!s) return;
    var name = s.hauptstadt ? s.hauptstadt.name : "";
    if (!name) {
      var nah = null, bd = 16 * (base || view).w / Math.max(1, surface.clientWidth);
      (geo.orte || []).forEach(function (o) { var d = Math.hypot(o[1] - p.x, o[2] - p.y); if (d < bd) { bd = d; nah = o; } });
      name = (window.prompt(T.capitalPrompt.replace("{state}", s.name), nah ? nah[0] : "") || "").trim();
      if (!name) return;
    }
    var step = newStep();
    step.vorher = clone(stand.staaten);
    s.hauptstadt = { name: name, x: Math.round(p.x * 10) / 10, y: Math.round(p.y * 10) / 10 };
    step.nachher = clone(stand.staaten);
    detailsNeu();
    commit(step);
  }

  // ---------- Dialog: Teilstaat anlegen / bearbeiten ----------
  var dlg, editing = null;
  function bindDialog() {
    dlg = document.querySelector("[data-dialog]");
    var f = { name: dlg.querySelector("#ks-name"), farbe: dlg.querySelector("#ks-farbe"), muster: dlg.querySelector("#ks-muster"), farbe2: dlg.querySelector("#ks-farbe2"), fraktion: dlg.querySelector("#ks-fraktion"), hauptstadt: dlg.querySelector("#ks-hauptstadt") };
    var namen = {};
    (geo.orte || []).forEach(function (o) { namen[o[0]] = 1; });
    dlg.querySelector("#ks-orte").innerHTML = Object.keys(namen).sort(function (a, b) { return a.localeCompare(b, "de"); }).map(function (n) { return '<option value="' + esc(n) + '">'; }).join("");
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
        hauptstadtSetzenAn(t, f.hauptstadt.value);
      } else {
        var max = stand.staaten.reduce(function (m, x) { return Math.max(m, parseInt(x.id.slice(1), 10) || 0); }, 0);
        s.id = "s" + (max + 1);
        stand.staaten.push(s);
        hauptstadtSetzenAn(s, f.hauptstadt.value);
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
    f.hauptstadt.value = s && s.hauptstadt ? s.hauptstadt.name : "";
    if (f.fraktion.value !== (s ? s.fraktion || "" : "")) f.fraktion.value = "";  // Rolle existiert nicht mehr
    dlg.querySelector("[data-dialog-fehler]").hidden = true;
    dlg.querySelector('[data-aktion="loeschen"]').hidden = !s;
    dlg.preview();
    dlg.returnValue = "";
    dlg.showModal();
    f.name.focus();
  }
})();
