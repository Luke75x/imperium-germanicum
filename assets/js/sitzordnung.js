/* Sitzordnung: Delegation per Hover/Fokus/Klick hervorheben, Info-Zeile, Legende verknüpft. Ohne JavaScript bleibt alles lesbar. */
(function () {
  var plan = document.querySelector('.sz-plan');
  if (!plan) return;
  var info = document.getElementById('sz-info');
  var en = (document.documentElement.lang || '').indexOf('en') === 0;
  var standard = info ? info.innerHTML : '';
  var gruppen = [].slice.call(plan.querySelectorAll('.dl, .bank'));
  var items = [].slice.call(document.querySelectorAll('.sz-legende li'));
  var fest = null;

  function an(g) {
    gruppen.forEach(function (x) { x.classList.toggle('an', x === g); });
    items.forEach(function (li) { li.classList.toggle('an', !!g && g.getAttribute('data-d') !== null && li.getAttribute('data-d') === g.getAttribute('data-d')); });
    plan.classList.toggle('fokus', !!g);
  }
  function zeige(g, kreis) {
    an(g);
    if (!info || !g) return;
    var name = g.getAttribute('aria-label') || (kreis && kreis.getAttribute('data-l')) || '';
    var l = kreis ? kreis.getAttribute('data-l') : name;
    info.innerHTML = '<b></b><br><span></span>';
    info.firstChild.textContent = name || l;
    if (l && name && l.indexOf(name + ': ') === 0) l = l.slice(name.length + 2);
    if (l && l.indexOf(name + ' · ') === 0) l = l.slice(name.length + 3);
    var bank = g.classList.contains('bank');
    info.lastChild.textContent = l && l !== name ? l : bank ? '' : (en ? 'Delegation of six seats (sovereign + five delegates)' : 'Delegation mit sechs Sitzen (Landesherr und fünf Delegierte)');
  }
  function aus() {
    if (fest) return zeige(fest, null);
    an(null);
    if (info) info.innerHTML = standard;
  }
  gruppen.forEach(function (g) {
    g.addEventListener('mouseover', function (e) { zeige(g, e.target.closest('circle, rect.sz')); });
    g.addEventListener('focus', function () { zeige(g, null); });
    g.addEventListener('mouseleave', aus);
    g.addEventListener('blur', aus);
    g.addEventListener('click', function () { fest = (fest === g) ? null : g; fest ? zeige(g, null) : aus(); });
  });
  items.forEach(function (li) {
    var d = li.getAttribute('data-d');
    var g = d !== null ? plan.querySelector('.dl[data-d="' + d + '"]') : null;
    if (!g) return;
    li.addEventListener('mouseenter', function () { zeige(g, null); });
    li.addEventListener('mouseleave', aus);
    li.addEventListener('click', function () { fest = (fest === g) ? null : g; fest ? zeige(g, null) : aus(); });
  });
})();
