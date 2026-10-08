
/* circoe.dashboard v2. Tout texte passe par textContent. Les boutons d'état (Fait, Tout fait, replier)
   n'écrivent pas en local : l'événement part, Core écrit, la mise à jour revient ; les nœuds sont
   conservés d'une mise à jour à l'autre, donc le repli s'anime et le focus reste. Une seule écriture en vol. */
var $ = function (id) { return document.getElementById(id); };
var sectionsEl = $('db-sections');
var emptyEl = $('db-empty');
var notice = $('db-notice');
var STATE = {item_done: 1, section_done: 1, section_toggled: 1};
var SENT = {
  item_remind: 'Rappel demandé.', item_postpone: 'Report demandé.', item_open: 'Ouverture demandée.',
  section_remind: 'Rappel de la section demandé.', section_postpone: 'Report de la section demandé.'
};
var LOST = {
  stale: 'Les données ont changé entre-temps : action non enregistrée.',
  rate_limited: 'Trop d’actions à la fois : réessayez.',
  failed: 'Jarvis est injoignable : action non enregistrée.',
  refused: 'Jarvis a refusé l’action.'
};
var sections = [];
var items = [];
var accent = '#6ee7ff';
var showDone = true;
var busy = false;
var busyTimer = null;
var noticeTimer = null;
var secNodes = {};
var firstPaint = true;

function copy(value) { return JSON.parse(JSON.stringify(value)); }

function say(text) {
  notice.textContent = text;
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(function () { noticeTimer = null; notice.textContent = ''; }, 4000);
}

function release() {
  busy = false;
  if (busyTimer !== null) clearTimeout(busyTimer);
  busyTimer = null;
  sectionsEl.removeAttribute('aria-busy');
}

function emit(name, payload) {
  if (STATE[name] && busy) { say('Action en cours, réessayez dans un instant.'); return; }
  try {
    jarvis.emit(name, payload);
  } catch (_error) {
    say(LOST.refused);
    return;
  }
  if (STATE[name]) {
    busy = true;
    sectionsEl.setAttribute('aria-busy', 'true');
    busyTimer = setTimeout(release, 3000);
  }
}

function settle(result) {
  if (!result) return;
  if (STATE[result.name]) release();
  if (result.outcome === 'applied') return;
  if (result.outcome === 'recorded') { if (SENT[result.name]) say(SENT[result.name]); return; }
  say(result.outcome === 'stale' ? LOST.stale : result.reason === 'rate_limited' ? LOST.rate_limited : result.outcome === 'failed' ? LOST.failed : LOST.refused);
}

function itemsIn(id) { return items.filter(function (item) { return item.section === id; }); }
function openCount(list) { return list.filter(function (item) { return item.done !== true; }).length; }
function setDone(ids, value) {
  var next = copy(items);
  next.forEach(function (item) { if (ids.indexOf(item.id) >= 0) item.done = value; });
  return next;
}

function actButton(kind, icon, label) {
  var b = cxEl('button', 'db-act');
  b.setAttribute('type', 'button');
  b.setAttribute('data-kind', kind);
  b.appendChild(cxIcon(icon));
  b.appendChild(cxEl('span', '', label));
  return b;
}

function buildItem() {
  var li = cxEl('li', 'db-item');
  var check = cxEl('button', 'db-check');
  check.setAttribute('type', 'button');
  check.appendChild(cxIcon('check'));
  var body = cxEl('div', 'db-body');
  var title = cxEl('span', 'db-item-title');
  var detail = cxEl('span', 'db-item-detail');
  var due = cxEl('span', 'cx-pill db-due');
  due.appendChild(cxIcon('clock'));
  var dueText = cxEl('span', 'cx-num');
  due.appendChild(dueText);
  body.appendChild(title); body.appendChild(detail); body.appendChild(due);
  var acts = cxEl('div', 'db-acts');
  acts.setAttribute('role', 'group');
  var remind = actButton('remind', 'bell', 'Rappeler');
  var postpone = actButton('postpone', 'cal', 'Reporter');
  var open = actButton('open', 'out', 'Ouvrir');
  acts.appendChild(remind); acts.appendChild(postpone); acts.appendChild(open);
  li.appendChild(check); li.appendChild(body); li.appendChild(acts);
  var n = {root: li, check: check, title: title, detail: detail, due: due, dueText: dueText, acts: acts,
    remind: remind, postpone: postpone, open: open, item: null, section: null};
  function ref() { return {section_id: n.section.id, item_id: n.item.id}; }
  check.addEventListener('click', function () {
    emit('item_done', {items: setDone([n.item.id], n.item.done !== true)});
  });
  remind.addEventListener('click', function () { emit('item_remind', ref()); });
  postpone.addEventListener('click', function () { emit('item_postpone', ref()); });
  open.addEventListener('click', function () { emit('item_open', ref()); });
  return n;
}

