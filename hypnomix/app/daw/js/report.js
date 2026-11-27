/* Reporting a problem, the DAW view's part: a link in the status bar to the app's report dialog (the dialog itself is the app's own
   page: it opens there with "#report"), and the page's own script errors, recorded on this computer like any crash (a few a minute at
   most, never a loop). Nothing is sent anywhere. */
(function () {
  'use strict';
  var foot = document.querySelector('footer.status');
  var link = document.createElement('a');
  link.id = 'hxReport'; link.href = '/#report'; link.className = 'status-report';
  link.textContent = 'Report a problem';
  link.title = 'Opens the app\'s report dialog: you see exactly what a report says, and send it yourself if you want to';
  if (foot) foot.appendChild(link);

  var stamps = [], lastKey = '';
  function pageError(message, source, line, stack) {
    try {
      var now = Date.now();
      while (stamps.length && now - stamps[0] > 60000) stamps.shift();
      var key = String(message) + '|' + source + '|' + line;
      if (stamps.length >= 3 || key === lastKey) return;
      lastKey = key; stamps.push(now);
      fetch('/api/crashes/page', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Hypnomix': window.HX_TOKEN || ''},
        body: JSON.stringify({message: String(message).slice(0, 500), source: String(source || '').slice(0, 200), line: Number(line) || 0,
                              stack: String(stack || '').slice(0, 2000), page: 'daw'})
      }).then(function (r) {
        if (r.ok) link.textContent = 'HypnoMix hit a bug: report it (a report was saved here; nothing was sent)';
      }).catch(function () { /* an error while reporting an error is only dropped */ });
    } catch (e) { /* nothing more to do */ }
  }
  window.addEventListener('error', function (e) {
    if (e.target && e.target !== window) return;
    pageError(e.message || 'script error', e.filename, e.lineno, e.error && e.error.stack);
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    if (r && r.name === 'AbortError') return;
    if (r instanceof TypeError && /fetch|network|load failed/i.test(String(r.message))) return;
    pageError((r && r.message) || String(r), '', 0, r && r.stack);
  });
})();
