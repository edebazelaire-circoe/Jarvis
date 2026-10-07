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
/* circoe.timeline v1. Frise de la semaine. Tout texte passe par textContent ; les nœuds (jours, lignes)
   sont conservés d'une mise à jour à l'autre. `now` fourni : rendu déterministe ; sinon l'heure du cadre,
   relue toutes les 30 s. */
ICONS.users = 'M9 11a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM3.5 19.5c.4-3.3 2.7-5 5.5-5s5.1 1.7 5.5 5M16 4.8a3.2 3.2 0 0 1 0 6.2M17.3 14.8c2 .5 3.3 2.2 3.5 4.7';
ICONS.plane = 'M20.5 4L3.5 10.8l6.3 2.4 2.4 6.3zM9.8 13.2L20.5 4';
ICONS.heart = 'M12 19.5s-7-4.3-7-9.6A4 4 0 0 1 12 7.5a4 4 0 0 1 7 2.4c0 5.3-7 9.6-7 9.6z';
ICONS.target = 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z';
ICONS.pin = 'M12 20.5s6-5.2 6-10a6 6 0 1 0-12 0c0 4.8 6 10 6 10zM12 12.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4z';
var $ = function (id) { return document.getElementById(id); };
var daysEl = $('tl-days');
var notice = $('tl-notice');
var KINDS = {
  meeting: {label: 'Réunion', icon: 'users', tone: 'var(--cx-acc)'},
  travel: {label: 'Déplacement', icon: 'plane', tone: 'var(--cx-violet)'},
  personal: {label: 'Perso', icon: 'heart', tone: 'var(--cx-ok)'},
  deadline: {label: 'Échéance', icon: 'flag', tone: 'var(--cx-urgent)'},
  focus: {label: 'Focus', icon: 'target', tone: 'var(--cx-warm)'}
};
var PEOPLE_TONES = ['#6ee7ff', '#aea4ff', '#ffcf72', '#63e8a9', '#ff8c7a', '#8fb8ff'];
var last = null;
var accent = '#6ee7ff';
var dayNodes = {};
var evNodes = {};
var noticeTimer = null;
var clockTimer = null;
var firstPaint = true;

function say(text) {
  notice.textContent = text;
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(function () { noticeTimer = null; notice.textContent = ''; }, 4000);
}

function parseTime(text) {
  var m = /^(\d{1,2}):(\d{2})$/.exec(String(text || '').trim());
  if (!m) return null;
  var h = Number(m[1]);
  var mi = Number(m[2]);
  if (h > 24 || mi > 59) return null;
  return h * 60 + mi;
}
function pad(n) { return (n < 10 ? '0' : '') + n; }
function clock(minutes) { return pad(Math.floor(minutes / 60) % 24) + ':' + pad(minutes % 60); }
function fmtDur(min) {
  if (min < 60) return min + ' min';
  var h = Math.floor(min / 60);
  var m = min % 60;
  return h + ' h' + (m ? ' ' + pad(m) : '');
}
function fmtIn(delta, dayDiff) {
  if (delta < 1) return 'À l’instant';
  if (delta < 60) return 'Dans ' + delta + ' min';
  if (dayDiff < 1) return 'Dans ' + fmtDur(delta);
  if (dayDiff === 1) return 'Demain';
  return 'Dans ' + dayDiff + ' j';
}
function personTone(text) {
  var s = String(text);
  var h = 0;
  for (var i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) % 997;
  return PEOPLE_TONES[h % PEOPLE_TONES.length];
}

function reference(props) {
  var d = props && props.now ? new Date(props.now) : new Date();
  if (isNaN(d.getTime())) d = new Date();
  return {min: d.getHours() * 60 + d.getMinutes(), date: d.getDate()};
}

