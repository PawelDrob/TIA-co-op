"""The two themes of the dashboards: the colours in the stylesheet, the switch on every page, and in a headless browser
what the viewer gets from it. The browser tests skip on a machine with neither Edge nor Chrome."""
import json
import re
import threading
import unittest
from pathlib import Path

from . import support
import live  # noqa: E402
import review_page  # noqa: E402

CSS = (support.TOOLS / 'dashboard.css').read_text(encoding='utf-8')

# Catppuccin Mocha, from its palette.json. Nothing else of it belongs here: colour means act or failed.
MOCHA = {'--bg': '#1e1e2e', '--ink': '#cdd6f4', '--muted': '#a6adc8', '--hint': '#a6adc8', '--hair': '#313244', '--you': '#fab387', '--fail': '#f38ba8'}
LIGHT = {'--bg': '#fff', '--ink': '#000', '--muted': '#666', '--hint': '#757575', '--hair': '#e0e0e0', '--you': '#a85b00', '--fail': '#c00000'}
TEXT_COLOURS = ('--ink', '--muted', '--hint', '--you', '--fail')
AA_TEXT = 4.5


def tokens():
    """{token: (light, dark)} as the stylesheet sets them."""
    return {name: (light, dark) for name, light, dark in re.findall(r'(--\w+):\s*light-dark\((#\w+),\s*(#\w+)\)', CSS)}


