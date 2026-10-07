/* circoe.metrics : cartes de chiffres. Affichage seul ; le seul événement est la notification card_open.
   Graphes en SVG construits ici (courbe de Catmull-Rom bornée, aire dégradée, anneau, barres) ; nœuds
   conservés d'une mise à jour à l'autre (un id de carte = une carte, tant que son genre ne change pas). */
ICONS.trend = 'M3.5 17l5.5-5.5 4 4 7-8M15 7.5h5v5';
ICONS.users = 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.8 20c.4-3.3 3-5.2 6.2-5.2s5.8 1.9 6.2 5.2M16 4.4a3.5 3.5 0 0 1 0 6.4M18.5 14.9c1.6.7 2.5 2.3 2.7 4.1';
ICONS.target = 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 11.4v1.2';
ICONS.euro = 'M17.5 6.8A6.5 6.5 0 0 0 7 9.5v5a6.5 6.5 0 0 0 10.5 2.7M4.5 10.8h9M4.5 13.2h9';
ICONS.ticket = 'M4 8.5A1.5 1.5 0 0 1 5.5 7h13A1.5 1.5 0 0 1 20 8.5V10a2 2 0 0 0 0 4v1.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 15.5V14a2 2 0 0 0 0-4zM14 7.5v9';
ICONS.bars = 'M5 20v-8M12 20V4M19 20v-6';
ICONS.timer = 'M12 8v4.5l2.5 1.5M9.5 3.5h5M12 5a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15z';
ICONS.bolt = 'M13 3.5L5.5 13.5H12l-1 7 7.5-10H12z';
ICONS.heart = 'M12 19.5s-7-4.2-7-9.4A4 4 0 0 1 12 7.7a4 4 0 0 1 7 2.4c0 5.2-7 9.4-7 9.4z';
ICONS.globe = 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM3.8 12h16.4M12 3.5c2.4 2.4 3.4 5.2 3.4 8.5s-1 6.1-3.4 8.5c-2.4-2.4-3.4-5.2-3.4-8.5s1-6.1 3.4-8.5z';

var $ = function (id) { return document.getElementById(id); };
var root = $('mt');
var gridEl = $('mt-grid');
var notice = $('mt-notice');
var TONES = {accent: 'var(--cx-acc)', ok: 'var(--cx-ok)', warm: 'var(--cx-warm)', urgent: 'var(--cx-urgent)', violet: 'var(--cx-violet)'};
var nodes = {};
var order = [];
var accent = '#6ee7ff';
var columns = 'auto';
var noticeTimer = null;
var gradSeq = 0;
var firstPaint = true;

function svgEl(tag, attrs) {
  var node = document.createElementNS(CX_NS, tag);
  Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
  return node;
}

function say(text) {
  notice.textContent = text;
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(function () { noticeTimer = null; notice.textContent = ''; }, 4000);
}

function fmt(value, format) {
  var n = Number(value);
  if (!isFinite(n)) return '–';
  var d = format === 'decimal' ? 1 : 0;
  return n.toLocaleString('fr-FR', {minimumFractionDigits: d, maximumFractionDigits: d});
}
function unitOf(card) { return card.unit || (card.format === 'percent' ? '%' : ''); }
function withUnit(value, card) { var u = unitOf(card); return fmt(value, card.format) + (u ? ' ' + u : ''); }

/* Compte jusqu'à la valeur (formatée), depuis 0 à la première fois puis depuis la valeur précédente. */
function tween(node, to, format, ms) {
  var target = Number(to);
  if (!isFinite(target)) { node.textContent = '–'; node._v = undefined; return; }
  var first = node._v === undefined;
  var from = first ? 0 : node._v;
  node._v = target;
  node._f = format;
  if (CX_REDUCED || !window.requestAnimationFrame || from === target) { node.textContent = fmt(target, format); return; }
  var t0 = null;
  function step(now) {
    if (node._v !== target) return;
    if (t0 === null) t0 = now;
    var k = Math.min(1, (now - t0) / ms);
    var e = 1 - Math.pow(1 - k, 4);
    node.textContent = fmt(from + (target - from) * e, format);
    if (k < 1) window.requestAnimationFrame(step); else node.textContent = fmt(target, format);
  }
  window.requestAnimationFrame(step);
}

