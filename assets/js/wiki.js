/* Wiki: Suchvorschläge, kleine Helfer und der Editor (Werkzeugleiste, Link- und Bilddialog,
   Live-Vorschau, Entwurf sichern). Ohne JavaScript bleibt alles bedienbar. */
(function () {
  "use strict";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  function debounce(fn, ms) { var t; return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); }; }
  function getJSON(url) { return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }); }

  /* ---------- Suchvorschläge (Seitentitel) ---------- */
  $$("input[data-suggest]").forEach(function (input) {
    var list = document.getElementById(input.getAttribute("list"));
    if (!list) return;
    input.addEventListener("input", debounce(function () {
      var q = input.value.trim();
      if (q.length < 2) { list.innerHTML = ""; return; }
      getJSON(input.dataset.suggest + "?q=" + encodeURIComponent(q)).then(function (titles) {
        list.innerHTML = "";
        titles.forEach(function (t) { var o = document.createElement("option"); o.value = t; list.appendChild(o); });
      }).catch(function () {});
    }, 150));
  });

  /* ---------- Kleine Helfer ---------- */
  $$("[data-select-all]").forEach(function (el) { el.addEventListener("focus", function () { el.select(); }); });
  $$("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (ev) { if (!window.confirm(el.dataset.confirm)) ev.preventDefault(); });
  });

  /* ---------- Editor ---------- */
  var cfgEl = document.getElementById("wiki-cfg");
  var form = $("form.wiki-edit");
  if (!cfgEl || !form) return;
  var cfg = JSON.parse(cfgEl.textContent);
  var T = cfg.i18n;
  var ta = form.querySelector("textarea[name=text]");
  var toolbar = $(".wiki-toolbar", form);
  if (toolbar) toolbar.hidden = false;

  function sel() { return { s: ta.selectionStart, e: ta.selectionEnd, v: ta.value }; }
  // Einfügen über execCommand, damit Strg+Z weiter funktioniert; sonst direkt setzen
  function put(text, selStart, selEnd) {
    ta.focus();
    var c = sel(), done = false;
    try { done = document.execCommand("insertText", false, text); } catch (e) { done = false; }
    if (!done) {
      ta.value = c.v.slice(0, c.s) + text + c.v.slice(c.e);
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (selStart != null) ta.setSelectionRange(c.s + selStart, c.s + selEnd);
    else ta.setSelectionRange(c.s + text.length, c.s + text.length);
  }
  function surround(before, after, placeholder) {
    var c = sel();
    var chosen = c.v.slice(c.s, c.e) || placeholder;
    put(before + chosen + after, before.length, before.length + chosen.length);
  }
  function prefixLines(prefix, placeholder) {
    var c = sel();
    var start = c.v.lastIndexOf("\n", c.s - 1) + 1;
    ta.setSelectionRange(start, c.e);
    var block = c.v.slice(start, c.e) || placeholder;
    put(block.split("\n").map(function (l) { return prefix + l; }).join("\n"));
  }
  function block(text) {
    var c = sel();
    var before = c.v.slice(0, c.s);
    var lead = !before ? "" : before.slice(-2) === "\n\n" ? "" : before.slice(-1) === "\n" ? "\n" : "\n\n";
    put(lead + text + "\n");
  }

  var actions = {
    bold: function () { surround("'''", "'''", T.bold); },
    italic: function () { surround("''", "''", T.italic); },
    h2: function () { block("== " + T.heading + " =="); },
    ul: function () { prefixLines("* ", T.item); },
    category: function () { block("[[Kategorie:" + T.category + "]]"); },
    table: function () { block("{|\n! " + T.col1 + " !! " + T.col2 + "\n|-\n| " + T.cell + " || " + T.cell + "\n|}"); },
    infobox: function () { block("{{Infobox " + T.infoTitle + "\n| Bild = Datei.png|" + T.caption + "\n| " + T.field + " = " + T.value + "\n}}"); },
    link: openLink,
    image: openImage
  };
  if (toolbar) toolbar.addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-act]");
    if (b && actions[b.dataset.act]) { ev.preventDefault(); actions[b.dataset.act](); }
  });
  ta.addEventListener("keydown", function (ev) {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey) return;
    var k = ev.key.toLowerCase();
    if (k === "b") { ev.preventDefault(); actions.bold(); }
    else if (k === "i") { ev.preventDefault(); actions.italic(); }
    else if (k === "k") { ev.preventDefault(); actions.link(); }
  });

  function showModal(d) { if (d.showModal) d.showModal(); else d.setAttribute("open", ""); }

  /* Link */
  var dlgLink = $("#dlg-link"), dlTarget = $("#dl-target"), dlLabel = $("#dl-label"), dlList = $("#dl-list");
  function openLink() {
    var c = sel();
    dlLabel.value = c.v.slice(c.s, c.e);
    dlTarget.value = "";
    dlgLink.returnValue = "";
    dlgLink.onclose = function () {
      if (dlgLink.returnValue !== "ok") { ta.focus(); return; }
      var t = dlTarget.value.trim(), l = dlLabel.value.trim();
      if (!t) { ta.focus(); return; }
      if (/^https?:\/\//i.test(t)) put("[" + t + (l ? " " + l : "") + "]");
      else put("[[" + t + (l && l !== t ? "|" + l : "") + "]]");
    };
    showModal(dlgLink);
    dlTarget.focus();
  }
  dlTarget.addEventListener("input", debounce(function () {
    var q = dlTarget.value.trim();
    if (!q || /^https?:/i.test(q)) { dlList.innerHTML = ""; return; }
    getJSON(cfg.suggest + "?q=" + encodeURIComponent(q)).then(function (list) {
      dlList.innerHTML = "";
      list.forEach(function (t) { var o = document.createElement("option"); o.value = t; dlList.appendChild(o); });
    }).catch(function () {});
  }, 150));

  /* Bild */
  var dlgImg = $("#dlg-img"), grid = $(".di-grid", dlgImg), search = $(".di-search", dlgImg), status = $(".di-status", dlgImg);
  var okBtn = $("button[value=ok]", dlgImg), tabs = $$("[data-tab]", dlgImg);
  var chosen = null, activeTab = "pick";
  function setStatus(msg) { status.textContent = msg || ""; status.hidden = !msg; }
  function setTab(name) {
    activeTab = name;
    tabs.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.tab === name)); });
    $$("[data-pane]", dlgImg).forEach(function (p) { p.hidden = p.dataset.pane !== name; });
    setStatus("");
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { setTab(b.dataset.tab); }); });
  function loadImages() {
    getJSON(cfg.suggest + "?typ=datei&q=" + encodeURIComponent(search.value.trim())).then(function (list) {
      grid.innerHTML = "";
      if (!list.length) { var p = document.createElement("p"); p.className = "form-note"; p.textContent = T.none; grid.appendChild(p); return; }
      list.forEach(function (f) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "doc-card"; b.setAttribute("role", "option"); b.setAttribute("aria-selected", "false");
        b.innerHTML = '<span class="sheet contain"><img alt="" loading="lazy"></span><span class="meta"><span></span></span>';
        b.querySelector("img").src = f.url;
        b.querySelector(".meta span").textContent = f.name;
        b.addEventListener("click", function () {
          chosen = f.name;
          $$(".doc-card", grid).forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); });
        });
        b.addEventListener("dblclick", function () { chosen = f.name; okBtn.click(); });
        grid.appendChild(b);
      });
    }).catch(function () {});
  }
  search.addEventListener("input", debounce(loadImages, 200));
  search.addEventListener("keydown", function (ev) { if (ev.key === "Enter") ev.preventDefault(); });

  function uploadFile(file, name) {
    var fd = new FormData();
    fd.append("csrf", cfg.csrf);
    fd.append("name", name || "");
    fd.append("beschreibung", "");
    fd.append("recht", "1");
    fd.append("datei", file);
    return fetch(cfg.upload, { method: "POST", body: fd, credentials: "same-origin" }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok || !j.ok) throw new Error(j.error || T.uploadFail); return j; });
    });
  }
  function imgSyntax(name) {
    var al = $("#di-align").value;
    var w = Math.max(60, Math.min(1200, parseInt($("#di-width").value, 10) || 300));
    var cap = $("#di-cap").value.trim().replace(/\|/g, "/");
    return "[[Datei:" + name + "|mini|" + al + "|" + w + "px" + (cap ? "|" + cap : "") + "]]";
  }
  function insertImage(name) {
    dlgImg.close("done");
    block(imgSyntax(name));
  }
  okBtn.addEventListener("click", function (ev) {
    ev.preventDefault();
    if (activeTab === "pick") {
      if (!chosen) { setStatus(T.pickFirst); return; }
      insertImage(chosen);
      return;
    }
    var f = $("#di-file").files[0];
    if (!f) { setStatus(T.pickFirst); return; }
    if (!$("#di-rights").checked) { setStatus(T.rights); return; }
    setStatus("");
    okBtn.disabled = true;
    okBtn.textContent = T.uploading;
    uploadFile(f, $("#di-name").value.trim() || f.name)
      .then(function (j) { insertImage(j.name); })
      .catch(function (e) { setStatus(e.message); })
      .then(function () { okBtn.disabled = false; okBtn.textContent = okBtn.dataset.orig; });
  });
  okBtn.dataset.orig = okBtn.textContent;
  dlgImg.addEventListener("close", function () { ta.focus(); });
  function openImage() {
    chosen = null;
    setTab("pick");
    $("#di-file").value = ""; $("#di-name").value = ""; $("#di-rights").checked = false; $("#di-cap").value = "";
    search.value = "";
    loadImages();
    showModal(dlgImg);
    search.focus();
  }

  /* Bilder per Einfügen oder Ziehen ins Textfeld hochladen */
  function handleFiles(files) {
    var f = Array.prototype.find.call(files || [], function (x) { return /^image\/(png|jpeg|gif|webp)$/.test(x.type); });
    if (!f) return false;
    var name = f.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(f.name) ? f.name
      : "Bild " + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + "." + f.type.split("/")[1].replace("jpeg", "jpg");
    uploadFile(f, name).then(function (j) { block("[[Datei:" + j.name + "|mini|rechts|300px]]"); })
      .catch(function (e) { window.alert(e.message); });
    return true;
  }
  ta.addEventListener("paste", function (ev) { if (handleFiles(ev.clipboardData && ev.clipboardData.files)) ev.preventDefault(); });
  ta.addEventListener("drop", function (ev) { if (handleFiles(ev.dataTransfer && ev.dataTransfer.files)) ev.preventDefault(); });
  ta.addEventListener("dragover", function (ev) {
    if (ev.dataTransfer && Array.prototype.some.call(ev.dataTransfer.items || [], function (i) { return i.kind === "file"; })) ev.preventDefault();
  });

  /* Live-Vorschau ohne Neuladen */
  var live = $("#wiki-live");
  var previewBtn = form.querySelector("button[value=vorschau]");
  if (previewBtn && live) previewBtn.addEventListener("click", function (ev) {
    ev.preventDefault();
    var body = $(".live-body", live);
    live.hidden = false;
    body.textContent = T.previewing;
    var fd = new URLSearchParams();
    fd.set("csrf", cfg.csrf);
    fd.set("text", ta.value);
    fetch(cfg.preview, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (j) { body.innerHTML = j.html; live.scrollIntoView({ block: "start" }); })
      .catch(function () { body.textContent = T.previewFail; });
  });

  /* Entwurf im Browser sichern, Warnung bei ungespeicherten Änderungen */
  var original = ta.value, submitting = false;
  var bar = $("#wiki-draft");
  function store(fn) { try { return fn(window.localStorage); } catch (e) { return null; } }
  var saved = store(function (ls) { return ls.getItem(cfg.draftKey); });
  if (saved && saved !== original && bar) {
    bar.hidden = false;
    $("p", bar).textContent = T.draft;
    $("[data-draft=restore]", bar).textContent = T.restore;
    $("[data-draft=discard]", bar).textContent = T.discard;
    bar.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-draft]");
      if (!b) return;
      if (b.dataset.draft === "restore") ta.value = saved;
      else store(function (ls) { ls.removeItem(cfg.draftKey); });
      bar.hidden = true;
      ta.focus();
    });
  }
  ta.addEventListener("input", debounce(function () {
    store(function (ls) { if (ta.value !== original) ls.setItem(cfg.draftKey, ta.value); else ls.removeItem(cfg.draftKey); });
  }, 800));
  form.addEventListener("submit", function (ev) {
    if (ev.submitter && ev.submitter.value === "speichern") { submitting = true; store(function (ls) { ls.removeItem(cfg.draftKey); }); }
    else submitting = true;
  });
  window.addEventListener("beforeunload", function (ev) {
    if (!submitting && ta.value !== original) { ev.preventDefault(); ev.returnValue = T.unsaved; return T.unsaved; }
  });
})();
