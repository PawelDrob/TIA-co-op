// The theme of a page, light or dark: the system setting until the viewer presses the icon in the top bar (.top).
//
// This script stands in the head and holds the page up, so the choice is on <html> before anything is drawn. It is kept in a
// cookie: unlike localStorage a cookie is the same for every port of a host, so both dashboards follow one choice; a tab
// already open takes it when it is shown again or gets focus. Where the browser blocks it the icon still switches this
// page, and nothing is remembered.
(function () {
  var COOKIE = 'dashboard-theme', SAVED = new RegExp('(?:^|;\\s*)' + COOKIE + '=(light|dark)'), A_YEAR = 365 * 24 * 3600;
  var SVG_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"' +
             ' stroke-linejoin="round" aria-hidden="true">';
  var ICONS = {     // of the theme it switches to
    light: SVG_OPEN + '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4' +
           'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    dark: SVG_OPEN + '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z"/></svg>'
  };
  var root = document.documentElement, system = window.matchMedia('(prefers-color-scheme: dark)');

  function saved() {
    try {
      var m = SAVED.exec(document.cookie);
      return m && m[1];
    } catch (e) {
      return null;
    }
  }
  function remember(theme) {
    try {
      document.cookie = COOKIE + '=' + theme + '; path=/; max-age=' + A_YEAR + '; samesite=lax';
    } catch (e) { /* blocked: this page still switches */ }
  }
  function current() {
    return root.dataset.theme || (system.matches ? 'dark' : 'light');
  }
  function other() {
    return current() === 'dark' ? 'light' : 'dark';
  }

  function follow() {
    var choice = saved();
    if (choice) root.dataset.theme = choice;
  }
  follow();

  document.addEventListener('DOMContentLoaded', function () {
    var top = document.querySelector('.top');
    if (!top) return;
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'theme';
    function show() {
      var label = 'Switch to ' + other() + ' mode';
      button.innerHTML = ICONS[other()];
      button.title = label;
      button.setAttribute('aria-label', label);
    }
    button.addEventListener('click', function () {
      root.dataset.theme = other();
      remember(root.dataset.theme);
      show();
    });
    system.addEventListener('change', show);       // still on the system setting: the icon follows it
    function again() {                             // a choice made in another tab or the other dashboard
      if (document.hidden) return;
      follow();
      show();
    }
    document.addEventListener('visibilitychange', again);
    window.addEventListener('focus', again);
    show();
    top.appendChild(button);
  });
})();

// The live connection of a dashboard page. The server pushes an "update" event (Server-Sent Events) when something
// this page shows has changed, and one when the connection opens.
//
// A browser keeps about six connections per site open over HTTP/1.1, so a page that sets stopWhenHidden holds none
// while its tab is hidden and catches up when it is shown. The start page stays connected: its tab title says what waits
// while another tab is in front, and nothing else tells you that a new review page has come.
function dashboardLive(url, onUpdate, stopWhenHidden) {
  var source = null, retry = null;

  function show(text, failed) {
    var el = document.getElementById('live');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('fail', failed);
  }
  function stop() {
    clearTimeout(retry);
    if (source) { source.close(); source = null; }
  }
  function start() {
    stop();
    source = new EventSource(url);
    source.addEventListener('update', function (e) {
      var data = JSON.parse(e.data);
      show(data.updated ? 'Live, updated ' + data.updated : 'Live', false);
      onUpdate(data);
    });
    source.onerror = function () {             // also a 502 from a proxy, on which EventSource would give up by itself
      stop();
      show('Disconnected, retrying', true);
      retry = setTimeout(start, 2000);
    };
  }
  if (stopWhenHidden) {
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop(); else start();
    });
    if (document.hidden) return;
  }
  start();
}

// Start page: swaps only the parts that changed, so scroll position stays as it is. A folded list stays open by its id:
// every <details> on a live page needs an id that is its own and does not change. One not seen before starts closed.
// An area with data-scroll and an id keeps its place, and focus stays on what has an id, also when a part around them is
// swapped. after, when given, runs after each update.
function dashboardBoard(after) {
  dashboardLive('/events?start=1', function (data) {
    var scroll = {}, focus = document.activeElement && document.activeElement.id;
    Array.prototype.forEach.call(document.querySelectorAll('[data-scroll][id]'), function (s) { scroll[s.id] = s.scrollTop; });
    Object.keys(data.parts).forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || el.dataset.html === data.parts[id]) return;
      var open = {};
      Array.prototype.forEach.call(el.querySelectorAll('details[id]'), function (d) { if (d.open) open[d.id] = true; });
      el.innerHTML = data.parts[id];
      el.dataset.html = data.parts[id];
      Array.prototype.forEach.call(el.querySelectorAll('details[id]'), function (d) { d.open = open[d.id] === true; });
    });
    if (after) after();          // first: what it shows again can then take its place back
    Array.prototype.forEach.call(document.querySelectorAll('[data-scroll][id]'), function (s) {
      if (scroll[s.id]) s.scrollTop = scroll[s.id];
    });
    if (focus && focus !== (document.activeElement && document.activeElement.id) && document.getElementById(focus)) {
      document.getElementById(focus).focus({preventScroll: true});
    }
    document.title = data.title;
  }, false);
}

// Document page: shows the new text when the file changes; the browser keeps the scroll position over a reload.
function dashboardDoc(rel, seen) {
  dashboardLive('/events?doc=' + encodeURIComponent(rel), function (data) {
    if (data.stamp !== seen) location.reload();
  }, true);
}
