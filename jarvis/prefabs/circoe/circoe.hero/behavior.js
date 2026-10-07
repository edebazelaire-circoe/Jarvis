/* cx:begin (bloc commun des prefabs circoe.* : copie exacte de _common/cx.js, vérifiée par test) */
var CX_REDUCED = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
var CX_NS = 'http://www.w3.org/2000/svg';
var ICONS = {
  check: 'M5 12.5l4.6 4.6L19 7.6',
  chev: 'M9 6l6 6-6 6',
  bell: 'M6 16v-5a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0',
  cal: 'M4.5 6.5h15v13h-15zM4.5 10.5h15M8.5 4v4M15.5 4v4',
  out: 'M7 17L17 7M8.5 7H17v8.5',
  clock: 'M12 7.2V12l3 2M3.5 12a8.5 8.5 0 1 0 17 0 8.5 8.5 0 0 0-17 0',
  spark: 'M12 3.5l1.9 5.6 5.6 1.9-5.6 1.9L12 18.5l-1.9-5.6L4.5 11l5.6-1.9z',
  up: 'M6 14l6-6 6 6',
  down: 'M6 10l6 6 6-6',
  flag: 'M6 20.5v-16M6 5h11l-2.2 3.5L17 12H6'
};
function cxEl(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function cxIcon(name) {
  var svg = document.createElementNS(CX_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'cx-ico');
  svg.setAttribute('aria-hidden', 'true');
  var path = document.createElementNS(CX_NS, 'path');
  path.setAttribute('d', ICONS[name] || ICONS.spark);
  svg.appendChild(path);
  return svg;
}
function cxCount(node, to, ms) {
  var target = Math.round(Number(to) || 0);
  var from = Number(node.getAttribute('data-n'));
  var first = !isFinite(from) || node.getAttribute('data-n') === null;
  node.setAttribute('data-n', String(target));
  if (CX_REDUCED || ms === 0 || !window.requestAnimationFrame) { node.textContent = String(target); return; }
  var start = first ? 0 : from;
  if (start === target) { node.textContent = String(target); return; }
  var t0 = null;
  var span = ms || 900;
  function step(now) {
    if (t0 === null) t0 = now;
    var k = Math.min(1, (now - t0) / span);
    var e = 1 - Math.pow(1 - k, 4);
    node.textContent = String(Math.round(start + (target - start) * e));
    if (k < 1 && node.getAttribute('data-n') === String(target)) window.requestAnimationFrame(step);
    else node.textContent = node.getAttribute('data-n');
  }
  window.requestAnimationFrame(step);
}
function cxNum(value, digits) {
  var n = Number(value);
  if (!isFinite(n)) return String(value);
  return n.toLocaleString('fr-FR', {maximumFractionDigits: digits === undefined ? 1 : digits});
}
document.addEventListener('pointermove', function (event) {
  var glass = event.target && event.target.closest ? event.target.closest('.cx-glass') : null;
  if (!glass) return;
  var box = glass.getBoundingClientRect();
  glass.style.setProperty('--mx', (event.clientX - box.left) + 'px');
  glass.style.setProperty('--my', (event.clientY - box.top) + 'px');
});
/* cx:end */
/* circoe.hero : annonce typographique. Tout texte passe par textContent ; les noeuds des puces et des
   indicateurs sont conserves d'une mise a jour a l'autre ; le chiffre s'anime depuis sa valeur precedente. */
ICONS.bolt = 'M13 3.5L5.5 13.5H11l-1 7 7.5-10H12z';
ICONS.shield = 'M12 3.5l7 2.6v5.4c0 4.3-2.9 7.4-7 9-4.1-1.6-7-4.7-7-9V6.1z';
ICONS.globe = 'M3.5 12a8.5 8.5 0 1 0 17 0 8.5 8.5 0 0 0-17 0M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5S9.6 5.9 12 3.5';
ICONS.chart = 'M4.5 19.5h15M7.5 16v-4.5M12 16V7.5M16.5 16v-7';
ICONS.users = 'M9 11.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6M3.5 19c.5-3 2.7-4.8 5.5-4.8s5 1.8 5.5 4.8M16 5.8a3 3 0 0 1 0 5.4M17.5 14.5c1.8.6 2.7 2.1 3 4.2';
ICONS.lock = 'M6.5 11h11v8.5h-11zM8.5 11V8.2a3.5 3.5 0 0 1 7 0V11';
ICONS.heart = 'M12 19.5S4.5 15 4.5 9.6A3.9 3.9 0 0 1 12 8a3.9 3.9 0 0 1 7.5 1.6c0 5.4-7.5 9.9-7.5 9.9z';
ICONS.star = 'M12 4l2.4 5 5.4.7-4 3.7 1 5.4-4.8-2.7-4.8 2.7 1-5.4-4-3.7 5.4-.7z';
ICONS.layers = 'M12 4l8 4.2-8 4.2-8-4.2zM4 12.3l8 4.2 8-4.2M4 16.2l8 4.2 8-4.2';
ICONS.cpu = 'M7.5 7.5h9v9h-9zM10 10h4v4h-4zM9.5 4v3.5M14.5 4v3.5M9.5 16.5V20M14.5 16.5V20M4 9.5h3.5M4 14.5h3.5M16.5 9.5H20M16.5 14.5H20';
ICONS.leaf = 'M5 19c0-8 4-13.5 14-14.5 0 9-4.5 14-12 14M5 19c2-4 4.5-6.5 8-8.5';
ICONS.wand = 'M5 19L15.5 8.5M14 4.5v3M18.5 6h-3M19.5 11v2.5M20.8 12.2h-2.6M9 4.5v2M10 5.5H8';
var $ = function (id) { return document.getElementById(id); };
var root = $('hr');
var bulletsEl = $('hr-bullets');
var statsEl = $('hr-stats');
var notice = $('hr-notice');
var noticeTimer = null;
var bulletNodes = [];
var statNodes = [];
var shown = null;
var raf = 0;
var actionOn = false;
var first = true;

function say(text) {
  notice.textContent = text;
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(function () { noticeTimer = null; notice.textContent = ''; }, 3500);
}

function digitsOf(n) {
  var s = String(n);
  var i = s.indexOf('.');
  return i < 0 ? 0 : Math.min(2, s.length - i - 1);
}

function setValue(target, firstPaint) {
  var node = $('hr-value');
  var d = digitsOf(target);
  if (raf) { window.cancelAnimationFrame(raf); raf = 0; }
  var from = firstPaint || shown === null ? 0 : shown;
  shown = target;
  if (CX_REDUCED || !window.requestAnimationFrame || from === target) { node.textContent = cxNum(target, d); return; }
  var t0 = null;
  function step(now) {
    if (t0 === null) t0 = now;
    var k = Math.min(1, (now - t0) / (firstPaint ? 1500 : 800));
    var e = 1 - Math.pow(1 - k, 4);
    node.textContent = cxNum(from + (target - from) * e, d);
    if (k < 1) raf = window.requestAnimationFrame(step);
    else { raf = 0; node.textContent = cxNum(target, d); }
  }
  raf = window.requestAnimationFrame(step);
}

function buildBullet() {
  var li = cxEl('li', 'hr-bullet cx-rise');
  var ic = cxEl('span', 'hr-ic');
  ic.setAttribute('aria-hidden', 'true');
  var title = cxEl('h2', 'hr-b-title');
  var text = cxEl('p', 'hr-b-text');
  li.appendChild(ic); li.appendChild(title); li.appendChild(text);
  return {root: li, ic: ic, title: title, text: text, icon: ''};
}

function buildStat() {
  var wrap = cxEl('div', 'hr-stat cx-rise');
  var dd = cxEl('dd', '');
  var dt = cxEl('dt', '');
  wrap.appendChild(dd); wrap.appendChild(dt);
  return {root: wrap, dd: dd, dt: dt};
}

function sync(list, nodes, parent, make, paint) {
  while (nodes.length < list.length) {
    var n = make();
    n.root.style.setProperty('--i', String(4 + nodes.length));
    nodes.push(n);
    parent.appendChild(n.root);
  }
  while (nodes.length > list.length) { var gone = nodes.pop(); parent.removeChild(gone.root); }
  list.forEach(function (entry, i) { paint(nodes[i], entry); });
}

function render(context) {
  var props = context.props || {};
  var data = context.data || {};
  root.style.setProperty('--cx-acc', props.accent || '#6ee7ff');
  root.setAttribute('data-align', props.align === 'center' ? 'center' : 'left');
  $('hr-eyebrow').textContent = data.eyebrow || '';
  $('hr-eyebrow').hidden = !data.eyebrow;
  var title = String(data.title || '');
  var tEl = $('hr-title');
  while (tEl.firstChild) tEl.removeChild(tEl.firstChild);
  var hl = String(data.highlight || '');
  var at = hl ? title.indexOf(hl) : -1;
  if (at >= 0) {
    tEl.appendChild(document.createTextNode(title.slice(0, at)));
    tEl.appendChild(cxEl('em', '', hl));
    tEl.appendChild(document.createTextNode(title.slice(at + hl.length)));
  } else tEl.textContent = title;
  $('hr-lead').textContent = data.lead || '';
  $('hr-lead').hidden = !data.lead;

  var m = data.metric || {value: 0};
  $('hr-metric').hidden = !data.metric;
  $('hr-unit').textContent = m.unit || '';
  $('hr-label').textContent = m.label || '';
  var delta = $('hr-delta');
  delta.hidden = !m.delta;
  $('hr-delta-t').textContent = m.delta || '';
  var trend = m.trend === 'down' || m.trend === 'flat' ? m.trend : 'up';
  delta.setAttribute('data-trend', trend);
  $('hr-trend').setAttribute('d', trend === 'down' ? 'M6 10l6 6 6-6' : trend === 'flat' ? 'M5 12h14' : 'M6 14l6-6 6 6');
  var value = Number(m.value);
  if (!isFinite(value)) value = 0;
  $('hr-metric').setAttribute('aria-label', cxNum(value, digitsOf(value)) + ' ' + (m.unit || '') + ' ' + (m.label || ''));
  setValue(value, first);

  var bullets = Array.isArray(data.bullets) ? data.bullets : [];
  sync(bullets, bulletNodes, bulletsEl, buildBullet, function (n, b) {
    if (n.icon !== b.icon) {
      while (n.ic.firstChild) n.ic.removeChild(n.ic.firstChild);
      n.ic.appendChild(cxIcon(b.icon));
      n.icon = b.icon;
    }
    n.title.textContent = b.title || '';
    n.text.textContent = b.text || '';
    n.text.hidden = !b.text;
  });
  bulletsEl.hidden = bullets.length === 0;

  var stats = Array.isArray(data.stats) ? data.stats : [];
  sync(stats, statNodes, statsEl, buildStat, function (n, s) {
    n.dd.textContent = s.value === undefined ? '' : String(s.value);
    n.dt.textContent = s.label || '';
  });
  statsEl.hidden = stats.length === 0;
  $('hr-rule').hidden = stats.length === 0;

  var act = data.action && data.action.label ? data.action : null;
  actionOn = !!act;
  $('hr-cta').hidden = !act;
  $('hr-action-t').textContent = act ? act.label : '';
  first = false;
}

$('hr-action').addEventListener('click', function () {
  if (!actionOn) return;
  try { jarvis.emit('hero_action', {label: $('hr-action-t').textContent}); } catch (_e) { say('Jarvis a refusé l’action.'); }
});
jarvis.on('event_result', function (r) {
  if (!r || r.name !== 'hero_action') return;
  say(r.outcome === 'recorded' || r.outcome === 'applied' ? 'Demande envoyée.' : 'Action non transmise.');
});
jarvis.on('init', render);
jarvis.on('update', render);
jarvis.on('teardown', function () {
  if (raf) window.cancelAnimationFrame(raf);
  if (noticeTimer !== null) clearTimeout(noticeTimer);
});
