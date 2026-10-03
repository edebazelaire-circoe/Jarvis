/* jarvis.document v1 : le texte (liaison `data-jv-markdown`, blocs de l'hôte),
   l'échelle, la position de lecture et la pagination au clavier quand le cadre
   a le focus : Page haut / Page bas (85 % de la hauteur visible, comme la
   fenêtre classique), Début, Fin. Le cadre défile lui-même : la fenêtre le
   borne à sa hauteur. */
var doc = document.getElementById('doc');
var track = document.getElementById('doc-track');
var bar = document.getElementById('doc-progress');
var empty = document.getElementById('doc-empty');
var scroller = document.scrollingElement || document.documentElement;
var SCALES = {s: true, m: true, l: true};

function show(el, on) {
  if (on) el.removeAttribute('hidden');
  else el.setAttribute('hidden', '');
}

function progress() {
  var range = (scroller.scrollHeight || 0) - (scroller.clientHeight || 0);
  var scrollable = range > 1;
  var ratio = scrollable ? Math.min(1, Math.max(0, (scroller.scrollTop || 0) / range)) : 0;
  track.setAttribute('data-on', scrollable ? '1' : '0');
  bar.style.transform = 'scaleX(' + ratio.toFixed(4) + ')';
}

function target(key) {
  var top = scroller.scrollTop || 0;
  var step = Math.max(20, Math.round((scroller.clientHeight || 0) * 0.85));
  var end = Math.max(0, (scroller.scrollHeight || 0) - (scroller.clientHeight || 0));
  if (key === 'PageDown') return Math.min(end, top + step);
  if (key === 'PageUp') return Math.max(0, top - step);
  if (key === 'Home') return 0;
  if (key === 'End') return end;
  return null;
}

document.addEventListener('keydown', function (event) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  var next = target(event.key);
  if (next === null) return;
  event.preventDefault();
  scroller.scrollTop = next;
  progress();
});
document.addEventListener('scroll', progress, {passive: true});
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('resize', progress);
}

function render(context) {
  var hasBody = jarvis.blocks('data.body').length > 0;
  doc.setAttribute('data-scale', SCALES[context.props.scale] ? context.props.scale : 'm');
  show(doc, hasBody);
  show(empty, !hasBody);
  progress();
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(progress);
}

jarvis.on('init', render);
jarvis.on('update', render);
