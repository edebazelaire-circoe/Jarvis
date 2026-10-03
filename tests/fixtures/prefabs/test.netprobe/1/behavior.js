var results = [];

function note(name, outcome, detail) {
  var list = document.getElementById('probe-results');
  var item = document.createElement('li');
  item.setAttribute('data-probe', name);
  item.setAttribute('data-outcome', outcome);
  item.textContent = name + ': ' + outcome + (detail ? ' (' + detail + ')' : '');
  list.appendChild(item);
  results.push({ name: name, outcome: outcome, detail: detail || '' });
  window.__probeResults = results;
}

document.addEventListener('securitypolicyviolation', function (event) {
  note('csp-violation', 'blocked', event.violatedDirective + ' ' + event.blockedURI);
});

jarvis.on('init', function () {
  try {
    fetch('https://example.com/probe').then(function () {
      note('fetch', 'allowed');
    }, function (error) {
      note('fetch', 'blocked', error.name);
    });
  } catch (error) {
    note('fetch', 'blocked', 'threw ' + error.name);
  }
  try {
    var title = parent.document.title;
    note('parent.document', 'allowed', String(title));
  } catch (error) {
    note('parent.document', 'blocked', error.name);
  }
  try {
    window.localStorage.getItem('probe');
    note('localStorage', 'allowed');
  } catch (error) {
    note('localStorage', 'blocked', error.name);
  }
  try {
    var popup = window.open('https://example.com/popup');
    note('window.open', popup ? 'allowed' : 'blocked', popup ? '' : 'returned null');
  } catch (error) {
    note('window.open', 'blocked', error.name);
  }
  try {
    var evaluated = (0, eval)('1 + 1');
    note('eval', 'allowed', String(evaluated));
  } catch (error) {
    note('eval', 'blocked', error.name);
  }
  jarvis.emit('probed', { count: results.length });
  if (jarvis.props.crash) {
    throw new Error('netprobe crash requested');
  }
});