/* Une passe : l'état, le délai et la progression de chaque événement, et celui à mettre en avant. */
function analyse(days, ref) {
  var todayIdx = -1;
  days.forEach(function (day, i) { if (todayIdx < 0 && Number(day.date) === ref.date) todayIdx = i; });
  var list = [];
  days.forEach(function (day, di) {
    (day.events || []).forEach(function (ev) {
      var s = parseTime(ev.start);
      var e = parseTime(ev.end);
      if (s !== null && e !== null && e < s) e += 1440;
      var endEff = e !== null ? e : s !== null ? s + (ev.kind === 'deadline' ? 0 : 30) : null;
      var state = ev.state;
      if (!state) {
        if (todayIdx < 0 || s === null) state = 'upcoming';
        else if (di < todayIdx) state = 'past';
        else if (di > todayIdx) state = 'upcoming';
        else state = ref.min >= endEff ? 'past' : ref.min >= s ? 'now' : 'upcoming';
      }
      list.push({day: day, di: di, ev: ev, s: s, e: e, endEff: endEff, state: state});
    });
  });
  if (!list.some(function (x) { return x.state === 'next'; })) {
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].state === 'upcoming') { list[i].state = 'next'; break; }
    }
  }
  var feature = null;
  var soon = null;
  list.forEach(function (x) { if (!feature && x.state === 'now') feature = x; });
  list.forEach(function (x) {
    if (x.state !== 'next') return;
    if (!feature) feature = x; else if (!soon) soon = x;
  });
  var info = {};
  list.forEach(function (x) {
    var timed = todayIdx >= 0 && x.s !== null;
    var dayDiff = todayIdx >= 0 ? x.di - todayIdx : 0;
    var entry = {state: x.state, feature: x === feature, soon: x === soon, label: '', progress: 0};
    if (x.state === 'now') {
      var span = x.endEff - x.s;
      var left = x.endEff - ref.min;
      var live = timed && x.di === todayIdx;
      entry.label = live && left > 0 ? 'En cours · encore ' + fmtDur(left) : 'En cours';
      entry.progress = live && span > 0 ? Math.max(.04, Math.min(1, (ref.min - x.s) / span)) : .5;
    } else if (x.state === 'next') {
      if (timed) {
        var delta = Math.max(0, dayDiff * 1440 + x.s - ref.min);
        entry.label = fmtIn(delta, dayDiff);
        entry.progress = Math.max(.05, 1 - Math.min(1, delta / 240));
      } else {
        entry.label = 'À suivre';
        entry.progress = .08;
      }
    }
    info[x.day.id + '/' + x.ev.id] = entry;
  });
  return {todayIdx: todayIdx, info: info, total: list.length,
    ahead: list.filter(function (x) { return x.state !== 'past'; }).length};
}

function buildDay() {
  var li = cxEl('li', 'tl-day cx-rise');
  var col = cxEl('div', 'tl-daycol');
  var num = cxEl('span', 'tl-num cx-num');
  var lab = cxEl('span', 'tl-lab');
  var pill = cxEl('span', 'cx-pill tl-today', 'Aujourd’hui');
  col.appendChild(num); col.appendChild(lab); col.appendChild(pill);
  var rail = cxEl('div', 'tl-rail'); rail.setAttribute('aria-hidden', 'true');
  var list = cxEl('ul', 'tl-events');
  li.appendChild(col); li.appendChild(rail); li.appendChild(list);
  return {root: li, num: num, lab: lab, pill: pill, list: list, day: null};
}