function paintItem(n, item, section, tone) {
  n.item = item; n.section = section;
  var done = item.done === true;
  n.root.style.setProperty('--acc', item.accent || tone);
  if (done) n.root.setAttribute('data-done', ''); else n.root.removeAttribute('data-done');
  n.title.textContent = item.title;
  n.detail.textContent = item.detail || '';
  n.detail.hidden = !item.detail;
  n.dueText.textContent = item.due || '';
  n.due.hidden = !item.due;
  n.check.setAttribute('aria-pressed', done ? 'true' : 'false');
  n.check.setAttribute('aria-label', (done ? 'Rouvrir : ' : 'Fait : ') + item.title);
  n.acts.setAttribute('aria-label', 'Actions : ' + item.title);
  n.remind.setAttribute('aria-label', 'Rappeler : ' + item.title);
  n.postpone.setAttribute('aria-label', 'Reporter : ' + item.title);
  n.open.setAttribute('aria-label', 'Ouvrir : ' + item.title);
}

function toolButton(label, primary) {
  var b = cxEl('button', 'cx-btn cx-btn-ghost', label);
  b.setAttribute('type', 'button');
  if (primary) b.setAttribute('data-primary', '');
  return b;
}

function buildSection(index) {
  var root = cxEl('section', 'db-sec cx-glass cx-rise');
  var head = cxEl('div', 'db-sec-head');
  var h = cxEl('h2', 'db-sec-h');
  var toggle = cxEl('button', 'db-toggle');
  toggle.setAttribute('type', 'button');
  toggle.setAttribute('aria-controls', 'db-panel-' + index);
  var chev = cxIcon('chev'); chev.setAttribute('class', 'cx-ico db-chev');
  var dot = cxEl('span', 'cx-dot'); dot.setAttribute('aria-hidden', 'true');
  var title = cxEl('span', 'db-sec-title');
  var meta = cxEl('span', 'db-sec-meta'); meta.setAttribute('aria-hidden', 'true');
  var count = cxEl('span', 'db-count', '0');
  meta.appendChild(count); meta.appendChild(cxEl('span', 'db-count-cap', 'à faire'));
  toggle.appendChild(chev); toggle.appendChild(dot); toggle.appendChild(title); toggle.appendChild(meta);
  h.appendChild(toggle);
  var tools = cxEl('div', 'db-sec-tools');
  tools.setAttribute('role', 'group');
  var allDone = toolButton('Tout fait', true);
  var remind = toolButton('Tout rappeler');
  var postpone = toolButton('Tout reporter');
  tools.appendChild(allDone); tools.appendChild(remind); tools.appendChild(postpone);
  head.appendChild(h);
  var prog = cxEl('div', 'db-prog'); prog.setAttribute('aria-hidden', 'true');
  var panel = cxEl('div', 'db-panel');
  panel.setAttribute('id', 'db-panel-' + index);
  var inner = cxEl('div', 'db-panel-in');
  var list = cxEl('ul', 'db-items');
  var none = cxEl('p', 'db-none');
  inner.appendChild(tools); inner.appendChild(list); inner.appendChild(none);
  panel.appendChild(inner);
  root.appendChild(head); root.appendChild(prog); root.appendChild(panel);
  var s = {root: root, toggle: toggle, title: title, count: count, tools: tools, allDone: allDone, remind: remind,
    postpone: postpone, prog: prog, panel: panel, list: list, none: none, rows: {}, section: null, expanded: true};
  toggle.addEventListener('click', function () {
    var next = copy(sections);
    for (var i = 0; i < next.length; i += 1) {
      if (next[i].id === s.section.id) next[i].collapsed = s.expanded;
    }
    emit('section_toggled', {sections: next});
  });
  allDone.addEventListener('click', function () {
    emit('section_done', {items: setDone(itemsIn(s.section.id).map(function (i) { return i.id; }), true)});
  });
  remind.addEventListener('click', function () { emit('section_remind', {section_id: s.section.id}); });
  postpone.addEventListener('click', function () { emit('section_postpone', {section_id: s.section.id}); });
  return s;
}

