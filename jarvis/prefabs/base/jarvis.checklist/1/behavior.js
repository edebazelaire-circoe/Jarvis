/* jarvis.checklist v1 : liste de contrôle (docs/prefabs.md › *Base catalogue*,
   *Structured inputs and events*). Tout texte passe par `textContent`.

   Cocher est immédiat : la ligne change tout de suite (état local), puis
   l'événement `item_toggled` (state, `{items}`) part vers Core, qui l'écrit
   dans les données de l'instance si la base que le cadre a vue est encore la
   bonne. Règles :
   - une seule écriture en vol. Les coches suivantes s'affichent aussitôt et
     partent ensemble, en un seul événement, quand Core a confirmé la
     précédente (sinon leur base serait déjà dépassée : `stale`) ;
   - confirmation = une mise à jour de l'hôte dont `items` est exactement la
     liste envoyée ;
   - toute autre mise à jour des données (Jarvis a remplacé la liste, ou
     l'écriture était `stale`) l'emporte : la liste de Core est affichée telle
     quelle et, si une coche n'a pas pu partir, une note le dit ;
   - sans confirmation en `CONFIRM_MS` (refus, débit, Core injoignable) : retour
     à la dernière liste de Core, et une note le dit ;
   - `checklist_completed` (notify, `{count}`) part quand une coche de
     l'utilisateur, confirmée par Core, fait passer la liste d'incomplète à
     complète. Décocher puis recocher est une nouvelle complétion : elle
     repart. Une liste déjà complète reçue de Jarvis, ou une mise à jour
     pendant qu'elle l'est, n'envoie rien.
   Clavier : un seul arrêt de tabulation dans la liste (Tab y entre) ; flèches
   haut/bas, Début, Fin déplacent le focus ; Espace coche. Les lignes sont des
   `role="checkbox"` avec `aria-checked`. Les écouteurs sont posés une fois sur
   la liste (délégation) et les lignes sont réutilisées par position : une
   mise à jour ne recrée ni écouteur ni ligne existante. */
var root = document.getElementById('ck');
var progress = document.getElementById('ck-progress');
var track = document.getElementById('ck-track');
var fill = document.getElementById('ck-fill');
var count = document.getElementById('ck-count');
var list = document.getElementById('ck-list');
var empty = document.getElementById('ck-empty');
var notice = document.getElementById('ck-notice');

var CONFIRM_MS = 5000;
var NOTICE_MS = 6000;

var confirmed = [];   /* dernière liste reçue de Core */
var local = [];       /* ce que l'utilisateur voit */
var inflight = null;  /* liste envoyée, en attente de confirmation */
var confirmTimer = null;
var noticeTimer = null;
var showProgress = true;
var focused = 0;
var rows = [];
var serial = 0;

function show(el, on) {
  if (on) el.removeAttribute('hidden');
  else el.setAttribute('hidden', '');
}

function element(tag, className) {
  var el = document.createElement(tag);
  if (className) el.className = className;
  return el;
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

function setAttr(el, name, value) {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value);
}

/* Clés triées : Core et le cadre n'ordonnent pas forcément les clés pareil. */
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    var out = {};
    Object.keys(value).sort().forEach(function (key) { out[key] = canonical(value[key]); });
    return out;
  }
  return value;
}

