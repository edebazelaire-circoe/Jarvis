/* jarvis.window v1 : corps markdown (liaison `data-jv-markdown`, blocs de
   l'hôte) et entrées. Tout texte passe par `textContent` ; une entrée liée ne
   porte pas de `href` et s'ouvre par `jarvis.openUrl` (l'hôte valide l'URL).

   Mise en page de `.sc-window` (voir style.css) : `.win` remplit le cadre, et
   `.win-sizer` donne au document la hauteur naturelle du contenu, celle que
   le shim rapporte à l'hôte. `layout()` la remesure à chaque rendu et à chaque
   changement de taille du cadre, et pose `data-clamped` quand le cadre est
   plus court que le contenu (les entrées sont alors plafonnées, style.css) ;
   `fades()` pose `data-more` sur le corps et la liste tant qu'il leur reste
   du contenu sous le bord. */
var root = document.getElementById('win');
var body = document.getElementById('win-body');
var list = document.getElementById('win-items');
var empty = document.getElementById('win-empty');
var sizer = document.getElementById('win-sizer');

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

function flag(el, name, on) {
  if (on) el.setAttribute(name, '');
  else el.removeAttribute(name);
}

/* Encore du contenu sous le bord : fondu, comme `.sc-summary` et `.sc-items`. */
function fades() {
  [body, list].forEach(function (part) {
    var rest = (part.scrollHeight || 0) - (part.clientHeight || 0) - (part.scrollTop || 0);
    flag(part, 'data-more', !part.hasAttribute('hidden') && rest > 2);
  });
}

/* Hauteur naturelle : chaque partie visible à sa taille de contenu, lue le
   temps d'une mesure (`data-measure` lève `flex` et `max-height`). */
function layout() {
  flag(root, 'data-measure', true);
  var total = 0;
  var bodyNatural = 0;
  [body, list, empty].forEach(function (part) {
    if (part.hasAttribute('hidden')) return;
    var height = part.offsetHeight || 0;
    if (part === body) bodyNatural = height;
    total += height;
  });
  flag(root, 'data-measure', false);
  sizer.style.height = Math.ceil(total) + 'px';
  root.style.setProperty('--win-body-natural', Math.ceil(bodyNatural) + 'px');
  flag(root, 'data-clamped', total > (root.clientHeight || 0) + 1);
  fades();
}

body.addEventListener('scroll', fades, {passive: true});
list.addEventListener('scroll', fades, {passive: true});
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('resize', layout);
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
  layout();
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(layout);
}

jarvis.on('init', render);
jarvis.on('update', render);
