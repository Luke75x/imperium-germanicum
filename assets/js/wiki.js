/* Wiki-Editor: Werkzeugleiste, Link- und Bilddialog, Live-Vorschau, Entwurf sichern.
   Ohne JavaScript bleibt das Formular voll nutzbar (nur die Leiste fehlt). */
(function () {
  "use strict";
  var cfgEl = document.getElementById("wiki-cfg");
  var form = document.querySelector("form.wiki-edit");
  if (!cfgEl || !form) return;
  var cfg = JSON.parse(cfgEl.textContent);
  var T = cfg.i18n;
  var ta = form.querySelector("textarea[name=text]");
  var toolbar = form.querySelector(".wiki-toolbar");
  if (toolbar) toolbar.hidden = false;

  /* ---------- Text einfügen ---------- */
  function sel() { return { s: ta.selectionStart, e: ta.selectionEnd, v: ta.value }; }
  function put(text, selStart, selEnd) {
    ta.focus();
    var done = false;
    try { done = document.execCommand("insertText", false, text); } catch (e) { done = false; }
    if (!done) {
      var c = sel();
      ta.value = c.v.slice(0, c.s) + text + c.v.slice(c.e);
      ta.selectionStart = ta.selectionEnd = c.s + text.length;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (selStart != null) {
      var base = ta.selectionStart - text.length;
      ta.setSelectionRange(base + selStart, base + selEnd);
    }
  }
  function surround(before, after, placeholder) {
    var c = sel();
    var chosen = c.v.slice(c.s, c.e) || placeholder;
    put(before + chosen + after, before.length, before.length + chosen.length);
  }
  function prefixLines(prefix, placeholder) {
    var c = sel();
    var start = c.v.lastIndexOf("\n", c.s - 1) + 1;
    var end = c.e;
    var block = c.v.slice(start, end) || placeholder;
    ta.setSelectionRange(start, end);
    var out = block.split("\n").map(function (l) { return prefix + l.replace(/^([*#>]\s|={2,4}.*=)/, "$1"); }).join("\n");
    put((start > 0 && c.v[start - 1] !== "\n" ? "\n" : "") + out);
  }
  function block(text) {
    var c = sel();
    var lead = c.s > 0 && c.v[c.s - 1] !== "\n" ? "\n\n" : (c.s > 0 && c.v.slice(c.s - 2, c.s) !== "\n\n" ? "\n" : "");
    put(lead + text + "\n");
  }

  var actions = {
    bold: function () { surround("'''", "'''", T.bold); },
    italic: function () { surround("''", "''", T.italic); },
    h2: function () { surround("== ", " ==", T.heading); },
    h3: function () { surround("=== ", " ===", T.heading); },
    ul: function () { prefixLines("* ", T.item); },
    ol: function () { prefixLines("# ", T.item); },
    quote: function () { prefixLines("> ", T.quote); },
    category: function () { block("[[Kategorie:" + T.category + "]]"); },
    table: function () {
      block("{|\n! " + T.col1 + " !! " + T.col2 + "\n|-\n| " + T.cell + " || " + T.cell + "\n|-\n| " + T.cell + " || " + T.cell + "\n|}");
    },
    infobox: function () {
      block("{{Infobox " + T.infoTitle + "\n| Bild = Datei.png|" + T.caption + "\n| " + T.field + " = " + T.value + "\n}}");
    },
    link: openLink,
    image: openImage
  };
  if (toolbar) toolbar.addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-act]");
    if (b && actions[b.dataset.act]) { ev.preventDefault(); actions[b.dataset.act](); }
  });
  ta.addEventListener("keydown", function (ev) {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
    var k = ev.key.toLowerCase();
    if (k === "b") { ev.preventDefault(); actions.bold(); }
    else if (k === "i") { ev.preventDefault(); actions.italic(); }
    else if (k === "k") { ev.preventDefault(); actions.link(); }
  });

  /* ---------- Hilfsfunktionen ---------- */
  function debounce(fn, ms) { var t; return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); }; }
  function getJSON(url) { return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }); }
  function openDialog(d, onOk) {
    d.returnValue = "";
    d.onclose = function () { if (d.returnValue === "ok") onOk(); };
    if (d.showModal) d.showModal(); else d.setAttribute("open", "");
  }

  /* ---------- Link ---------- */
  var dlgLink = document.getElementById("dlg-link");
  var dlTarget = document.getElementById("dl-target");
  var dlLabel = document.getElementById("dl-label");
  var dlList = document.getElementById("dl-list");
  function openLink() {
    var c = sel();
    dlLabel.value = c.v.slice(c.s, c.e);
    dlTarget.value = "";
    openDialog(dlgLink, function () {
      var t = dlTarget.value.trim(), l = dlLabel.value.trim();
      if (!t) return;
      if (/^https?:\/\//i.test(t)) put("[" + t + (l ? " " + l : "") + "]");
      else put("[[" + t + (l && l !== t ? "|" + l : "") + "]]");
    });
    setTimeout(function () { dlTarget.focus(); }, 30);
  }
  if (dlTarget) dlTarget.addEventListener("input", debounce(function () {
    var q = dlTarget.value.trim();
    if (q.length < 1 || /^https?:/i.test(q)) { dlList.innerHTML = ""; return; }
    getJSON(cfg.suggest + "?q=" + encodeURIComponent(q)).then(function (list) {
      dlList.innerHTML = "";
      list.forEach(function (t) { var o = document.createElement("option"); o.value = t; dlList.appendChild(o); });
    });
  }, 150));

  /* ---------- Bild ---------- */
  var dlgImg = document.getElementById("dlg-img");
  var chosen = null;
  function uploadFile(file, name) {
    var fd = new FormData();
    fd.append("csrf", cfg.csrf);
    fd.append("name", name || "");
    fd.append("beschreibung", "");
    fd.append("recht", "1");
    fd.append("datei", file);
    return fetch(cfg.upload, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || T.uploadFail); return j; }); });
  }
  function imgSyntax(name) {
    var al = document.getElementById("di-align").value;
    var w = parseInt(document.getElementById("di-width").value, 10) || 300;
    var cap = document.getElementById("di-cap").value.trim().replace(/\|/g, "/");
    return "[[Datei:" + name + "|mini|" + al + "|" + w + "px" + (cap ? "|" + cap : "") + "]]";
  }
  if (dlgImg) {
    var grid = dlgImg.querySelector(".di-grid");
    var search = dlgImg.querySelector(".di-search");
    var status = dlgImg.querySelector(".di-status");
    var tabs = dlgImg.querySelectorAll("[data-tab]");
    var activeTab = "pick";
    function setTab(name) {
      activeTab = name;
      tabs.forEach(function (b) { b.setAttribute("aria-selected", b.dataset.tab === name ? "true" : "false"); });
      dlgImg.querySelectorAll("[data-pane]").forEach(function (p) { p.hidden = p.dataset.pane !== name; });
    }
    tabs.forEach(function (b) { b.addEventListener("click", function () { setTab(b.dataset.tab); }); });
    var load = function () {
      getJSON(cfg.suggest + "?typ=datei&q=" + encodeURIComponent(search.value.trim())).then(function (list) {
        grid.innerHTML = "";
        if (!list.length) { var li = document.createElement("li"); li.className = "none"; li.textContent = T.none; grid.appendChild(li); return; }
        list.forEach(function (f) {
          var li = document.createElement("li");
          var b = document.createElement("button");
          b.type = "button";
          var img = document.createElement("img"); img.src = f.url; img.alt = ""; img.loading = "lazy";
          var cap = document.createElement("span"); cap.textContent = f.name;
          b.appendChild(img); b.appendChild(cap);
          b.addEventListener("click", function () {
            chosen = f.name;
            grid.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
            b.classList.add("on");
          });
          li.appendChild(b); grid.appendChild(li);
        });
      });
    };
    search.addEventListener("input", debounce(load, 200));
    search.addEventListener("keydown", function (ev) { if (ev.key === "Enter") ev.preventDefault(); });
  }
  function openImage() {
    chosen = null;
    status.textContent = "";
    setTab("pick");
    document.getElementById("di-file").value = "";
    document.getElementById("di-name").value = "";
    document.getElementById("di-rights").checked = false;
    document.getElementById("di-cap").value = "";
    dlgImg.querySelector(".di-search").value = "";
    dlgImg.querySelector(".di-search").dispatchEvent(new Event("input"));
    // Der Dialog schließt sich bei „Einfügen“ nur, wenn alles bereit ist (Upload läuft vorher).
    var okBtn = dlgImg.querySelector("button[value=ok]");
    okBtn.onclick = function (ev) {
      ev.preventDefault();
      if (activeTab === "pick") {
        if (!chosen) { status.textContent = ""; alert(T.pickFirst); return; }
        finish(chosen);
        return;
      }
      var f = document.getElementById("di-file").files[0];
      if (!f) { alert(T.pickFirst); return; }
      if (!document.getElementById("di-rights").checked) { alert(T.rights); return; }
      status.textContent = T.uploading;
      okBtn.disabled = true;
      uploadFile(f, document.getElementById("di-name").value.trim() || f.name)
        .then(function (j) { okBtn.disabled = false; status.textContent = ""; finish(j.name); })
        .catch(function (e) { okBtn.disabled = false; status.textContent = e.message; });
    };
    function finish(name) {
      dlgImg.returnValue = "cancel";
      dlgImg.close();
      put(imgSyntax(name) + "\n");
    }
    dlgImg.onclose = null;
    if (dlgImg.showModal) dlgImg.showModal(); else dlgImg.setAttribute("open", "");
  }

  // Bilder per Einfügen/Ziehen in das Textfeld hochladen
  function handleFiles(files) {
    var f = Array.prototype.find.call(files || [], function (x) { return /^image\/(png|jpeg|gif|webp)$/.test(x.type); });
    if (!f) return false;
    var name = f.name && f.name !== "image.png" ? f.name : "Bild " + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".png";
    var live = document.getElementById("wiki-live");
    uploadFile(f, name).then(function (j) { put("[[Datei:" + j.name + "|mini|rechts|300px]]\n"); alert(T.pasteNote); })
      .catch(function (e) { alert(e.message); });
    return true;
  }
  ta.addEventListener("paste", function (ev) { if (handleFiles(ev.clipboardData && ev.clipboardData.files)) ev.preventDefault(); });
  ta.addEventListener("drop", function (ev) { if (handleFiles(ev.dataTransfer && ev.dataTransfer.files)) ev.preventDefault(); });
  ta.addEventListener("dragover", function (ev) { if (ev.dataTransfer && Array.prototype.some.call(ev.dataTransfer.items || [], function (i) { return i.kind === "file"; })) ev.preventDefault(); });

  /* ---------- Live-Vorschau ---------- */
  var live = document.getElementById("wiki-live");
  var previewBtn = form.querySelector("button[value=vorschau]");
  if (previewBtn && live) previewBtn.addEventListener("click", function (ev) {
    ev.preventDefault();
    var body = live.querySelector(".live-body");
    live.hidden = false;
    body.textContent = T.previewing;
    var fd = new URLSearchParams();
    fd.set("csrf", cfg.csrf);
    fd.set("text", ta.value);
    fetch(cfg.preview, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (j) { body.innerHTML = j.html; live.scrollIntoView({ behavior: "smooth", block: "start" }); })
      .catch(function () { body.textContent = T.previewFail; });
  });

  /* ---------- Entwurf und Warnung bei ungespeicherten Änderungen ---------- */
  var original = ta.value, submitting = false;
  var bar = document.getElementById("wiki-draft");
  function store(fn) { try { return fn(window.localStorage); } catch (e) { return null; } }
  var saved = store(function (ls) { return ls.getItem(cfg.draftKey); });
  if (saved && saved !== original && bar) {
    bar.hidden = false;
    bar.querySelector("span").textContent = T.draft;
    bar.querySelector("[data-draft=restore]").textContent = T.restore;
    bar.querySelector("[data-draft=discard]").textContent = T.discard;
    bar.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-draft]");
      if (!b) return;
      if (b.dataset.draft === "restore") { ta.value = saved; }
      else { store(function (ls) { ls.removeItem(cfg.draftKey); }); }
      bar.hidden = true;
    });
  }
  ta.addEventListener("input", debounce(function () {
    store(function (ls) { ta.value !== original ? ls.setItem(cfg.draftKey, ta.value) : ls.removeItem(cfg.draftKey); });
  }, 800));
  form.addEventListener("submit", function (ev) {
    var v = ev.submitter && ev.submitter.value;
    if (v === "speichern") { submitting = true; store(function (ls) { ls.removeItem(cfg.draftKey); }); }
  });
  window.addEventListener("beforeunload", function (ev) {
    if (!submitting && ta.value !== original) { ev.preventDefault(); ev.returnValue = T.unsaved; return T.unsaved; }
  });
})();
