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