function paintSection(s, section, order) {
  var list = itemsIn(section.id);
  var open = openCount(list);
  var tone = section.accent || accent;
  var expanded = section.collapsed !== true;
  s.section = section; s.expanded = expanded;
  s.root.style.setProperty('--tone', tone);
  s.root.style.setProperty('--i', String(order + 3));
  if (expanded) s.root.setAttribute('data-open', ''); else s.root.removeAttribute('data-open');
  s.toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  s.toggle.setAttribute('aria-label', section.title + ', ' + open + ' à faire sur ' + list.length);
  s.title.textContent = section.title;
  cxCount(s.count, open, firstPaint ? 900 : 500);
  s.prog.style.setProperty('--v', list.length ? String((list.length - open) / list.length) : '0');
  if (expanded) s.panel.removeAttribute('inert'); else s.panel.setAttribute('inert', '');
  s.tools.setAttribute('aria-label', 'Actions de la section ' + section.title);
  s.allDone.setAttribute('aria-label', 'Tout marquer fait : ' + section.title);
  s.remind.setAttribute('aria-label', 'Rappeler la section : ' + section.title);
  s.postpone.setAttribute('aria-label', 'Reporter la section : ' + section.title);
  s.allDone.disabled = open === 0;
  s.remind.disabled = s.postpone.disabled = list.length === 0;
  var shown = list.filter(function (item) { return showDone || item.done !== true; });
  var keep = {};
  shown.forEach(function (item, k) {
    var n = s.rows[item.id];
    if (!n) {
      n = s.rows[item.id] = buildItem();
      n.root.classList.add('cx-rise');
      if (firstPaint) n.root.style.setProperty('--i', String(order + 4 + k));
    }
    paintItem(n, item, section, tone);
    keep[item.id] = true;
    if (s.list.children[k] !== n.root) s.list.insertBefore(n.root, s.list.children[k] || null);
  });
  Object.keys(s.rows).forEach(function (id) {
    if (!keep[id]) { var r = s.rows[id].root; if (r.parentNode) r.parentNode.removeChild(r); delete s.rows[id]; }
  });
  s.none.hidden = shown.length > 0;
  s.none.textContent = list.length ? 'Tout est fait.' : 'Rien ici.';
  s.list.hidden = shown.length === 0;
}

function paintHero(context) {
  var total = items.length;
  var open = openCount(items);
  var done = total - open;
  $('db-eyebrow').textContent = context.props.title || 'Tableau de bord';
  cxCount($('db-open'), open, firstPaint ? 1100 : 600);
  var ratio = total ? done / total : 0;
  $('db-ring').style.strokeDashoffset = String(100 - ratio * 100);
  cxCount($('db-pct'), Math.round(ratio * 100), 1100);
  var sub = context.props.subtitle;
  if (!sub) {
    sub = total === 0 ? 'Rien à suivre pour le moment.'
      : open === 0 ? 'Tout est fait : ' + total + (total > 1 ? ' éléments terminés.' : ' élément terminé.')
      : done + ' sur ' + total + ' terminé' + (done > 1 ? 's' : '') + ', ' + (open > 1 ? open + ' restent' : 'un reste') + ' à traiter.';
  }
  $('db-sub').textContent = sub;
  $('db-gauge').hidden = total === 0;
  var chips = $('db-chips');
  while (chips.firstChild) chips.removeChild(chips.firstChild);
  sections.forEach(function (section) {
    var c = cxEl('button', 'db-chip');
    c.setAttribute('type', 'button');
    c.style.setProperty('--tone', section.accent || accent);
    var dot = cxEl('span', 'cx-dot'); dot.setAttribute('aria-hidden', 'true');
    c.appendChild(dot);
    c.appendChild(cxEl('span', '', section.title));
    c.appendChild(cxEl('b', '', String(openCount(itemsIn(section.id)))));
    c.setAttribute('aria-label', 'Aller à ' + section.title);
    c.addEventListener('click', function () {
      var s = secNodes[section.id];
      if (s && s.root.scrollIntoView) s.root.scrollIntoView({behavior: CX_REDUCED ? 'auto' : 'smooth', block: 'start'});
    });
    chips.appendChild(c);
  });
  chips.hidden = sections.length < 2;
}

function render(context) {
  accent = context.props.accent || accent;
  $('db').style.setProperty('--cx-acc', accent);
  showDone = context.props.show_done !== false;
  sections = Array.isArray(context.data.sections) ? context.data.sections : [];
  items = Array.isArray(context.data.items) ? context.data.items : [];
  var seen = {};
  sections.forEach(function (section, index) {
    var s = secNodes[section.id];
    if (!s) s = secNodes[section.id] = buildSection(index);
    paintSection(s, section, index);
    seen[section.id] = true;
    if (sectionsEl.children[index] !== s.root) sectionsEl.insertBefore(s.root, sectionsEl.children[index] || null);
  });
  Object.keys(secNodes).forEach(function (id) {
    if (!seen[id]) { var r = secNodes[id].root; if (r.parentNode) r.parentNode.removeChild(r); delete secNodes[id]; }
  });
  emptyEl.hidden = sections.length > 0;
  paintHero(context);
  firstPaint = false;
}

jarvis.on('init', render);
jarvis.on('update', render);
jarvis.on('event_result', settle);
jarvis.on('teardown', function () {
  release();
  if (noticeTimer !== null) clearTimeout(noticeTimer);
});