function buildEvent() {
  var li = cxEl('li', 'tl-ev');
  var node = cxEl('span', 'tl-node'); node.setAttribute('aria-hidden', 'true');
  var card = cxEl('div', 'tl-card');
  var time = cxEl('div', 'tl-time');
  var start = cxEl('span', 'tl-start cx-num');
  var end = cxEl('span', 'tl-end cx-num');
  time.appendChild(start); time.appendChild(end);
  var main = cxEl('div', 'tl-main');
  var title = cxEl('span', 'tl-ev-title');
  var place = cxEl('span', 'tl-place');
  place.appendChild(cxIcon('pin'));
  var placeText = cxEl('span', '');
  place.appendChild(placeText);
  var live = cxEl('div', 'tl-live');
  var liveLabel = cxEl('span', 'tl-live-label');
  var track = cxEl('div', 'cx-track tl-track'); track.setAttribute('aria-hidden', 'true');
  var fill = cxEl('div', 'cx-fill');
  track.appendChild(fill);
  live.appendChild(liveLabel); live.appendChild(track);
  main.appendChild(title); main.appendChild(place); main.appendChild(live);
  var side = cxEl('div', 'tl-side');
  var kind = cxEl('span', 'cx-pill tl-kind');
  var kindIcon = cxIcon('users');
  var kindText = cxEl('span', '');
  kind.appendChild(kindIcon); kind.appendChild(kindText);
  var dur = cxEl('span', 'tl-dur cx-num');
  dur.appendChild(cxIcon('clock'));
  var durText = cxEl('span', '');
  dur.appendChild(durText);
  var people = cxEl('span', 'tl-people');
  side.appendChild(kind); side.appendChild(dur); side.appendChild(people);
  var open = cxEl('button', 'tl-open');
  open.setAttribute('type', 'button');
  open.appendChild(cxEl('span', '', 'Ouvrir'));
  open.appendChild(cxIcon('out'));
  card.appendChild(time); card.appendChild(main); card.appendChild(side); card.appendChild(open);
  li.appendChild(node); li.appendChild(card);
  var n = {root: li, start: start, end: end, title: title, place: place, placeText: placeText, live: live,
    liveLabel: liveLabel, fill: fill, kindIcon: kindIcon, kindText: kindText, dur: dur, durText: durText,
    people: people, peopleKey: null, open: open, day: null, ev: null};
  open.addEventListener('click', function () {
    try {
      jarvis.emit('event_open', {day_id: n.day.id, event_id: n.ev.id});
    } catch (_error) {
      say('Jarvis a refusé l’action.');
    }
  });
  return n;
}

function paintPeople(n, people) {
  var list = (Array.isArray(people) ? people : []).slice(0, 4).map(String);
  var key = list.join('|');
  n.people.hidden = list.length === 0;
  if (n.peopleKey === key) return;
  n.peopleKey = key;
  while (n.people.firstChild) n.people.removeChild(n.people.firstChild);
  list.forEach(function (p, i) {
    var c = cxEl('span', 'tl-person', p.slice(0, 3).toUpperCase());
    c.style.setProperty('--pc', personTone(p));
    c.style.zIndex = String(10 - i);
    n.people.appendChild(c);
  });
  n.people.setAttribute('role', 'img');
  n.people.setAttribute('aria-label', 'Participants : ' + list.join(', '));
}

function paintEvent(n, day, ev, entry, order) {
  n.day = day; n.ev = ev;
  var k = KINDS[ev.kind] || KINDS.meeting;
  var s = parseTime(ev.start);
  var e = parseTime(ev.end);
  n.root.style.setProperty('--tone', k.tone);
  n.root.setAttribute('data-state', entry.state);
  if (entry.feature) n.root.setAttribute('data-feature', ''); else n.root.removeAttribute('data-feature');
  if (entry.soon) n.root.setAttribute('data-soon', ''); else n.root.removeAttribute('data-soon');
  n.start.textContent = s !== null ? clock(s) : String(ev.start || '');
  n.end.textContent = e !== null ? clock(e) : '';
  n.end.hidden = e === null;
  n.title.textContent = ev.title;
  n.placeText.textContent = ev.place || '';
  n.place.hidden = !ev.place;
  n.kindText.textContent = k.label;
  n.kindIcon.firstChild.setAttribute('d', ICONS[k.icon]);
  var dur = s !== null && e !== null ? (e < s ? e + 1440 : e) - s : 0;
  n.durText.textContent = dur > 0 ? fmtDur(dur) : '';
  n.dur.hidden = dur <= 0;
  n.live.hidden = !(entry.feature || entry.soon);
  n.liveLabel.textContent = entry.soon && entry.label ? 'Ensuite · ' + entry.label.charAt(0).toLowerCase() + entry.label.slice(1) : entry.label;
  n.fill.style.setProperty('--v', String(entry.feature ? entry.progress : 0));
  paintPeople(n, ev.people);
  var when = day.label + ' ' + day.date + ', ' + n.start.textContent + (n.end.textContent ? ' à ' + n.end.textContent : '');
  n.open.setAttribute('aria-label', 'Ouvrir : ' + ev.title + ', ' + when + (entry.label ? ', ' + entry.label : ''));
  n.root.style.setProperty('--i', String(Math.min(order, 12) + 2));
}