function same(a, b) {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

/* `done` toujours explicite : la scène garde les données d'une instance telles
   que Jarvis les a écrites (sans défaut), alors qu'une écriture d'état stocke la
   fusion complétée des défauts. Envoyer `done` partout fait revenir de Core
   exactement la liste envoyée, ce qui confirme la coche. */
function itemsOf(data) {
  var items = data && Array.isArray(data.items) ? data.items : [];
  return items.filter(function (item) { return item && typeof item === 'object'; })
    .map(function (item) {
      var copy = JSON.parse(JSON.stringify(item));
      copy.done = copy.done === true;
      return copy;
    });
}

function doneCount(items) {
  return items.filter(function (item) { return item.done === true; }).length;
}

function complete(items) {
  return items.length > 0 && doneCount(items) === items.length;
}

function cancelConfirm() {
  if (confirmTimer !== null) clearTimeout(confirmTimer);
  confirmTimer = null;
}

function say(text) {
  setText(notice, text);
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(function () { noticeTimer = null; setText(notice, ''); }, NOTICE_MS);
}

/* ------------------------------------------------------------ dessin */

function makeRow() {
  serial += 1;
  var row = element('div', 'ck-item');
  row.setAttribute('role', 'checkbox');
  row.setAttribute('tabindex', '-1');
  row.setAttribute('aria-checked', 'false');
  var box = element('span', 'ck-box');
  box.setAttribute('aria-hidden', 'true');
  var main = element('span', 'ck-main');
  var label = element('span', 'ck-label');
  label.setAttribute('id', 'ck-label-' + serial);
  var note = element('span', 'ck-note');
  note.setAttribute('id', 'ck-note-' + serial);
  note.setAttribute('hidden', '');
  row.setAttribute('aria-labelledby', 'ck-label-' + serial);
  main.appendChild(label);
  main.appendChild(note);
  row.appendChild(box);
  row.appendChild(main);
  return {row: row, label: label, note: note};
}

function paintRow(entry, item, index) {
  var note = typeof item.note === 'string' ? item.note : '';
  setAttr(entry.row, 'data-index', String(index));
  setAttr(entry.row, 'aria-checked', item.done === true ? 'true' : 'false');
  setAttr(entry.row, 'tabindex', index === focused ? '0' : '-1');
  setText(entry.label, typeof item.label === 'string' ? item.label : '');
  setText(entry.note, note);
  show(entry.note, note !== '');
  if (note) setAttr(entry.row, 'aria-describedby', entry.note.getAttribute('id'));
  else if (entry.row.hasAttribute('aria-describedby')) entry.row.removeAttribute('aria-describedby');
}

function paint() {
  var total = local.length;
  var focusWasInside = false;
  while (rows.length < total) {
    var made = makeRow();
    rows.push(made);
    list.appendChild(made.row);
  }
  while (rows.length > total) {
    var gone = rows.pop();
    if (document.activeElement === gone.row) focusWasInside = true;
    gone.row.remove();
  }
  if (focused >= total) focused = Math.max(0, total - 1);
  local.forEach(function (item, index) { paintRow(rows[index], item, index); });
  if (focusWasInside && rows[focused]) rows[focused].row.focus();

  var done = doneCount(local);
  show(empty, total === 0);
  show(progress, showProgress && total > 0);
  fill.style.setProperty('--ck-ratio', String(total ? done / total : 0));
  setAttr(track, 'aria-valuemax', String(total));
  setAttr(track, 'aria-valuenow', String(done));
  setAttr(track, 'aria-valuetext', done + ' sur ' + total + ' cochés');
  setText(count, complete(local) ? 'Terminé · ' + done + '/' + total : done + '/' + total);
  if (complete(local)) setAttr(root, 'data-complete', '');
  else if (root.hasAttribute('data-complete')) root.removeAttribute('data-complete');
}

/* ------------------------------------------------------------ écriture */

function send() {
  var items = JSON.parse(JSON.stringify(local));
  try {
    jarvis.emit('item_toggled', {items: items});
  } catch (error) {
    /* Le shim refuse une charge de plus de 8 Kio : rien n'est parti. */
    local = JSON.parse(JSON.stringify(confirmed));
    say('Coche non enregistrée : ' + (error && error.message ? error.message : String(error)) + '.');
    paint();
    return;
  }
  inflight = items;
  cancelConfirm();
  confirmTimer = setTimeout(function () {
    confirmTimer = null;
    if (inflight === null) return;
    inflight = null;
    local = JSON.parse(JSON.stringify(confirmed));
    say('Coche non enregistrée : Jarvis n’a pas confirmé. Réessayez.');
    paint();
  }, CONFIRM_MS);
}

function toggle(index) {
  if (index < 0 || index >= local.length) return;
  local = JSON.parse(JSON.stringify(local));
  local[index].done = local[index].done !== true;
  paint();
  if (inflight === null) send();
}

/* ------------------------------------------------------------ données de Core */

function receive(items) {
  if (inflight !== null && same(items, inflight)) {
    var before = confirmed;
    confirmed = items;
    inflight = null;
    cancelConfirm();
    if (!complete(before) && complete(confirmed)) jarvis.emit('checklist_completed', {count: confirmed.length});
    if (same(local, confirmed)) local = JSON.parse(JSON.stringify(confirmed));
    else send();
    return;
  }
  var lost = inflight !== null || !same(local, confirmed);
  confirmed = items;
  local = JSON.parse(JSON.stringify(items));
  inflight = null;
  cancelConfirm();
  if (lost) say('La liste a changé entre-temps : votre dernière coche n’a pas été enregistrée.');
}

function render(context) {
  showProgress = context.props.show_progress !== false;
  if (!context.changed || context.changed.data) receive(itemsOf(context.data));
  paint();
}

/* ------------------------------------------------------------ souris et clavier */

function indexOf(node) {
  while (node && node !== list) {
    if (node.getAttribute && node.getAttribute('role') === 'checkbox') return Number(node.getAttribute('data-index'));
    node = node.parentNode;
  }
  return -1;
}

function moveFocus(index) {
  if (!rows.length) return;
  var next = Math.max(0, Math.min(rows.length - 1, index));
  if (rows[focused]) rows[focused].row.setAttribute('tabindex', '-1');
  focused = next;
  var row = rows[next].row;
  row.setAttribute('tabindex', '0');
  if (typeof row.focus === 'function') row.focus();
  if (typeof row.scrollIntoView === 'function') row.scrollIntoView({block: 'nearest'});
}

list.addEventListener('click', function (event) {
  var index = indexOf(event.target);
  if (index < 0) return;
  moveFocus(index);
  toggle(index);
});

list.addEventListener('keydown', function (event) {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  var index = indexOf(event.target);
  if (index < 0) index = focused;
  var key = event.key;
  if (key === ' ' || key === 'Spacebar') toggle(index);
  else if (key === 'ArrowDown') moveFocus(index + 1);
  else if (key === 'ArrowUp') moveFocus(index - 1);
  else if (key === 'Home') moveFocus(0);
  else if (key === 'End') moveFocus(rows.length - 1);
  else return;
  event.preventDefault();
});

jarvis.on('init', render);
jarvis.on('update', render);
jarvis.on('teardown', function () {
  cancelConfirm();
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = null;
});
