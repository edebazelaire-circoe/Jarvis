/* jarvis.window v1 : corps markdown (liaison `data-jv-markdown`, blocs de
   l'hôte) et entrées. Tout texte passe par `textContent` ; une entrée liée ne
   porte pas de `href` et s'ouvre par `jarvis.openUrl` (l'hôte valide l'URL). */
var root = document.getElementById('win');
var body = document.getElementById('win-body');
var list = document.getElementById('win-items');
var empty = document.getElementById('win-empty');

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

function hostOf(url) {
  var match = /^https?:\/\/(?:[^@/?#]*@)?([^/?#:]+)/i.exec(url);
  return match ? match[1].replace(/^www\./i, '').toLowerCase() : '';
}

function linkRow(row, item) {
  var host = hostOf(item.url);
  var link = element('span', 'win-link');
  link.setAttribute('role', 'link');
  link.setAttribute('tabindex', '0');
  link.setAttribute('title', item.url);
  link.setAttribute('aria-label', (item.label || host) + ' — ' + host + ', s’ouvre dans un nouvel onglet');
  if (host) link.appendChild(element('span', 'win-host', host));
  link.appendChild(element('span', 'win-label', item.label));
  var out = element('span', 'win-out');
  out.setAttribute('aria-hidden', 'true');
  link.appendChild(out);
  link.addEventListener('click', function (event) {
    event.preventDefault();
    jarvis.openUrl(item.url);
  });
  link.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    jarvis.openUrl(item.url);
  });
  row.appendChild(link);
}

function itemRow(item) {
  var row = element('li', 'win-item');
  var main = element('span', 'win-main');
  row.appendChild(main);
  if (item.url) linkRow(main, item);
  else main.appendChild(element('span', 'win-label', item.label));
  if (item.ref) row.appendChild(element('span', 'win-ref', item.ref));
  return row;
}

function render(context) {
  var items = Array.isArray(context.data.items) ? context.data.items : [];
  var hasBody = jarvis.blocks('data.body').length > 0;
  root.setAttribute('data-density', context.props.density === 'compact' ? 'compact' : 'comfortable');
  show(body, hasBody);
  list.replaceChildren();
  items.forEach(function (item) { list.appendChild(itemRow(item)); });
  show(list, items.length > 0);
  show(empty, !hasBody && items.length === 0);
}

jarvis.on('init', render);
jarvis.on('update', render);