function render(context) {
  last = context;
  accent = context.props.accent || accent;
  $('tl').style.setProperty('--cx-acc', accent);
  var data = context.data || {};
  var events = Array.isArray(data.events) ? data.events : [];
  var days = (Array.isArray(data.days) ? data.days : []).map(function (day) {
    return {id: day.id, label: day.label, date: day.date, events: events.filter(function (ev) { return ev.day_id === day.id; }).slice(0, 8)};
  });
  var a = analyse(days, reference(context.props));
  $('tl-title').textContent = data.title || 'Ma semaine';
  $('tl-range').textContent = data.range || '';
  $('tl-range').hidden = !data.range;
  cxCount($('tl-n'), a.total, firstPaint ? 900 : 500);
  $('tl-n-cap').textContent = (a.total > 1 ? 'événements' : 'événement') +
    (a.todayIdx >= 0 && a.total ? ' · ' + a.ahead + ' à venir' : '');
  var seenDays = {};
  var seenEv = {};
  var order = 0;
  days.forEach(function (day, di) {
    var dn = dayNodes[day.id];
    if (!dn) dn = dayNodes[day.id] = buildDay();
    dn.day = day;
    dn.num.textContent = String(day.date);
    dn.lab.textContent = day.label;
    var state = a.todayIdx < 0 ? '' : di < a.todayIdx ? 'past' : di === a.todayIdx ? 'today' : 'future';
    if (state) dn.root.setAttribute('data-day', state); else dn.root.removeAttribute('data-day');
    dn.pill.hidden = state !== 'today';
    dn.root.setAttribute('aria-label', day.label + ' ' + day.date + (state === 'today' ? ', aujourd’hui' : ''));
    dn.root.style.setProperty('--i', String(Math.min(di, 6) + 1));
    seenDays[day.id] = true;
    var evs = Array.isArray(day.events) ? day.events : [];
    var keep = {};
    evs.forEach(function (ev, k) {
      var key = day.id + '/' + ev.id;
      var n = evNodes[key];
      if (!n) n = evNodes[key] = buildEvent();
      paintEvent(n, day, ev, a.info[key], order);
      order += 1;
      keep[key] = true; seenEv[key] = true;
      if (dn.list.children[k] !== n.root) dn.list.insertBefore(n.root, dn.list.children[k] || null);
    });
    Object.keys(evNodes).forEach(function (key) {
      if (key.indexOf(day.id + '/') === 0 && !keep[key]) {
        var r = evNodes[key].root;
        if (r.parentNode) r.parentNode.removeChild(r);
        delete evNodes[key];
      }
    });
    if (daysEl.children[di] !== dn.root) daysEl.insertBefore(dn.root, daysEl.children[di] || null);
  });
  Object.keys(dayNodes).forEach(function (id) {
    if (!seenDays[id]) {
      var r = dayNodes[id].root;
      if (r.parentNode) r.parentNode.removeChild(r);
      delete dayNodes[id];
    }
  });
  $('tl-empty').hidden = a.total > 0;
  firstPaint = false;
  if (clockTimer !== null) { clearInterval(clockTimer); clockTimer = null; }
  if (!context.props.now) clockTimer = setInterval(function () { if (last) render(last); }, 30000);
}

jarvis.on('init', render);
jarvis.on('update', render);
jarvis.on('event_result', function (result) {
  if (!result || result.outcome === 'applied') return;
  if (result.outcome === 'recorded') say('Ouverture demandée.');
  else say(result.outcome === 'failed' ? 'Jarvis est injoignable : action non enregistrée.' : 'Jarvis a refusé l’action.');
});
jarvis.on('teardown', function () {
  if (clockTimer !== null) clearInterval(clockTimer);
  if (noticeTimer !== null) clearTimeout(noticeTimer);
});