function r1(n) { return Math.round(n * 10) / 10; }

/* Courbe lisse de Catmull-Rom ; les points de contrôle restent entre les deux ordonnées voisines : pas de dépassement. */
function smooth(pts) {
  var d = 'M' + r1(pts[0].x) + ' ' + r1(pts[0].y);
  for (var i = 0; i < pts.length - 1; i += 1) {
    var p0 = pts[i - 1] || pts[i];
    var p1 = pts[i];
    var p2 = pts[i + 1];
    var p3 = pts[i + 2] || p2;
    var lo = Math.min(p1.y, p2.y);
    var hi = Math.max(p1.y, p2.y);
    var c1y = Math.max(lo, Math.min(hi, p1.y + (p2.y - p0.y) / 6));
    var c2y = Math.max(lo, Math.min(hi, p2.y - (p3.y - p1.y) / 6));
    d += 'C' + r1(p1.x + (p2.x - p0.x) / 6) + ' ' + r1(c1y) + ' ' + r1(p2.x - (p3.x - p1.x) / 6) + ' ' + r1(c2y) + ' ' + r1(p2.x) + ' ' + r1(p2.y);
  }
  return d;
}

function cleanSeries(raw) {
  var out = [];
  (Array.isArray(raw) ? raw : []).forEach(function (v) { var n = Number(v); if (isFinite(n) && out.length < 60) out.push(n); });
  return out;
}

