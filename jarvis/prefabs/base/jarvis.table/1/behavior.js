/* jarvis.table v1 : en-tête, lignes, sélection. Une ligne se choisit au clic
   ou au clavier (Entrée, Espace) ; flèches haut/bas, Début et Fin déplacent le
   focus (un seul arrêt de tabulation dans le tableau). Choisir une autre ligne
   envoie l'événement `row_selected` (notify, `{index}`) : Jarvis le lit au
   prochain tour, rien n'est écrit. Tout texte passe par `textContent`. */
var table = document.getElementById('tbl');
var head = document.getElementById('tbl-head');
var body = document.getElementById('tbl-body');
var empty = document.getElementById('tbl-empty');
var foot = document.getElementById('tbl-foot');
var ALIGNS = {left: true, right: true, center: true};
var SHORT_CELL = 16; /* caractères : en deçà, la cellule reste sur une ligne */
var selected = -1;
var focused = 0;
var count = 0;

function show(el, on) {
  if (on) el.removeAttribute('hidden');
  else el.setAttribute('hidden', '');
}

function element(tag, className, text) {
  var el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function rowAt(index) {
  return body.children[index] || null;
}

function plural(n, one, many) {
  return n + ' ' + (n > 1 ? many : one);
}

function describe(columns) {
  var text = plural(count, 'ligne', 'lignes') + ' · ' + plural(columns, 'colonne', 'colonnes');
  if (selected >= 0) text += ' · ligne ' + (selected + 1) + ' choisie';
  foot.textContent = text;
}

function moveFocus(index, scroll) {
  if (!count) return;
  var next = Math.max(0, Math.min(count - 1, index));
  var previous = rowAt(focused);
  if (previous) previous.setAttribute('tabindex', '-1');
  focused = next;
  var row = rowAt(next);
  row.setAttribute('tabindex', '0');
  if (typeof row.focus === 'function') row.focus();
  if (scroll && typeof row.scrollIntoView === 'function') row.scrollIntoView({block: 'nearest'});
}

function select(index) {
  if (index < 0 || index >= count) return;
  var changed = index !== selected;
  var previous = rowAt(selected);
  if (previous) previous.setAttribute('aria-selected', 'false');
  selected = index;
  rowAt(index).setAttribute('aria-selected', 'true');
  describe(head.children.length);
  if (changed) jarvis.emit('row_selected', {index: index});
}

function onKey(index, event) {
  var key = event.key;
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  if (key === 'Enter' || key === ' ') select(index);
  else if (key === 'ArrowDown') moveFocus(index + 1, true);
  else if (key === 'ArrowUp') moveFocus(index - 1, true);
  else if (key === 'Home') moveFocus(0, true);
  else if (key === 'End') moveFocus(count - 1, true);
  else return;
  event.preventDefault();
}

/* Texte long : des coupures possibles après `/ \ : ? & =` (`<wbr>`), pour
   qu'un chemin ou une URL passe à la ligne entre ses segments au lieu
   d'élargir sa colonne ou d'être coupé au milieu d'un nom. */
function fillBreakable(cell, text) {
  var parts = text.split(/([\/\\:?&=]+)/);
  for (var i = 0; i < parts.length; i++) {
    if (!parts[i]) continue;
    cell.appendChild(document.createTextNode(parts[i]));
    if (i % 2 === 1) cell.appendChild(document.createElement('wbr'));
  }
}

function bodyRow(cells, columns, index) {
  var row = element('tr');
  row.setAttribute('role', 'row');
  row.setAttribute('aria-selected', index === selected ? 'true' : 'false');
  row.setAttribute('tabindex', index === focused ? '0' : '-1');
  columns.forEach(function (column, at) {
    var text = typeof cells[at] === 'string' ? cells[at] : '';
    var cell = element('td');
    cell.setAttribute('role', 'gridcell');
    if (text.length <= SHORT_CELL) {
      cell.setAttribute('data-short', '');
      cell.textContent = text;
    } else {
      fillBreakable(cell, text);
    }
    cell.setAttribute('data-align', column.align);
    row.appendChild(cell);
  });
  row.addEventListener('click', function () {
    moveFocus(index, false);
    select(index);
  });
  row.addEventListener('keydown', function (event) { onKey(index, event); });
  return row;
}

function render(context) {
  var columns = (Array.isArray(context.data.columns) ? context.data.columns : []).map(function (column) {
    return {label: String(column.label || ''), align: ALIGNS[column.align] ? column.align : 'left'};
  });
  var rows = Array.isArray(context.data.rows) ? context.data.rows : [];
  count = rows.length;
  if (selected >= count) selected = -1;
  if (focused >= count) focused = 0;
  table.setAttribute('data-zebra', context.props.zebra === false ? '0' : '1');
  head.replaceChildren();
  columns.forEach(function (column) {
    var cell = element('th', 'jv-label', column.label);
    cell.setAttribute('role', 'columnheader');
    cell.setAttribute('scope', 'col');
    cell.setAttribute('data-align', column.align);
    head.appendChild(cell);
  });
  body.replaceChildren();
  rows.forEach(function (cells, index) {
    body.appendChild(bodyRow(Array.isArray(cells) ? cells : [], columns, index));
  });
  show(empty, count === 0);
  describe(columns.length);
}

jarvis.on('init', render);
jarvis.on('update', render);
