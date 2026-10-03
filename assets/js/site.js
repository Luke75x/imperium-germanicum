/* Imperium Germanicum – Seitenlogik (ohne Abhängigkeiten) */
(function () {
  "use strict";

  var doc = document.documentElement;
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ---------- Kopfbereich & mobiles Menü ---------- */

  var header = $(".site-header");
  var menuBtn = $(".menu-button");
  var onScroll = function () {
    document.body.classList.toggle("is-scrolled", window.scrollY > 38);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  if (menuBtn) {
    menuBtn.addEventListener("click", function () {
      var open = document.body.classList.toggle("menu-open");
      menuBtn.setAttribute("aria-expanded", String(open));
      menuBtn.querySelector(".menu-label").textContent = open ? "Schließen" : "Menü";
    });
  }

  $$(".nav-toggle-sub").forEach(function (btn) {
    var li = btn.closest(".has-sub");
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = li.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
    });
  });
  document.addEventListener("click", function (e) {
    $$(".has-sub.open").forEach(function (li) {
      if (!li.contains(e.target)) {
        li.classList.remove("open");
        li.querySelector(".nav-toggle-sub").setAttribute("aria-expanded", "false");
      }
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    $$(".has-sub.open").forEach(function (li) {
      li.classList.remove("open");
      var b = li.querySelector(".nav-toggle-sub");
      b.setAttribute("aria-expanded", "false");
      b.focus();
    });
    if (document.body.classList.contains("menu-open") && menuBtn) menuBtn.click();
  });

  /* ---------- Einblenden beim Scrollen ---------- */

  var reveals = $$(".reveal");
  if ("IntersectionObserver" in window && reveals.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- Lightbox ---------- */

  var links = $$("[data-lightbox]");
  if (links.length) {
    var box = document.createElement("div");
    box.className = "lightbox";
    box.hidden = true;
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", "Bildansicht");
    box.innerHTML =
      '<div class="lb-bar"><span class="lb-count" aria-live="polite"></span>' +
      '<div class="lb-tools"><a class="lb-orig" href="#" target="_blank" rel="noopener">Original öffnen</a>' +
      '<button class="lb-btn lb-close" type="button" aria-label="Schließen"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 3l10 10M13 3L3 13"/></svg></button></div></div>' +
      '<div class="lb-stage"><button class="lb-btn lb-prev" type="button" aria-label="Vorheriges Bild"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3L5 8l5 5"/></svg></button>' +
      '<img alt="">' +
      '<button class="lb-btn lb-next" type="button" aria-label="Nächstes Bild"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3l5 5-5 5"/></svg></button></div>' +
      '<div class="lb-caption"></div>';
    document.body.appendChild(box);

    var lbImg = $("img", box), lbCap = $(".lb-caption", box), lbCount = $(".lb-count", box), lbOrig = $(".lb-orig", box);
    var prevBtn = $(".lb-prev", box), nextBtn = $(".lb-next", box);
    var group = [], index = 0, opener = null;

    var visible = function (el) { return el.offsetParent !== null; };

    var show = function (i) {
      index = (i + group.length) % group.length;
      var a = group[index];
      lbImg.src = a.getAttribute("data-full") || a.href;
      var cap = a.getAttribute("data-caption") || "";
      lbImg.alt = cap;
      lbCap.textContent = cap;
      lbOrig.href = a.href;
      lbCount.textContent = group.length > 1 ? (index + 1) + " / " + group.length : "";
      prevBtn.hidden = nextBtn.hidden = group.length < 2;
    };

    var open = function (a) {
      var name = a.getAttribute("data-gallery");
      group = name ? links.filter(function (l) { return l.getAttribute("data-gallery") === name && visible(l); }) : [a];
      if (!group.length) group = [a];
      opener = a;
      show(group.indexOf(a));
      box.hidden = false;
      doc.style.overflow = "hidden";
      $(".lb-close", box).focus();
    };

    var close = function () {
      box.hidden = true;
      lbImg.removeAttribute("src");
      doc.style.overflow = "";
      if (opener) opener.focus();
    };

    links.forEach(function (a) {
      a.addEventListener("click", function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        open(a);
      });
    });
    $(".lb-close", box).addEventListener("click", close);
    prevBtn.addEventListener("click", function () { show(index - 1); });
    nextBtn.addEventListener("click", function () { show(index + 1); });
    box.addEventListener("click", function (e) {
      if (e.target === box || e.target.classList.contains("lb-stage")) close();
    });
    document.addEventListener("keydown", function (e) {
      if (box.hidden) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") show(index - 1);
      else if (e.key === "ArrowRight") show(index + 1);
      else if (e.key === "Tab") {
        var f = $$("button:not([hidden]), a[href]", box);
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    var touchX = null;
    box.addEventListener("touchstart", function (e) { touchX = e.touches[0].clientX; }, { passive: true });
    box.addEventListener("touchend", function (e) {
      if (touchX === null) return;
      var dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 50) show(index + (dx < 0 ? 1 : -1));
      touchX = null;
    });
  }

  /* ---------- Charta: Inhaltsverzeichnis, Lesefortschritt, Druck ---------- */

  var progress = $(".progress");
  var article = $("[data-progress]");
  if (article && progress) {
    var tocLinks = $$(".toc a");
    var sections = tocLinks.map(function (a) { return $(a.getAttribute("href")); });
    var tick = function () {
      var r = article.getBoundingClientRect();
      var total = r.height - window.innerHeight;
      var p = total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 1;
      progress.style.transform = "scaleX(" + p + ")";
      var active = 0;
      sections.forEach(function (s, i) { if (s && s.getBoundingClientRect().top < 160) active = i; });
      tocLinks.forEach(function (a, i) { a.classList.toggle("active", i === active); });
    };
    window.addEventListener("scroll", tick, { passive: true });
    window.addEventListener("resize", tick);
    tick();
  }
  $$("[data-print]").forEach(function (b) { b.addEventListener("click", function () { window.print(); }); });

  /* ---------- Filter (Etiketten-Guide & Erlasse) ---------- */

  var guideSearch = $("[data-guide-search]");
  var guideTabs = $$("[data-filter]");
  if (guideTabs.length) {
    var groups = $$("[data-group]");
    var noResults = $("[data-no-results]");
    var current = "alle";
    var applyGuide = function () {
      var q = (guideSearch && guideSearch.value || "").trim().toLowerCase();
      var hits = 0;
      groups.forEach(function (g) {
        var inCat = current === "alle" || g.getAttribute("data-group") === current;
        var cards = $$(".title-card", g);
        if (!cards.length) { g.hidden = !inCat || q !== ""; return; }
        var any = false;
        cards.forEach(function (c) {
          var match = !q || c.getAttribute("data-search").indexOf(q) !== -1;
          c.hidden = !match;
          if (match) any = true;
        });
        g.hidden = !inCat || !any;
        if (!g.hidden) hits++;
      });
      if (noResults) noResults.hidden = hits > 0;
    };
    guideTabs.forEach(function (b) {
      b.addEventListener("click", function () {
        current = b.getAttribute("data-filter");
        guideTabs.forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        applyGuide();
      });
    });
    if (guideSearch) guideSearch.addEventListener("input", applyGuide);
  }

  var docTabs = $$("[data-doc-filter]");
  if (docTabs.length) {
    var docs = $$("[data-issuer]");
    docTabs.forEach(function (b) {
      b.addEventListener("click", function () {
        var f = b.getAttribute("data-doc-filter");
        docTabs.forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        docs.forEach(function (d) { d.hidden = f !== "alle" && d.getAttribute("data-issuer") !== f; });
      });
    });
  }

  /* ---------- Formulare ---------- */

  $$("[data-ts]").forEach(function (i) { i.value = String(Math.floor(Date.now() / 1000)); });

  var messages = {
    valueMissing: "Bitte fülle dieses Feld aus.",
    typeMismatch: "Bitte gib eine gültige E-Mail-Adresse ein."
  };

  var validate = function (form) {
    var ok = true;
    $$("input[required], textarea[required], input[type=email]", form).forEach(function (el) {
      var field = el.closest(".field");
      if (!field) return;
      var err = $(".error", field);
      if (err) err.remove();
      field.classList.remove("invalid");
      el.removeAttribute("aria-invalid");
      if (el.value.trim() === "" && el.required) el.value = "";
      if (!el.checkValidity()) {
        ok = false;
        field.classList.add("invalid");
        el.setAttribute("aria-invalid", "true");
        var msg = document.createElement("span");
        msg.className = "error";
        msg.id = el.id + "-error";
        msg.textContent = el.validity.valueMissing ? messages.valueMissing : messages.typeMismatch;
        el.setAttribute("aria-describedby", msg.id);
        field.appendChild(msg);
      }
    });
    return ok;
  };

  $$("[data-ajax-form]").forEach(function (form) {
    var status = $(".form-status", form);
    var btn = $("button[type=submit]", form);
    var setStatus = function (kind, text) {
      status.hidden = false;
      status.className = "form-status " + kind;
      status.textContent = text;
    };
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!validate(form)) {
        var first = $(".invalid input, .invalid textarea", form);
        if (first) first.focus();
        return;
      }
      if (!window.fetch) { form.submit(); return; }
      btn.disabled = true;
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { "Accept": "application/json" }
      })
        .then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
        .then(function (res) {
          if (res.ok) {
            form.reset();
            setStatus("ok", res.message || "Vielen Dank! Deine Nachricht wurde gesendet.");
            $$("[data-ts]", form).forEach(function (i) { i.value = String(Math.floor(Date.now() / 1000)); });
          } else {
            setStatus("err", res.message || "Die Nachricht konnte nicht gesendet werden. Bitte schreibe uns direkt per E-Mail.");
          }
        })
        .catch(function () {
          setStatus("err", "Die Verbindung ist fehlgeschlagen. Bitte versuche es erneut oder schreibe uns direkt per E-Mail.");
        })
        .then(function () { btn.disabled = false; });
    });
  });

  var params = new URLSearchParams(window.location.search);
  if (params.has("fehler")) {
    var st = $("[data-ajax-form] .form-status");
    if (st) {
      st.hidden = false;
      st.className = "form-status err";
      st.textContent = "Die Nachricht konnte nicht gesendet werden. Bitte prüfe deine Eingaben oder schreibe uns direkt per E-Mail.";
    }
  }
})();
