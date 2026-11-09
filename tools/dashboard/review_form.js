// The forms of the dashboard. A review page: an answer box under each question (.ask li) and a Send button, added when the page is served
// (review_server.py). seen is the stamp of the page as it was served: a page rebuilt since reloads itself.
function reviewForm(seen) {
  var page = decodeURIComponent(location.pathname.split('/').pop());
  var main = document.querySelector('main') || document.body;
  var top = document.createElement('div'); top.className = 'top';
  top.innerHTML = '<a href="/">All reviews and tickets</a><span class="live" id="live"></span>';
  main.prepend(top);
  var asks = Array.prototype.slice.call(document.querySelectorAll('.ask li'));
  var sec = document.querySelector('.ask') || (function () {
    var s = document.createElement('section'); s.className = 'ask'; s.innerHTML = '<h2>Answers</h2>';
    main.insertBefore(s, main.children[2] || null); return s; })();
  var boxes = asks.map(function (li) {
    var t = document.createElement('textarea'); t.className = 'answer'; t.placeholder = 'Your answer';
    t.setAttribute('aria-label', li.firstChild.textContent);
    li.appendChild(t); return t; });
  var comment = document.createElement('textarea'); comment.className = 'answer';
  comment.placeholder = 'Anything else for the agent (optional)';
  comment.setAttribute('aria-label', 'Anything else for the agent');
  var btn = document.createElement('button'); btn.id = 'review-submit'; btn.textContent = 'Send answers';
  var state = document.createElement('span'); state.id = 'review-state'; state.setAttribute('role', 'status');
  sec.appendChild(comment); sec.appendChild(btn); sec.appendChild(state);

  function question(i) { return asks[i].firstChild.textContent; }
  function blankOnes() {
    return boxes.map(function (t, i) { return t.value.trim() ? -1 : i; }).filter(function (i) { return i >= 0; });
  }

  fetch('/answers/' + encodeURIComponent(page.replace(/\.html$/, '.json'))).then(function (r) {
    return r.ok ? r.json() : null; }).then(function (a) {
    if (!a) return;
    if (!asks.length && !(a.comment || '').trim()) return;   // as on the start page: nothing here is answered, it is to read
    var byQ = {}; a.answers.forEach(function (x) { byQ[x.question] = x.answer; });
    asks.forEach(function (li, i) { if (question(i) in byQ) boxes[i].value = byQ[question(i)]; });
    var left = blankOnes().length;
    var same = asks.some(function (li, i) { return question(i) in byQ; });   // answers to other questions keep their comment out
    if (same || !asks.length) comment.value = a.comment || '';
    if (!left) state.textContent = 'Answered ' + a.at;
    else if (same) state.textContent = 'Sent ' + a.at + ', ' + left + ' still blank: this page keeps waiting';
    else state.textContent = 'Earlier answers (' + a.at + ') were to other questions'; });

  var sent = false, warned = '';
  btn.onclick = function () {
    var blank = blankOnes();
    if (blank.length === asks.length && !comment.value.trim()) {
      state.textContent = 'Not sent: nothing is written.';
      (boxes[0] || comment).focus();
      return;
    }
    // a blank answer is no answer: said before it goes, and sent only when asked again with the same ones blank
    var names = blank.map(function (i) { return '"' + question(i) + '"'; }).join(', ');
    if (names && names !== warned) {
      warned = names;
      state.textContent = 'Not sent: blank are ' + names + '. Send again to send the rest; this page then keeps waiting for those.';
      boxes[blank[0]].focus();
      return;
    }
    var body = { title: document.title, comment: comment.value,
      answers: asks.map(function (li, i) { return { question: question(i), answer: boxes[i].value }; }) };
    state.textContent = 'Sending...';
    fetch('/answer/' + encodeURIComponent(page), { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r.ok) { state.textContent = 'Not sent: ' + r.error; return; }
      if (blank.length) { state.textContent = 'Sent ' + r.at + ', ' + blank.length + ' still blank: this page keeps waiting.'; return; }
      sent = true;
      state.textContent = 'Sent ' + r.at + '. The agent has it. Back to the dashboard...';
      setTimeout(function () { location.href = '/'; }, 1500); },
      function (e) { state.textContent = 'Not sent: ' + e; });
  };

  // a rebuilt page reloads itself, unless something is typed: then a note says so
  dashboardLive('/events?page=' + encodeURIComponent(page), function (v) {
    if (v.stamp === seen || sent) return;
    var typed = boxes.concat([comment]).some(function (t) { return t.value.trim(); });
    if (v.stamp !== null && !typed) { location.reload(); return; }
    var note = document.getElementById('review-updated') || document.createElement('p');
    note.id = 'review-updated';
    note.textContent = v.stamp === null ? 'This page was taken down. Copy what you typed before you leave it.'
      : 'This page was updated since you opened it. Copy what you typed, then reload.';
    main.insertBefore(note, top.nextSibling);
  }, true);
}

// The answer box of a ticket that asks you something, on the ticket's page (review_server.py). rel is the ticket's file, asked
// its question as the page shows it and seen the ticket's stamp then: the server refuses an answer to a question changed since.
// A ticket changed since reloads the page, unless something is typed: then a note says so.
function ticketForm(rel, asked, seen) {
  var sec = document.getElementById('ticket-ask');
  var question = sec.querySelector('.question');
  if (window.marked) question.innerHTML = marked.parse(asked);
  var box = document.createElement('textarea'); box.className = 'answer'; box.id = 'ticket-answer';
  box.placeholder = 'Your answer'; box.setAttribute('aria-label', 'Your answer');
  var btn = document.createElement('button'); btn.id = 'review-submit'; btn.textContent = 'Send answer';
  var state = document.createElement('span'); state.id = 'review-state'; state.setAttribute('role', 'status');
  sec.appendChild(box); sec.appendChild(btn); sec.appendChild(state);

  var sent = false;
  btn.onclick = function () {
    if (!box.value.trim()) { state.textContent = 'Not sent: nothing is written.'; box.focus(); return; }
    state.textContent = 'Sending...';
    fetch('/answer-ticket', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket: rel, question: asked, answer: box.value }) }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r.ok) { state.textContent = 'Not sent: ' + r.error; return; }
      sent = true;
      state.textContent = 'Sent ' + r.at + '. It is in the ticket\'s comments.' + (r.note ? ' But ' + r.note + '.' : ' Back to the dashboard...');
      if (!r.note) setTimeout(function () { location.href = '/'; }, 1500); },
      function (e) { state.textContent = 'Not sent: ' + e; });
  };

  dashboardLive('/events?doc=' + encodeURIComponent(rel), function (v) {
    if (v.stamp === seen || sent) return;
    if (v.stamp !== null && !box.value.trim()) { location.reload(); return; }
    var note = document.getElementById('review-updated') || document.createElement('p');
    note.id = 'review-updated';
    note.textContent = v.stamp === null ? 'This ticket is gone. Copy what you typed before you leave it.'
      : 'This ticket changed since you opened it. Copy what you typed, then reload.';
    sec.parentNode.insertBefore(note, sec);
  }, true);
}
