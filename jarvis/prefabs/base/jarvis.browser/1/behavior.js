/* jarvis.browser v1 : surface de navigation en présentation. Le cadre n'a pas
   de réseau : il montre la page courante (hôte, adresse, notes), la position
   dans l'historique, le zoom et le défilement, et laisse l'utilisateur
   l'ouvrir dans un onglet (`jarvis.openUrl`, l'hôte valide l'URL). Tout texte
   passe par `textContent`. Les données sont celles que Core a validées ;
   l'état de navigation (historique, index, zoom, défilement) est écrit par
   l'outil de surface, jamais par ce comportement. */
var root = document.getElementById('brw');
var bar = document.getElementById('brw-bar');
var nav = document.getElementById('brw-nav');
var zoomBadge = document.getElementById('brw-zoom');
var page = document.getElementById('brw-page');
var hostEl = document.getElementById('brw-host');
var urlEl = document.getElementById('brw-url');
var openEl = document.getElementById('brw-open');
var body = document.getElementById('brw-body');
var empty = document.getElementById('brw-empty');
var current = null;
var scrollPercent = 0;

function show(el, on) {
  if (on) el.removeAttribute('hidden');
  else el.setAttribute('hidden', '');
}

function hostOf(url) {
  var match = /^https?:\/\/(?:[^@/?#]*@)?([^/?#:]+)/i.exec(url);
  return match ? match[1].replace(/^www\./i, '').toLowerCase() : '';
}

function applyScroll() {
  var room = Math.max(0, (page.scrollHeight || 0) - (page.clientHeight || 0));
  page.scrollTop = Math.round(room * scrollPercent / 100);
}

function open() {
  if (current) jarvis.openUrl(current.url);
}

openEl.addEventListener('click', function (event) {
  event.preventDefault();
  open();
});
openEl.addEventListener('keydown', function (event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  open();
});

function render(context) {
  var data = context.data || {};
  var history = Array.isArray(data.history) ? data.history : [];
  var index = Math.min(Math.max(0, data.index || 0), Math.max(0, history.length - 1));
  var zoom = typeof data.zoom === 'number' ? data.zoom : 100;
  current = history.length > 0 ? history[index] : null;
  scrollPercent = typeof data.scroll === 'number' ? data.scroll : 0;
  root.style.setProperty('--brw-zoom', String(zoom / 100));
  show(empty, current === null);
  show(page, current !== null);
  show(bar, current !== null);
  if (current !== null) {
    var host = hostOf(current.url);
    hostEl.textContent = current.label || host;
    urlEl.textContent = current.url;
    openEl.setAttribute('aria-label', 'Ouvrir ' + host + ' dans un nouvel onglet');
    nav.textContent = (index + 1) + ' / ' + history.length;
    nav.setAttribute('data-back', index > 0 ? 'on' : 'off');
    nav.setAttribute('data-forward', index < history.length - 1 ? 'on' : 'off');
    zoomBadge.textContent = zoom + ' %';
    zoomBadge.setAttribute('data-zoomed', zoom === 100 ? 'off' : 'on');
    show(body, jarvis.blocks('data.body').length > 0);
  }
  applyScroll();
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(applyScroll);
}

jarvis.on('init', render);
jarvis.on('update', render);
