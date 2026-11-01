/* Imperium Germanicum – Neugestaltung (Testfassung): Navigation, Bewegung, Reichskarte, Staatsaufbau, Archiv.
   Ohne Abhängigkeiten; ergänzt assets/js/site.js (Farbschema, Lightbox, Charta, Formulare). */
(function () {
  "use strict";

  var doc = document.documentElement;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var EN = doc.getAttribute("lang") === "en";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var T = EN
    ? { menu: "Menu", close: "Close", all: "Overview", area: "Area", pop: "Population", districts: "Districts", ruler: "Sovereign",
        none: "No sovereign at present", chancellor: "responsible, as it belongs to no constituent state", loadfail: "The interactive map could not be loaded." }
    : { menu: "Menü", close: "Schließen", all: "Gesamtansicht", area: "Fläche", pop: "Bevölkerung", districts: "Bezirke", ruler: "Landesherr",
        none: "Derzeit ohne Landesherrn", chancellor: "zuständig, da keinem Teilstaat zugehörig", loadfail: "Die interaktive Karte konnte nicht geladen werden." };
  var nf = new Intl.NumberFormat(EN ? "en-GB" : "de-DE");

  /* ---------- Mega-Menü Institutionen ---------- */

  var header = $("[data-header]");
  var megaBtn = $(".tg-nav__toggle");
  var mega = $("#tg-mega");
  if (megaBtn && mega) {
    mega.hidden = false;
    var closeTimer;
    var setMega = function (open) {
      clearTimeout(closeTimer);
      mega.classList.toggle("is-open", open);
      header.classList.toggle("mega-open", open);
      megaBtn.setAttribute("aria-expanded", String(open));
    };
    var hoverAt = 0;
    megaBtn.addEventListener("click", function () {
      // direkt nach dem Öffnen per Hover nicht gleich wieder schließen
      if (Date.now() - hoverAt < 500) return;
      setMega(megaBtn.getAttribute("aria-expanded") !== "true");
    });
    if (window.matchMedia("(hover: hover)").matches) {
      [megaBtn, mega].forEach(function (el) {
        el.addEventListener("mouseenter", function () { if (megaBtn.getAttribute("aria-expanded") !== "true") hoverAt = Date.now(); setMega(true); });
        el.addEventListener("mouseleave", function () { closeTimer = setTimeout(function () { setMega(false); }, 180); });
      });
    }
    document.addEventListener("click", function (e) { if (!header.contains(e.target)) setMega(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && megaBtn.getAttribute("aria-expanded") === "true") { setMega(false); megaBtn.focus(); }
    });
    mega.addEventListener("focusout", function (e) { if (!header.contains(e.relatedTarget)) setMega(false); });
  }

  /* ---------- Mobiles Vollbildmenü ---------- */

  var burger = $(".tg-burger");
  var menu = $("#tg-menu");
  if (burger && menu) {
    menu.hidden = false;
    var label = $(".tg-burger__label", burger);
    var setMenu = function (open) {
      menu.classList.toggle("is-open", open);
      document.body.classList.toggle("menu-is-open", open);
      burger.setAttribute("aria-expanded", String(open));
      label.textContent = open ? T.close : T.menu;
      if ("inert" in menu) menu.inert = !open;
      if (open) { var first = $("a, summary", menu); if (first) setTimeout(function () { first.focus({ preventScroll: true }); }, 350); }
    };
    if ("inert" in menu) menu.inert = true;
    burger.addEventListener("click", function () { setMenu(!menu.classList.contains("is-open")); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menu.classList.contains("is-open")) { setMenu(false); burger.focus(); }
    });
    window.addEventListener("resize", function () { if (window.innerWidth > 1180 && menu.classList.contains("is-open")) setMenu(false); });
    // zweiter Farbschema-Knopf im Menü schaltet über den ersten (site.js)
    $$("[data-theme-alt]").forEach(function (b) {
      b.addEventListener("click", function (e) { e.stopImmediatePropagation(); var main = $(".tg-tools .theme-toggle"); if (main) main.click(); });
    });
  }

  /* ---------- Einblenden, Bildmasken, Überschriften ---------- */

  var targets = $$("[data-reveal], [data-mask], .tg-hero, .tg-display");
  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.01 });
    targets.forEach(function (el) { io.observe(el); });
  } else {
    targets.forEach(function (el) { el.classList.add("is-in"); });
  }

  /* ---------- Zurückhaltende Parallaxe ---------- */

  var px = reduce ? [] : $$("[data-parallax]");
  if (px.length) {
    var ticking = false;
    var update = function () {
      ticking = false;
      var vh = window.innerHeight;
      px.forEach(function (el) {
        var r = el.parentNode.getBoundingClientRect();
        if (r.bottom < 0 || r.top > vh) return;
        var p = (r.top + r.height / 2 - vh / 2) / vh; // -1 … 1
        el.style.transform = "translate3d(0," + (p * -5).toFixed(2) + "%,0) scale(1.1)";
      });
    };
    window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  /* ---------- Zähler ---------- */

  var counters = $$("[data-count]");
  if (counters.length && "IntersectionObserver" in window && !reduce) {
    var run = function (el) {
      var end = parseInt(el.getAttribute("data-count"), 10), t0 = null, dur = 1600;
      var step = function (t) {
        if (!t0) t0 = t;
        var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 4);
        el.textContent = nf.format(Math.round(end * e));
        if (k < 1) requestAnimationFrame(step); else el.textContent = nf.format(end);
      };
      requestAnimationFrame(step);
    };
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { run(en.target); cio.unobserve(en.target); } });
    }, { threshold: 0.6 });
    counters.forEach(function (el) { cio.observe(el); });
  }

  /* ---------- Staatsaufbau (Reiter) ---------- */

  $$(".tg-org").forEach(function (root) {
    var tabs = $$("[data-org]", root);
    var select = function (tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        var p = document.getElementById(t.getAttribute("aria-controls"));
        if (on) p.removeAttribute("data-hidden"); else p.setAttribute("data-hidden", "");
      });
      if (focus) tab.focus();
      if (window.innerWidth <= 1000) {
        var panel = document.getElementById(tab.getAttribute("aria-controls"));
        var top = panel.getBoundingClientRect().top;
        if (top > window.innerHeight * .8) panel.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      }
    };
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(t, false); });
      t.addEventListener("keydown", function (e) {
        var k = e.key, j = -1;
        if (k === "ArrowRight" || k === "ArrowDown") j = (i + 1) % tabs.length;
        else if (k === "ArrowLeft" || k === "ArrowUp") j = (i - 1 + tabs.length) % tabs.length;
        else if (k === "Home") j = 0;
        else if (k === "End") j = tabs.length - 1;
        if (j >= 0) { e.preventDefault(); select(tabs[j], true); }
      });
    });
  });

  /* ---------- Archiv der Erlasse: Suche und Filter ---------- */

  $$("[data-archive]").forEach(function (root) {
    var items = $$("[data-archive-item]", root), chips = $$("[data-archive-filter]", root);
    var input = $("[data-archive-search]", root), count = $("[data-archive-count]", root), empty = $("[data-archive-empty]", root);
    var filter = "alle";
    var apply = function () {
      var q = (input.value || "").trim().toLowerCase(), n = 0;
      items.forEach(function (it) {
        var ok = (filter === "alle" || it.getAttribute("data-issuer-name") === filter) && (!q || it.getAttribute("data-search").indexOf(q) !== -1);
        it.hidden = !ok;
        if (ok) n++;
      });
      count.textContent = n;
      empty.hidden = n > 0;
    };
    chips.forEach(function (c) {
      c.addEventListener("click", function () {
        filter = c.getAttribute("data-archive-filter");
        chips.forEach(function (x) { x.setAttribute("aria-pressed", String(x === c)); });
        apply();
      });
    });
    input.addEventListener("input", apply);
  });

  /* ---------- Reichskarte (Daten live aus dem Webdienst /karte/) ---------- */

  var SVGNS = "http://www.w3.org/2000/svg";
  $$("[data-map]").forEach(function (fig) {
    var stage = $("[data-map-stage]", fig), section = fig.closest(".tg-mapsec");
    var panel = $("[data-map-panel]", section), list = $("[data-map-list]", section), reset = $("[data-map-reset]", fig);
    var started = false;
    var start = function () {
      if (started) return;
      started = true;
      var bar = document.createElement("div");
      bar.className = "tg-map__loading";
      stage.appendChild(bar);
      var get = function (url) { return fetch(url, { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw r; return r.json(); }); };
      Promise.all([get(fig.getAttribute("data-geo")), get(fig.getAttribute("data-daten")),
                   get(fig.getAttribute("data-info")).catch(function () { return {}; })])
        .then(function (res) { build(res[0], res[1], res[2]); })
        .catch(function () {
          bar.remove();
          var p = document.createElement("p");
          p.className = "tg-note";
          p.textContent = T.loadfail;
          panel.appendChild(p);
        });
    };
    if ("IntersectionObserver" in window) {
      var mio = new IntersectionObserver(function (en) { if (en[0].isIntersecting) { start(); mio.disconnect(); } }, { rootMargin: "600px 0px" });
      mio.observe(fig);
    } else start();

    function build(geo, daten, info) {
      var staaten = daten.staaten || [], zu = daten.gebiete || {}, namen = daten.namen || {};
      var bev = info.bev || {}, reg = info.regenten || {};
      var byState = {};
      staaten.forEach(function (s) { byState[s.id] = { s: s, d: [], area: 0, pop: 0, n: 0 }; });
      var rest = [];
      Object.keys(geo.gebiete).forEach(function (gid) {
        var g = geo.gebiete[gid], sid = zu[gid], st = sid && byState[sid];
        if (st) {
          st.d.push(g.d); st.area += g.a || 0; st.n++;
          if (bev[gid]) st.pop += bev[gid][0];
        } else rest.push(g.d);
      });
      var states = staaten.map(function (s) { return byState[s.id]; }).filter(function (x) { return x.n > 0; });

      var svg = document.createElementNS(SVGNS, "svg");
      svg.setAttribute("role", "group");
      svg.setAttribute("aria-label", EN ? "Map of the constituent states" : "Karte der Teilstaaten");
      var gLand = document.createElementNS(SVGNS, "g");
      var land = document.createElementNS(SVGNS, "path");
      land.setAttribute("class", "land");
      land.setAttribute("d", (geo.hintergrund || []).join(" ") + " " + rest.join(" "));
      gLand.appendChild(land);
      svg.appendChild(gLand);
      var gStates = document.createElementNS(SVGNS, "g");
      svg.appendChild(gStates);
      states.forEach(function (st, i) {
        var p = document.createElementNS(SVGNS, "path");
        p.setAttribute("d", st.d.join(" "));
        p.setAttribute("class", "staat t" + (i % 6));
        p.setAttribute("tabindex", "0");
        p.setAttribute("role", "button");
        p.setAttribute("aria-label", st.s.name);
        st.el = p;
        gStates.appendChild(p);
      });
      svg.setAttribute("viewBox", "0 0 " + geo.breite + " " + geo.hoehe);
      stage.innerHTML = "";
      stage.appendChild(svg);

      // Ausschnitt: Reichsgebiet mit Rand, an das Seitenverhältnis der Bühne angepasst
      var pad = function (b, k) {
        var w = b.width, h = b.height, ar = stage.clientWidth / Math.max(1, stage.clientHeight);
        var cx = b.x + w / 2, cy = b.y + h / 2;
        w *= k; h *= k;
        if (w / h > ar) h = w / ar; else w = h * ar;
        return [cx - w / 2, cy - h / 2, w, h];
      };
      var home = pad(gStates.getBBox(), 1.08);
      states.forEach(function (st) { st.box = st.el.getBBox(); });
      var vb = home.slice(), anim = null;
      var setVB = function (v) { svg.setAttribute("viewBox", v.map(function (x) { return x.toFixed(1); }).join(" ")); };
      setVB(vb);
      var fly = function (to) {
        if (anim) cancelAnimationFrame(anim);
        if (reduce) { vb = to.slice(); setVB(vb); return; }
        var from = vb.slice(), t0 = null, dur = 700;
        var step = function (t) {
          if (!t0) t0 = t;
          var k = Math.min(1, (t - t0) / dur), e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
          vb = from.map(function (f, i) { return f + (to[i] - f) * e; });
          setVB(vb);
          if (k < 1) anim = requestAnimationFrame(step);
        };
        anim = requestAnimationFrame(step);
      };
      window.addEventListener("resize", function () { home = pad(gStates.getBBox(), 1.08); if (!active) { vb = home.slice(); setVB(vb); } });

      // Liste
      list.innerHTML = "";
      var sorted = states.slice().sort(function (a, b) { return a.s.name.localeCompare(b.s.name, "de"); });
      sorted.forEach(function (st) {
        var li = document.createElement("li"), b = document.createElement("button");
        b.type = "button";
        b.setAttribute("aria-pressed", "false");
        b.innerHTML = "<span></span><small></small>";
        b.firstChild.textContent = st.s.name;
        b.lastChild.textContent = nf.format(Math.round(st.area)) + " km²";
        st.btn = b;
        li.appendChild(b);
        list.appendChild(li);
      });

      var active = null;
      var hover = function (st, on) {
        fig.classList.toggle("has-focus", on || !!active);
        states.forEach(function (x) { x.el.classList.toggle("is-hover", on && x === st); x.btn.classList.toggle("is-hover", on && x === st); });
      };
      var regentText = function (sid) {
        var r = reg[sid];
        if (!r || !r.personen || !r.personen.length) return T.none;
        var names = r.personen.map(function (p) { return (p.titel && p.titel.length ? p.titel.join(", ") + " · " : "") + p.name; }).join("; ");
        return r.art === "kanzler" ? names + " – " + T.chancellor : names;
      };
      var esc = function (t) { var d = document.createElement("div"); d.textContent = t; return d.innerHTML; };
      var select = function (st) {
        active = st;
        states.forEach(function (x) {
          x.el.classList.toggle("is-active", x === st);
          x.btn.setAttribute("aria-pressed", String(x === st));
        });
        fig.classList.toggle("has-focus", !!st);
        reset.hidden = !st;
        if (!st) { fly(home); return; }
        fly(pad(st.box, 1.5));
        var rows = [[T.ruler, regentText(st.s.id)], [T.area, nf.format(Math.round(st.area)) + " km²"]];
        if (st.pop) rows.push([T.pop, nf.format(st.pop)]);
        rows.push([T.districts, nf.format(st.n)]);
        panel.innerHTML = '<p class="tg-org__panel-art">' + (EN ? "Constituent state" : "Teilstaat") + "</p><h3>" + esc(st.s.name) + '</h3><dl class="tg-dl">' +
          rows.map(function (r) { return "<div><dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd></div>"; }).join("") + "</dl>";
      };
      states.forEach(function (st) {
        [st.el, st.btn].forEach(function (el) {
          el.addEventListener("mouseenter", function () { hover(st, true); });
          el.addEventListener("mouseleave", function () { hover(st, false); });
          el.addEventListener("focus", function () { hover(st, true); });
          el.addEventListener("blur", function () { hover(st, false); });
          el.addEventListener("click", function () { select(active === st ? null : st); });
        });
        st.el.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(active === st ? null : st); }
        });
      });
      reset.addEventListener("click", function () { select(null); });
      reset.textContent = T.all;
      void namen;
    }
  });

  /* ---------- Seitenwechsel (sanftes Ausblenden bei internen Links) ---------- */

  if (!reduce) {
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a[href]");
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (a.target === "_blank" || a.hasAttribute("download") || a.hasAttribute("data-lightbox")) return;
      var url = new URL(a.href, location.href);
      if (url.origin !== location.origin || url.pathname.indexOf("/testseite1/") !== 0) return;
      if (url.pathname === location.pathname && url.hash) return;
      e.preventDefault();
      document.body.classList.add("is-leaving");
      setTimeout(function () { location.href = url.href; }, 260);
    });
    window.addEventListener("pageshow", function () { document.body.classList.remove("is-leaving"); });
  }
})();