def luminance(colour):
    colour = colour.lstrip('#')
    if len(colour) == 3:
        colour = ''.join(c * 2 for c in colour)
    channels = [int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class ColoursTest(unittest.TestCase):
    def test_dark_takes_the_catppuccin_colours(self):
        self.assertEqual({k: v[1] for k, v in tokens().items()}, MOCHA)

    def test_light_stays_as_it_was(self):
        self.assertEqual({k: v[0] for k, v in tokens().items()}, LIGHT)

    def test_text_colours_can_be_read_against_the_background_in_both_themes(self):
        t = tokens()
        for which, theme in enumerate(('light', 'dark')):
            for name in TEXT_COLOURS:
                ratio = contrast(t[name][which], t['--bg'][which])
                self.assertGreaterEqual(ratio, AA_TEXT, f'{name} on --bg, {theme}: {ratio:.2f}')

    def test_no_colour_outside_the_tokens(self):
        # the white behind images and frames is theirs: a transparent picture is drawn for a white page
        rest = re.sub(r'/\*.*?\*/', '', CSS, flags=re.S)
        rest = re.sub(r'--\w+:\s*light-dark\([^)]*\);?', '', rest)
        rest = re.sub(r'background:\s*#fff', '', rest)
        self.assertEqual(re.findall(r'#[0-9a-fA-F]{3,8}\b(?=[;\s}])|rgba?\(|hsla?\(', rest), [])

    def test_a_chosen_theme_wins_over_the_system_setting(self):
        for theme in ('light', 'dark'):
            self.assertRegex(CSS, r':root\[data-theme="%s"\]\s*\{\s*color-scheme:\s*%s;' % (theme, theme))
        self.assertRegex(CSS, r':root\s*\{[^}]*color-scheme:\s*light dark;')


class EveryPageTest(unittest.TestCase):
    """The switch is made by dashboard.js, so a page needs that script in its head (there it runs before anything is drawn)
    and a .top outside what live updates swap."""

    @classmethod
    def setUpClass(cls):
        cls.repo = support.class_repo(cls)
        scratch = cls.repo / '.scratch'
        (cls.repo / 'docs').mkdir()
        (cls.repo / 'docs' / 'guide.md').write_text('# Guide\n', encoding='utf-8')
        (scratch / 'reviews').mkdir(parents=True)
        cls.old_page = '<!doctype html><html><head><style>:root { --bg: #000; }</style></head><body><main><p>old</p></main></body></html>'
        (scratch / 'reviews' / 'Old.html').write_text(cls.old_page, encoding='utf-8')
        (scratch / 'reviews' / 'Bare.html').write_text('<html><body><p>hand made</p></body></html>', encoding='utf-8')
        (scratch / 'reviews' / 'NoHead.html').write_text('<!doctype html><title>t</title><body><p>hand made</p></body>', encoding='utf-8')
        (scratch / 'reviews' / 'NoBody.html').write_text('<!doctype html><p>hand made</p>', encoding='utf-8')
        review_page.main(['--root', str(scratch), '--no-open', '--title', 'Real', '--ask', 'One?'])
        cls.server = support.Server(scratch)
        cls.addClassCleanup(cls.server.stop)

    def script_in_head(self, text):
        head = text.split('</head>')[0]
        self.assertIn('<script src="/dashboard.js"></script>', head)

    def test_start_page_and_document_page(self):
        for path in ('/', '/doc/docs/guide.md'):
            text = self.server.get(path)
            self.script_in_head(text)
            self.assertIn('class="top"', text)

    def test_a_review_page_has_it_in_its_head_once(self):
        text = self.server.get('/Old.html')
        self.script_in_head(text)
        self.assertEqual(text.count('src="/dashboard.js"'), 1)

    def test_a_review_page_built_earlier_follows_the_current_stylesheet(self):
        # its own inline copy has no themes in it: the current one has to come after it to win
        text = self.server.get('/Old.html')
        self.assertLess(text.index('<style>'), text.index('href="/dashboard.css"'))
        self.assertLess(text.index('href="/dashboard.css"'), text.index('</head>'))

    def test_a_hand_made_review_page_without_a_head_is_served_with_it_too(self):
        text = self.server.get('/Bare.html')
        self.assertLess(text.index('src="/dashboard.js"'), text.index('<body>'))

    def test_a_page_with_a_doctype_and_no_end_of_head_keeps_its_doctype_first(self):
        # anything before the doctype would put the page in quirks mode
        text = self.server.get('/NoHead.html')
        self.assertTrue(text.startswith('<!doctype html>'), text[:80])
        self.assertLess(text.index('src="/dashboard.js"'), text.index('<body>'))

    def test_a_page_with_a_doctype_and_nothing_else_of_a_page_keeps_its_doctype_first(self):
        text = self.server.get('/NoBody.html')
        self.assertTrue(text.startswith('<!doctype html>'), text[:80])
        self.assertLess(text.index('src="/dashboard.js"'), text.index('<p>'))

    def test_the_switch_is_in_the_top_bar_of_a_real_start_review_and_document_page(self):
        edge = support.headless()
        if not edge:
            self.skipTest('no Microsoft Edge, Google Chrome or hmipreview')
        self.addCleanup(edge.close)
        for path in ('/', '/Real.html', '/doc/docs/guide.md'):
            dom = support.dom_at_load(edge, f'http://127.0.0.1:{self.server.port}{path}')
            self.assertRegex(dom, support.SWITCH_IN_TOP, path)

    def test_the_top_bar_of_the_start_page_is_outside_what_updates_swap(self):
        text = self.server.get('/')
        self.assertLess(text.index('class="top"'), text.index('id="summary"'))
        self.assertLess(text.index('</header>'), text.index('id="summary"'))


# What the pages run, in a browser. A page here is the real head and script with this at the end of its body: it presses
# the switch as the case says and leaves what it saw in <pre id="seen">, which dump_dom returns.
PROBE = r"""<script>
addEventListener('load', function () {
  var root = document.documentElement, b = document.querySelector('.top .theme');
  function look() {
    return {theme: root.dataset.theme || null, bg: getComputedStyle(document.body).backgroundColor,
            label: b && b.getAttribute('aria-label'), icon: !!(b && b.querySelector('svg')),
            hint: getComputedStyle(document.querySelector('.answer'), '::placeholder').color};
  }
  var seen = {system: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', first: firstSeen, before: look(), kind: b && b.tagName, errors: window.errors, focusable: b && b.tabIndex};
  if (location.search.indexOf('press') >= 0) { b.click(); seen.after = look(); }
  // Another tab has made a choice, this one is shown again or gets focus.
  var search = location.search, shown = search.indexOf('shown') >= 0 ? [document, 'visibilitychange'] : search.indexOf('focused') >= 0 ? [window, 'focus'] : null;
  if (shown) {
    if (search.indexOf('elsewhere') >= 0) {
      document.cookie = 'dashboard-theme=' + (look().theme === 'dark' || (!look().theme && seen.system === 'dark') ? 'light' : 'dark') + '; path=/';
    }
    shown[0].dispatchEvent(new Event(shown[1]));
    seen.shown = look();
  }
  if (window.fireUpdate) {
    fireUpdate();
    seen.afterUpdate = look();
    seen.sameButton = document.querySelector('.top .theme') === b;
    seen.swapped = document.getElementById('summary').textContent;
  }
  var pre = document.createElement('pre'); pre.id = 'seen'; pre.textContent = JSON.stringify(seen);
  document.body.appendChild(pre);
});
</script>"""

# First in the head: what the page's script finds when browser storage is blocked, and a live connection that needs no server.
ERRORS = "<script>window.errors = []; addEventListener('error', function (e) { errors.push(e.message); });</script>"
NO_STORAGE = ("<script>Object.defineProperty(document, 'cookie', {get: function () { throw new DOMException('blocked', 'SecurityError'); },"
              "set: function () { throw new DOMException('blocked', 'SecurityError'); }});</script>")
FAKE_LIVE = ("<script>var fake = {close: function () {}, addEventListener: function (kind, f) { fake.on = f; }};"
             "window.EventSource = function () { return fake; };"
             "window.fireUpdate = function () { fake.on({data: JSON.stringify({title: 't', parts: {summary: 'swapped'}})}); };</script>")


def probe_page(extra=''):
    head, rest = live.head('probe').split('<title>', 1)
    return (head + ERRORS + extra + '<title>' + rest +
            # the first thing in the body: what the theme is by the time anything can be drawn
            '<body><script>var firstSeen = {theme: document.documentElement.dataset.theme || null,'
            ' scheme: getComputedStyle(document.documentElement).colorScheme};</script>'
            '<main><header class="top"><h1>Probe</h1><span class="live" id="live"></span></header>'
            '<div id="summary"></div><textarea class="answer" placeholder="Your answer"></textarea></main><script>if (window.fireUpdate) dashboardBoard();</script>' + PROBE + '</body></html>')


class ProbeHandler(live.Handler):
    def do_GET(self):
        path = self.path.split('?')[0]
        pages = {'/': probe_page(), '/blocked': probe_page(NO_STORAGE), '/updates': probe_page(FAKE_LIVE)}
        if path in pages:
            return self.send_text(200, pages[path], 'text/html; charset=utf-8')
        if self.send_asset(path):
            return None
        return self.send_error(404)


def probe_server(test):
    server = live.Server(('127.0.0.1', 0), ProbeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return server.server_address[1]


class InABrowserTest(unittest.TestCase):
    """Whatever the system setting of this machine is: the probe says which, and the switch goes to the other."""
    BACKGROUND = {'light': 'rgb(255, 255, 255)', 'dark': 'rgb(30, 30, 46)'}
    OTHER = {'light': 'dark', 'dark': 'light'}

    def setUp(self):
        self.edge = support.headless()
        if not self.edge:
            self.skipTest('no Microsoft Edge, Google Chrome or hmipreview')
        self.addCleanup(self.edge.close)
        self.port = probe_server(self)

    def see(self, path, port=None):
        dom = self.edge.dump_dom(f'http://127.0.0.1:{port or self.port}{path}')
        m = re.search(r'<pre id="seen">(.*?)</pre>', dom, re.S)
        self.assertTrue(m, dom[-2000:])
        return json.loads(m.group(1).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>'))

    def test_it_starts_from_the_system_setting_with_a_named_button_reached_by_keyboard(self):
        seen = self.see('/')
        self.assertIsNone(seen['before']['theme'])
        self.assertEqual(seen['before']['bg'], self.BACKGROUND[seen['system']])
        self.assertEqual(seen['kind'], 'BUTTON')
        self.assertEqual(seen['focusable'], 0)
        self.assertEqual(seen['before']['label'], f'Switch to {self.OTHER[seen["system"]]} mode')
        self.assertTrue(seen['before']['icon'])

    def test_pressing_it_switches_the_page_and_the_next_page_has_it_before_it_draws_anything(self):
        seen = self.see('/?press')
        chosen = self.OTHER[seen['system']]
        self.assertEqual(seen['after']['theme'], chosen)
        self.assertEqual(seen['after']['bg'], self.BACKGROUND[chosen])
        self.assertEqual(seen['after']['label'], f'Switch to {seen["system"]} mode')

        seen = self.see('/')
        self.assertEqual(seen['first']['theme'], chosen)
        self.assertEqual(seen['first']['scheme'].strip(), chosen)
        self.assertEqual(seen['before']['bg'], self.BACKGROUND[chosen])
        self.assertEqual(seen['before']['label'], f'Switch to {seen["system"]} mode')

        seen = self.see('/', probe_server(self))     # the other dashboard, on another port
        self.assertEqual(seen['first']['theme'], chosen)

    def test_blocked_storage_fails_quietly_and_the_switch_still_works(self):
        seen = self.see('/blocked?press')
        chosen = self.OTHER[seen['system']]
        self.assertEqual(seen['errors'], [])
        self.assertEqual(seen['after']['theme'], chosen)
        self.assertEqual(seen['after']['bg'], self.BACKGROUND[chosen])

    def test_the_placeholder_of_an_answer_box_takes_the_muted_colour_in_dark_and_stays_in_light(self):
        seen = self.see('/?press')
        hints = {'light': 'rgb(117, 117, 117)', 'dark': 'rgb(166, 173, 200)'}
        self.assertEqual(seen['before']['hint'], hints[seen['system']])
        self.assertEqual(seen['after']['hint'], hints[self.OTHER[seen['system']]])

    def test_an_open_tab_takes_a_choice_made_elsewhere_when_it_is_shown_again_or_gets_focus(self):
        for how in ('shown', 'focused'):
            with self.subTest(how):
                seen = self.see(f'/?elsewhere&{how}')
                chosen = self.OTHER[seen['system']]
                self.assertEqual(seen['shown']['theme'], chosen)
                self.assertEqual(seen['shown']['bg'], self.BACKGROUND[chosen])
                self.assertEqual(seen['shown']['label'], f'Switch to {seen["system"]} mode')
                self.edge.close()
                self.edge = support.headless()      # a fresh profile: no choice left from this round
                self.addCleanup(self.edge.close)

    def test_a_tab_with_blocked_storage_keeps_its_choice_when_it_is_shown_again(self):
        seen = self.see('/blocked?press&shown')
        self.assertEqual(seen['errors'], [])
        self.assertEqual(seen['shown']['theme'], self.OTHER[seen['system']])

    def test_it_holds_through_a_live_update(self):
        seen = self.see('/updates?press')
        chosen = self.OTHER[seen['system']]
        self.assertEqual(seen['swapped'], 'swapped')       # the update did arrive
        self.assertTrue(seen['sameButton'])
        self.assertEqual(seen['afterUpdate']['theme'], chosen)
        self.assertEqual(seen['afterUpdate']['bg'], self.BACKGROUND[chosen])


if __name__ == '__main__':
    unittest.main()