function buildChart(hero, order_) {
  var el = cxEl('div', 'mt-chart mt-viz');
  el.setAttribute('role', 'img');
  var id = 'mtg' + (gradSeq += 1);
  var svg = svgEl('svg', {preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false'});
  var defs = svgEl('defs');
  var grad = svgEl('linearGradient', {id: id, x1: '0', y1: '0', x2: '0', y2: '1'});
  grad.appendChild(svgEl('stop', {offset: '0', 'class': 'mt-s0'}));
  grad.appendChild(svgEl('stop', {offset: '1', 'class': 'mt-s1'}));
  defs.appendChild(grad);
  svg.appendChild(defs);
  var grid = svgEl('g');
  if (hero) { for (var g = 0; g < 3; g += 1) grid.appendChild(svgEl('line', {'class': 'mt-grid-line'})); }
  var area = svgEl('path', {'class': 'mt-area', fill: 'url(#' + id + ')'});
  var line = svgEl('path', {'class': 'mt-line', pathLength: '1'});
  svg.appendChild(grid); svg.appendChild(area); svg.appendChild(line);
  var end = cxEl('span', 'mt-end');
  var cur = cxEl('span', 'mt-cur');
  var dot = cxEl('span', 'mt-dot');
  var tip = cxEl('span', 'mt-tip');
  var tipV = cxEl('span', '');
  var tipS = cxEl('small', '');
  tip.appendChild(tipV); tip.appendChild(tipS);
  [svg, end, cur, dot, tip].forEach(function (n) { el.appendChild(n); });
  var c = {root: el, svg: svg, grid: grid, area: area, line: line, end: end, cur: cur, dot: dot, tip: tip, tipV: tipV, tipS: tipS,
    hero: hero, rank: order_, series: [], pts: [], w: 0, h: 0, card: null, drawn: false};
  function show(clientX) {
    if (!c.pts.length) return;
    var box = el.getBoundingClientRect();
    var x = clientX - box.left;
    var best = 0;
    var gap = Infinity;
    c.pts.forEach(function (p, i) { var dx = Math.abs(p.x - x); if (dx < gap) { gap = dx; best = i; } });
    var p = c.pts[best];
    cur.style.left = p.x + 'px';
    dot.style.left = p.x + 'px';
    dot.style.top = p.y + 'px';
    tipV.textContent = withUnit(c.series[best], c.card);
    tipS.textContent = (best + 1) + ' / ' + c.pts.length;
    var half = tip.offsetWidth / 2;
    tip.style.left = Math.max(4, Math.min(c.w - tip.offsetWidth - 4, p.x - half)) + 'px';
    el.setAttribute('data-hover', '');
  }
  el.addEventListener('pointermove', function (event) { show(event.clientX); });
  el.addEventListener('pointerdown', function (event) { show(event.clientX); });
  el.addEventListener('pointerleave', function () { el.removeAttribute('data-hover'); });
  if (window.ResizeObserver) new ResizeObserver(function () { drawChart(c); }).observe(el);
  return c;
}

function drawChart(c) {
  var w = c.root.clientWidth;
  var h = c.root.clientHeight;
  var s = c.series;
  if (!w || !h || s.length < 2) return;
  c.w = w; c.h = h;
  c.svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
  var padT = c.hero ? h * 0.2 : h * 0.18;
  var padB = c.hero ? h * 0.1 : h * 0.14;
  var padR = c.hero ? 10 : 8;
  var min = Math.min.apply(null, s);
  var max = Math.max.apply(null, s);
  var span = max - min || 1;
  c.pts = s.map(function (v, i) {
    return {x: (w - padR) * i / (s.length - 1), y: max === min ? h / 2 : padT + (1 - (v - min) / span) * (h - padT - padB)};
  });
  var d = smooth(c.pts);
  c.line.setAttribute('d', d);
  var last = c.pts[c.pts.length - 1];
  c.area.setAttribute('d', d + 'L' + w + ' ' + r1(last.y) + 'L' + w + ' ' + h + 'L0 ' + h + 'Z');
  c.end.style.left = last.x + 'px';
  c.end.style.top = last.y + 'px';
  var lines = c.grid.childNodes;
  for (var i = 0; i < lines.length; i += 1) {
    var y = r1(padT + (h - padT - padB) * (i + 0.5) / lines.length);
    lines[i].setAttribute('x1', '0'); lines[i].setAttribute('x2', String(w));
    lines[i].setAttribute('y1', String(y)); lines[i].setAttribute('y2', String(y));
  }
  if (!c.drawn) {
    c.drawn = true;
    var wait = (firstPaint ? 380 : 60) + c.rank * 110;
    setTimeout(function () { c.root.setAttribute('data-in', ''); }, CX_REDUCED ? 0 : wait);
  }
}

function buildRing() {
  var el = cxEl('div', 'mt-ring mt-viz');
  el.setAttribute('role', 'img');
  var svg = svgEl('svg', {viewBox: '0 0 120 120', 'aria-hidden': 'true', focusable: 'false'});
  svg.appendChild(svgEl('circle', {'class': 'mt-ring-track', cx: '60', cy: '60', r: '50'}));
  var fill = svgEl('circle', {'class': 'mt-ring-fill', cx: '60', cy: '60', r: '50', pathLength: '100'});
  svg.appendChild(fill);
  var inner = cxEl('div', 'mt-ring-in');
  inner.setAttribute('aria-hidden', 'true');
  var cap = cxEl('span', 'mt-ring-cap');
  el.appendChild(svg); el.appendChild(inner);
  return {root: el, fill: fill, inner: inner, cap: cap};
}

function buildBars() {
  var ul = cxEl('ul', 'mt-bars mt-viz');
  return {root: ul, rows: []};
}

function buildCard(card, index) {
  var kind = card.kind;
  var root = cxEl('article', 'mt-card cx-glass cx-lift cx-rise');
  root.setAttribute('data-kind', kind);
  var top = cxEl('div', 'mt-top');
  var eyebrow = cxEl('p', 'cx-eyebrow mt-eyebrow');
  eyebrow.setAttribute('aria-hidden', 'true');
  var iconHost = cxEl('span', '');
  iconHost.style.display = 'contents';
  var label = cxEl('span', '');
  eyebrow.appendChild(iconHost); eyebrow.appendChild(label);
  var open = cxEl('button', 'mt-open');
  open.setAttribute('type', 'button');
  open.appendChild(cxIcon('out'));
  top.appendChild(eyebrow); top.appendChild(open);

  var main = cxEl('div', 'mt-main');
  var text = cxEl('div', 'mt-text');
  var fig = cxEl('div', 'mt-fig');
  var value = cxEl('p', 'mt-value');
  value.setAttribute('aria-hidden', 'true');
  var num = cxEl('span', 'mt-num', '0');
  var unit = cxEl('span', 'mt-unit');
  value.appendChild(num); value.appendChild(unit);
  var delta = cxEl('span', 'mt-delta');
  delta.setAttribute('aria-hidden', 'true');
  var arrow = cxEl('span', 'mt-arrow');
  var dText = cxEl('span', '');
  delta.appendChild(arrow); delta.appendChild(dText);
  var note = cxEl('p', 'cx-cap mt-note');
  note.setAttribute('aria-hidden', 'true');
  var sr = cxEl('p', 'cx-sr');

  var n = {root: root, kind: kind, icon: iconHost, iconName: '', label: label, open: open, num: num, unit: unit, delta: delta, arrow: arrow,
    dText: dText, note: note, sr: sr, viz: null, ring: null, bars: null, chart: null, card: card, index: index, ringCap: null};

  if (kind === 'ring') {
    n.ring = buildRing();
    n.ringCap = n.ring.cap;
    n.ring.inner.appendChild(value); n.ring.inner.appendChild(n.ring.cap);
    fig.appendChild(delta);
    text.appendChild(fig); text.appendChild(note);
    main.appendChild(n.ring.root); main.appendChild(text);
    n.viz = n.ring.root;
  } else {
    fig.appendChild(value);
    fig.appendChild(delta);
    text.appendChild(fig); text.appendChild(note);
    main.appendChild(text);
    if (kind === 'line' || kind === 'spark') {
      n.chart = buildChart(kind === 'line', index);
      n.viz = n.chart.root;
    } else if (kind === 'bars') {
      n.bars = buildBars();
      main.appendChild(n.bars.root);
      n.viz = n.bars.root;
    }
  }
  root.appendChild(top); root.appendChild(main); root.appendChild(sr);
  if (n.chart) {
    var range = cxEl('p', 'mt-range');
    range.setAttribute('aria-hidden', 'true');
    n.range = range;
    n.rangeMin = cxEl('span', ''); n.rangeMax = cxEl('span', '');
    range.appendChild(n.rangeMin); range.appendChild(n.rangeMax);
    root.insertBefore(range, sr);
    root.insertBefore(n.chart.root, range);
  }
  open.addEventListener('click', function () {
    try { jarvis.emit('card_open', {card_id: n.card.id}); } catch (_error) { say('Jarvis a refusé l’action.'); }
  });
  return n;
}

function paintDelta(n, card) {
  var d = Number(card.delta);
  if (card.delta === undefined || card.delta === null || !isFinite(d)) { n.delta.hidden = true; return ''; }
  var dir = d > 0 ? 1 : d < 0 ? -1 : 0;
  var good = card.good === 'down' ? -1 : 1;
  var verdict = dir === 0 ? 'flat' : dir * good > 0 ? 'good' : 'bad';
  n.delta.hidden = false;
  n.delta.setAttribute('data-v', verdict);
  n.arrow.textContent = dir > 0 ? '▲' : dir < 0 ? '▼' : '●';
  var amount = Math.abs(d).toLocaleString('fr-FR', {maximumFractionDigits: 1});
  n.dText.textContent = (dir > 0 ? '+' : dir < 0 ? '−' : '') + amount + ' %';
  var sense = dir === 0 ? 'stable' : (dir > 0 ? 'en hausse de ' : 'en baisse de ') + amount + ' %';
  return sense + (dir === 0 ? '' : verdict === 'good' ? ', favorable' : ', défavorable');
}

function ringFraction(card) {
  var v = Number(card.value);
  var t = Number(card.target);
  var f;
  if (card.format === 'percent') f = v / 100;
  else if (isFinite(t) && t > 0) f = v / t;
  else f = v / 100;
  return isFinite(f) ? Math.max(0, Math.min(1, f)) : 0;
}

/* « libellé: valeur » (le schéma des prefabs borde l'imbrication : une barre est une chaîne). */
function parseBar(entry) {
  var text = String(entry);
  var cut = text.lastIndexOf(':');
  if (cut < 0) return {label: text, value: 0};
  return {label: text.slice(0, cut).trim(), value: Number(text.slice(cut + 1).replace(',', '.').replace(/\s/g, ''))};
}

function paintBars(n, card, tone) {
  var list = (Array.isArray(card.bars) ? card.bars.slice(0, 6) : []).map(parseBar);
  var max = 0;
  var topIndex = -1;
  list.forEach(function (b, i) { var v = Number(b.value) || 0; if (v > max) { max = v; topIndex = i; } });
  var rows = n.bars.rows;
  while (rows.length > list.length) { var gone = rows.pop(); n.bars.root.removeChild(gone.root); }
  list.forEach(function (b, i) {
    var row = rows[i];
    if (!row) {
      var li = cxEl('li', 'mt-bar');
      var l = cxEl('span', 'mt-bar-l');
      var v = cxEl('span', 'mt-bar-v');
      var track = cxEl('div', 'cx-track');
      var fill = cxEl('div', 'cx-fill');
      track.appendChild(fill);
      li.appendChild(l); li.appendChild(v); li.appendChild(track);
      n.bars.root.appendChild(li);
      row = rows[i] = {root: li, l: l, v: v, fill: fill, grown: false};
    }
    var val = Number(b.value) || 0;
    var u = unitOf(card);
    row.l.textContent = b.label;
    row.v.textContent = fmt(val, card.format);
    if (u && u.length <= 2) row.v.appendChild(cxEl('small', '', u));
    if (i === topIndex) row.root.setAttribute('data-top', ''); else row.root.removeAttribute('data-top');
    var share = max > 0 ? val / max : 0;
    if (row.grown || CX_REDUCED) row.fill.style.setProperty('--v', String(share));
    else {
      row.grown = true;
      row.fill.style.transitionDelay = (firstPaint ? 0.45 : 0.1) + i * 0.09 + 's';
      setTimeout(function () { row.fill.style.setProperty('--v', String(share)); }, 30);
    }
  });
  return list.map(function (b) { return b.label + ' ' + withUnit(b.value, card); }).join(', ');
}

function paintCard(n, card, index) {
  n.card = card; n.index = index;
  var tone = TONES[card.tone] || TONES.accent;
  n.root.style.setProperty('--tone', tone);
  n.root.style.setProperty('--i', String(index + 2));
  var icon = card.icon || 'spark';
  if (n.iconName !== icon) {
    while (n.icon.firstChild) n.icon.removeChild(n.icon.firstChild);
    n.icon.appendChild(cxIcon(icon));
    n.iconName = icon;
  }
  n.label.textContent = card.label;
  var u = unitOf(card);
  tween(n.num, card.value, card.format, n.kind === 'line' ? 1500 : 1100);
  n.unit.textContent = u;
  n.unit.hidden = !u;
  var sense = paintDelta(n, card);
  n.note.textContent = card.note || '';
  n.note.hidden = !card.note;
  n.open.setAttribute('aria-label', 'Ouvrir : ' + card.label);
  var parts = [card.label + ' : ' + withUnit(card.value, card)];
  if (sense) parts.push(sense);
  if (card.note) parts.push(card.note);

  if (n.kind === 'ring') {
    var f = ringFraction(card);
    var t = Number(card.target);
    var showTarget = card.format !== 'percent' && isFinite(t) && t > 0;
    n.ringCap.textContent = showTarget ? 'sur ' + fmt(t, card.format) : '';
    n.ringCap.hidden = !showTarget;
    n.ring.root.setAttribute('aria-label', Math.round(f * 100) + ' % de l’objectif atteint');
    parts.push(Math.round(f * 100) + ' % de l’objectif atteint');
    var apply = function () { n.ring.fill.style.strokeDashoffset = String(100 - f * 100); };
    if (n.ringGrown || CX_REDUCED) apply(); else { n.ringGrown = true; setTimeout(apply, firstPaint ? 450 : 80); }
  } else if (n.chart) {
    var series = cleanSeries(card.series);
    n.chart.series = series;
    n.chart.card = card;
    n.chart.root.hidden = series.length < 2;
    n.chart.root.style.setProperty('--tone', tone);
    if (series.length >= 2) {
      var lo = Math.min.apply(null, series);
      var hi = Math.max.apply(null, series);
      var summary = 'Courbe de ' + series.length + ' valeurs, de ' + withUnit(series[0], card) + ' à ' + withUnit(series[series.length - 1], card) +
        ', minimum ' + withUnit(lo, card) + ', maximum ' + withUnit(hi, card) + '.';
      n.chart.root.setAttribute('aria-label', summary);
      n.rangeMin.textContent = 'min ' + withUnit(lo, card);
      n.rangeMax.textContent = 'max ' + withUnit(hi, card);
      parts.push(summary + ' Valeurs : ' + series.map(function (v) { return fmt(v, card.format); }).join(', ') + '.');
      drawChart(n.chart);
    }
    n.range.hidden = series.length < 2;
  } else if (n.bars) {
    parts.push('Comparaison : ' + paintBars(n, card, tone) + '.');
  }
  n.sr.textContent = parts.join('. ').replace(/\.\./g, '.');
}

function colsNow() {
  if (columns === '2' || columns === '3') return Number(columns);
  var px = parseFloat(getComputedStyle(gridEl).fontSize) || 16;
  var em = gridEl.clientWidth / px;
  return em >= 50 ? 3 : em >= 26 ? 2 : 1;
}

function layout() {
  var N = colsNow();
  var u = 6 / N;
  var group = [];
  function flush() {
    var i = 0;
    while (i < group.length) {
      var take = Math.min(N, group.length - i);
      var base = Math.floor(N / take);
      var extra = N - base * take;
      for (var k = 0; k < take; k += 1) group[i + k].root.style.gridColumn = 'span ' + (base + (k < extra ? 1 : 0)) * u;
      i += take;
    }
    group = [];
  }
  order.forEach(function (id) {
    var n = nodes[id];
    if (n.kind === 'line') { flush(); n.root.style.gridColumn = 'span 6'; } else group.push(n);
  });
  flush();
}

function render(context) {
  accent = context.props.accent || accent;
  columns = context.props.columns || 'auto';
  root.style.setProperty('--cx-acc', accent);
  $('mt-title').textContent = context.data.title || 'Résumé';
  var period = $('mt-period');
  period.textContent = '';
  if (context.data.period) {
    period.appendChild(cxIcon('cal'));
    period.appendChild(cxEl('span', 'cx-num', context.data.period));
    period.hidden = false;
  } else period.hidden = true;
  var cards = (Array.isArray(context.data.cards) ? context.data.cards : []).slice(0, 6);
  var seen = {};
  order = [];
  cards.forEach(function (card, index) {
    var n = nodes[card.id];
    if (n && n.kind !== card.kind) { if (n.root.parentNode) n.root.parentNode.removeChild(n.root); n = nodes[card.id] = null; }
    if (!n) n = nodes[card.id] = buildCard(card, index);
    seen[card.id] = true;
    order.push(card.id);
    if (gridEl.children[index] !== n.root) gridEl.insertBefore(n.root, gridEl.children[index] || null);
    paintCard(n, card, index);
  });
  Object.keys(nodes).forEach(function (id) {
    if (!seen[id]) { var gone = nodes[id]; if (gone && gone.root.parentNode) gone.root.parentNode.removeChild(gone.root); delete nodes[id]; }
  });
  $('mt-empty').hidden = cards.length > 0;
  layout();
  firstPaint = false;
}

function settle(result) {
  if (!result || result.name !== 'card_open') return;
  if (result.outcome === 'recorded' || result.outcome === 'applied') say('Ouverture demandée.');
  else say('Jarvis a refusé l’action.');
}

if (window.ResizeObserver) new ResizeObserver(function () { layout(); }).observe(gridEl);
jarvis.on('init', render);
jarvis.on('update', render);
jarvis.on('event_result', settle);
jarvis.on('teardown', function () { if (noticeTimer !== null) clearTimeout(noticeTimer); });
