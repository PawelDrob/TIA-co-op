"""Rendering: headless Edge (else Chrome) loads the browser app from the preview server on a fixture repo; the drawn DOM is
checked against the SimaticML (positions, sizes, texts) and run-mode clicks are checked by the screen shown.
No pixel comparison, except EditorLookTest: the stylesheet decides there, and a DOM dump does not show that. Skipped when
neither is installed."""
import contextlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

from hmipreview import server
from Tests.browser import NET_TRIES, NOT_FOUND, Edge, EdgeError, edge_path, failed_requests, parse, png_colours
from Tests.fixture import TP1200, FixtureRepo, document, group, item, rect

EDGE = edge_path()


FONT = ('<ObjectList><Hmi.Globalization.MultiLingualFont ID="F" CompositionName="Font"><ObjectList>'
        '<Hmi.Globalization.FontItem ID="G" CompositionName="Items"><AttributeList><Culture>en-US</Culture>'
        '<FontFamily>Tahoma</FontFamily><FontSize>11</FontSize><FontStyle>Bold</FontStyle></AttributeList>'
        '</Hmi.Globalization.FontItem></ObjectList></Hmi.Globalization.MultiLingualFont></ObjectList>')


class BrowserTempFolderTest(unittest.TestCase):
    """A real browser leaves a folder in its temp folder only on some runs, so this one prints where that is."""

    def test_the_browser_gets_its_profile_as_temp_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            browser = os.path.join(folder, 'browser.cmd')
            with open(browser, 'w', encoding='ascii') as f:
                f.write('@echo %TEMP%^|%TMP%\n')
            edge = Edge(browser)
            self.addCleanup(edge.close)
            self.assertEqual(edge.dump_dom('about:blank').strip(), edge.profile + '|' + edge.profile)

    def test_a_profile_that_cannot_go_raises(self):
        edge = Edge('no-browser.exe')
        self.addCleanup(edge.close)
        with open(os.path.join(edge.profile, 'held'), 'w', encoding='ascii'):
            with self.assertRaises(PermissionError):
                edge.close()


class DrawnPageTest(unittest.TestCase):
    """On a slow machine (a CI runner) the browser dumped some pages before they had drawn: a stand-in browser draws
    the page only on its second run, or never."""

    def browser(self, draws):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        browser = os.path.join(folder, 'browser.cmd')
        with open(browser, 'w', encoding='ascii') as f:
            f.write('@echo %%*>>"%s"\n' % os.path.join(folder, 'runs'))
            f.write('@if exist "%%TEMP%%\\once" (echo ^<html %s^>^</html^>) else (echo.>"%%TEMP%%\\once" & echo ^<html^>^</html^>)\n'
                    % ('data-ready="1"' if draws else ''))
        edge = Edge(browser)
        self.addCleanup(edge.close)
        return edge, os.path.join(folder, 'runs')

    def budgets_used(self, log):
        with open(log, encoding='ascii') as f:
            return [re.search(r'--virtual-time-budget=(\d+)', line).group(1) for line in f]

    def test_a_page_not_drawn_yet_is_dumped_again_with_a_larger_budget(self):
        edge, log = self.browser(draws=True)
        self.assertEqual('1', edge.dump('about:blank').ready())
        self.assertEqual(['8000', '30000'], self.budgets_used(log))

    def test_a_page_that_never_draws_is_given_back_after_the_largest_budget(self):
        edge, log = self.browser(draws=False)
        self.assertIsNone(edge.dump('about:blank').ready())
        self.assertEqual(['8000', '30000', '120000'], self.budgets_used(log))

    def test_a_screenshot_takes_the_largest_budget_at_once(self):
        edge, log = self.browser(draws=True)                # writes no PNG: only the budget is read here
        with self.assertRaises(EdgeError):
            edge.screenshot('about:blank', os.path.join(os.path.dirname(log), 'shot.png'), 900, 600)
        self.assertEqual(['120000'], self.budgets_used(log))


class NetLogTest(unittest.TestCase):
    """A NetLog that does not read turns the run-again off for that run: it says so on stderr, and none is no news."""

    def failed(self, text):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        netlog = os.path.join(folder, 'netlog.json')
        if text is not None:
            with open(netlog, 'w', encoding='utf-8') as f:
                f.write(text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            found = failed_requests(netlog, 'http://127.0.0.1:1/')
        return found, err.getvalue()

    def test_a_netlog_cut_short_is_named(self):
        found, err = self.failed('{"constants": {}, "events": [')
        self.assertEqual([], found)
        self.assertIn('the NetLog of http://127.0.0.1:1/ does not read (JSONDecodeError', err)

    def test_a_netlog_without_its_constants_is_named(self):
        found, err = self.failed('{"events": []}')
        self.assertEqual([], found)
        self.assertIn('does not read (KeyError', err)

    def test_no_netlog_is_no_news(self):
        self.assertEqual(([], ''), self.failed(None))


@unittest.skipUnless(EDGE, NOT_FOUND)
class FailedRequestTest(unittest.TestCase):
    """On a CI runner the browser failed a request of the page now and then ("Failed to fetch"), with no error raised
    by the server: a page whose request the browser failed is loaded again, NET_TRIES times at most, and each such run
    is named on stderr. A server that answers /data only from its page's load number fails + 1 stands in: the browser
    itself asks a request with an empty answer twice."""
    PAGE = ('<html><body><script>%sfetch("/data").then(r => r.text()).then(t => {'
            ' document.body.textContent = t; document.documentElement.dataset.ready = "1"; })'
            '.catch(() => { document.documentElement.dataset.ready = "error"; });</script></body></html>')

    def setUp(self):
        self.edge = Edge(EDGE)
        self.addCleanup(self.edge.close, True)

    def serve(self, fails, also=''):
        """URL of the page and the list of its loads; also: script run first on the page."""
        loads, page = [], (self.PAGE % also).encode('utf-8')

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    loads.append(self.path)
                elif self.path == '/data' and len(loads) <= fails:
                    return                                  # closed with no answer: the browser fails the request
                body = b'drawn' if self.path == '/data' else page
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return 'http://127.0.0.1:%d/' % httpd.server_address[1], loads

    def dump(self, url):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            dom = self.edge.dump(url)
        return dom, err.getvalue()

    def test_a_page_whose_request_the_browser_failed_is_loaded_again(self):
        url, loads = self.serve(fails=1)
        dom, err = self.dump(url)
        self.assertEqual('1', dom.ready())
        self.assertEqual(2, len(loads))
        self.assertIn(url + 'data ERR_EMPTY_RESPONSE', err)

    def test_a_request_failed_on_every_run_is_given_back_after_the_last_try(self):
        url, loads = self.serve(fails=99)
        dom, err = self.dump(url)
        self.assertEqual('error', dom.ready())
        self.assertEqual(NET_TRIES, len(loads))
        self.assertEqual(NET_TRIES, err.count('ERR_EMPTY_RESPONSE'))

    def test_a_screenshot_is_taken_again_after_a_failed_request(self):
        url, loads = self.serve(fails=1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.edge.screenshot(url, os.path.join(self.edge.profile, 'shot.png'), 300, 200)
        self.assertEqual(2, len(loads))

    def test_a_failed_request_to_another_server_is_not_the_page_s(self):
        # Chromium blocks port 1 before it connects: the NetLog holds that request as ERR_UNSAFE_PORT
        url, loads = self.serve(fails=0, also='fetch("http://127.0.0.1:1/").catch(() => {}); ')
        dom, err = self.dump(url)
        self.assertEqual('1', dom.ready())
        self.assertEqual(1, len(loads))
        self.assertEqual('', err)


@unittest.skipUnless(EDGE, NOT_FOUND)
class BrowserCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge = Edge(EDGE)

    @classmethod
    def tearDownClass(cls):
        cls.edge.close()
    def setUp(self):
        self.repo = FixtureRepo()
        self.addCleanup(self.repo.cleanup)

    def page(self, size=None, **params):
        """Serve the fixture repo, load the app with the given URL hooks, return the dumped DOM. size: the window's
        (width, height), else the browser's own."""
        dom = self.served(lambda base: self.edge.dump(base + '?' + urllib.parse.urlencode(params), size=size), params,
                          drew=lambda dumped: dumped.ready() == '1')
        status = dom.by_id('status')
        self.assertEqual('1', dom.ready(), 'page did not finish drawing; its status: %s'
                         % (status.text() if status is not None else 'none'))
        return dom

    def screen(self, dom):
        return dom.by_id('screen')

    def shot(self, **params):
        """{(x, y): colour} of a real screenshot of the app at 900 x 600 with the given URL hooks."""
        out = os.path.join(tempfile.mkdtemp(dir=self.repo.path), 'shot.png')
        self.served(lambda base: self.edge.screenshot(base + '?' + urllib.parse.urlencode(params), out, 900, 600),
                    params)
        return png_colours(out)

    def served(self, load, params, drew=None):
        """load(base URL) while a preview server serves the fixture repo (?live=0 unless params say). What the server
        saw goes to stderr when the browser failed a request in a run of it (beside the browser's own line: a request
        the server never got, or one it got and did not answer), when the server answered a request with a 5xx (a
        page that then ends in an error has no failed request, and a screenshot cannot say it did not draw), when
        drew(what load gave) is false, and when load raised."""
        params.setdefault('live', '0')
        httpd = server.make_server(self.repo.path, host='127.0.0.1', port=0)
        httpd.RequestHandlerClass, httpd.seen, httpd.errors = LoggedHandler, [], []
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        base, before, drawn = 'http://127.0.0.1:%d/' % httpd.server_address[1], len(self.edge.failures), False
        try:
            result = load(base)
            drawn = drew is None or drew(result)
            return result
        finally:
            httpd.shutdown()
            httpd.server_close()
            if len(self.edge.failures) > before or httpd.errors or not drawn:
                sys.stderr.write('Tests.browser: what the preview server of %s saw:\n%s'
                                 % (base, ''.join('  %s\n' % line for line in httpd.seen)))


class LoggedHandler(server.Handler):
    """The preview server's handler, writing down in server.seen each connection, each request it answered and each
    connection's end, by the browser's port and the time; a 5xx answer also with its body (which names the exception)
    and in server.errors. The server itself logs only when verbose, and answers an exception with a 500 silently."""

    def setup(self):
        super().setup()
        self.note('connected')

    def _send(self, resp):
        if resp.status >= 500:
            self.server.errors.append(resp.status)
            self.note('answered %d: %s' % (resp.status, ' '.join(resp.body[:500].decode('utf-8', 'replace').split())))
        super()._send(resp)

    def log_message(self, fmt, *args):
        self.note(fmt % args)

    def finish(self):
        try:
            super().finish()
        finally:
            self.note('closed')

    def note(self, what):
        self.server.seen.append('%s port %d: %s' % (time.strftime('%H:%M:%S'), self.client_address[1], what))


class ServerLogTest(BrowserCase):
    """A page or screenshot with a run in which the browser failed a request, or whose server answered a 5xx, puts what
    its preview server saw on stderr: a red run tells a request lost before the server from one the server dropped or
    answered with an error. Where a browser stands in, it fetches the page once, as a run would, and says whether
    that run failed a request."""

    def fake_browser(self, failed):
        def run(url, *args, **kwargs):
            urllib.request.urlopen(url, timeout=30).read()
            if failed:
                self.edge.failures.append((url, [(url, 'ERR_EMPTY_RESPONSE')]))
            return parse('<html data-ready="1"></html>')
        return run

    def stderr_of(self, call, *args, **kwargs):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            call(*args, **kwargs)
        return err.getvalue()

    def break_typenames(self):
        """/api/typenames raises for this test. The server answers it with a 500 and the browser fails no request, so
        nothing runs again: the page's status and the server's log are what tell."""
        i = next(i for i, r in enumerate(server.ROUTES) if r[:2] == ('GET', '/api/typenames'))

        def broken(req):
            raise RuntimeError('made up for the test')
        self.addCleanup(server.ROUTES.__setitem__, i, server.ROUTES[i])
        server.ROUTES[i] = ('GET', '/api/typenames', broken)

    def assert_server_log_of_the_500(self, err):
        self.assertRegex(err, r'what the preview server of http://127\.0\.0\.1:\d+/ saw')
        self.assertRegex(err, r'answered 500: \{ "error": "RuntimeError: made up for the test" \}')
        self.assertRegex(err, r'"GET /api/typenames HTTP/1\.1" 500')

    def test_a_page_its_server_answered_with_a_500_says_what_both_saw(self):
        self.break_typenames()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(AssertionError) as caught:
            self.page(screen='Main')
        self.assertIn('its status: Error: /api/typenames: HTTP 500', str(caught.exception))
        self.assert_server_log_of_the_500(err.getvalue())

    def test_a_screenshot_its_server_answered_with_a_500_shows_what_the_server_saw(self):
        self.break_typenames()                      # a PNG cannot say the page did not draw: the server's log does
        self.assert_server_log_of_the_500(self.stderr_of(self.shot, screen='Main'))

    def test_a_page_with_a_failed_run_shows_what_its_server_saw(self):
        self.edge.dump = self.fake_browser(failed=True)
        self.addCleanup(delattr, self.edge, 'dump')
        err = self.stderr_of(self.page, screen='Main')
        self.assertRegex(err, r'what the preview server of http://127\.0\.0\.1:\d+/ saw')
        self.assertRegex(err, r'port \d+: connected')
        self.assertRegex(err, r'port \d+: "GET /\?screen=Main&live=0 HTTP/1\.1" 200')
        self.assertRegex(err, r'port \d+: closed')

    def test_a_page_without_a_failed_run_says_nothing(self):
        self.edge.dump = self.fake_browser(failed=False)
        self.addCleanup(delattr, self.edge, 'dump')
        self.assertEqual('', self.stderr_of(self.page, screen='Main'))

    def test_a_screenshot_with_a_failed_run_shows_what_its_server_saw(self):
        fake = self.fake_browser(failed=True)

        def shoot(url, out, width, height):
            fake(url)
            png_of_one_pixel(out)
        self.edge.screenshot = shoot
        self.addCleanup(delattr, self.edge, 'screenshot')
        self.assertIn('what the preview server of', self.stderr_of(self.shot, screen='Main'))


def png_of_one_pixel(path):
    """A black PNG of 1 x 1 pixel at path, of the form png_colours reads."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00')) + chunk(b'IEND', b''))


def ml_text(comp, lines, cultures=('en-US', 'es-ES')):
    """MultilingualText as exported: rich text <body><p>a<br />b</p></body> per culture."""
    items = ''.join(
        '<MultilingualTextItem ID="0" CompositionName="Items"><AttributeList><Culture>%s</Culture>'
        '<Text><body><p>%s</p></body></Text></AttributeList></MultilingualTextItem>'
        % (c, '<br />'.join(escape(l if c == 'en-US' else l + ' ES') for l in lines)) for c in cultures)
    return '<MultilingualText ID="0" CompositionName="%s"><ObjectList>%s</ObjectList></MultilingualText>' % (comp, items)


def font(size, style='Regular'):
    return ('<MultiLingualFont ID="0" CompositionName="Font"><ObjectList><Hmi.Globalization.FontItem ID="0" '
            'CompositionName="Items"><AttributeList><Culture>en-US</Culture><FontFamily>Tahoma</FontFamily>'
            '<FontSize>%d</FontSize><FontStyle>%s</FontStyle></AttributeList></Hmi.Globalization.FontItem>'
            '</ObjectList></MultiLingualFont>' % (size, style))


def link(kind, name):
    return '<%s TargetID="@OpenLink"><Name>%s</Name></%s>' % (kind, escape(name), kind)


def func(name, *params):
    """System function; params (name, kind, value): kind 'link' (by name), 'self' (#0) or 'int'."""
    ps = []
    for pn, kind, val in params:
        if kind == 'link':
            ps.append('<Hmi.Event.FunctionListEntryParameter ID="0" CompositionName="Parameters"><AttributeList>'
                      '<Name>%s</Name></AttributeList><LinkList>%s</LinkList></Hmi.Event.FunctionListEntryParameter>'
                      % (pn, link('Value', val)))
        elif kind == 'self':
            ps.append('<Hmi.Event.FunctionListEntryParameter ID="0" CompositionName="Parameters"><AttributeList>'
                      '<Name>%s</Name></AttributeList><LinkList><Value TargetID="#0" /></LinkList>'
                      '</Hmi.Event.FunctionListEntryParameter>' % pn)
        else:
            ps.append('<Hmi.Event.FunctionListEntryParameter ID="0" CompositionName="Parameters"><AttributeList>'
                      '<Name>%s</Name><Value Type="System.Int32">%s</Value></AttributeList>'
                      '</Hmi.Event.FunctionListEntryParameter>' % (pn, val))
    return ('<Hmi.Event.FunctionListEntry ID="0" CompositionName="FunctionListEntries"><AttributeList><Name>%s</Name>'
            '<Type>SystemFunction</Type></AttributeList><ObjectList>%s</ObjectList></Hmi.Event.FunctionListEntry>'
            % (name, ''.join(ps)))


def event(name, *funcs):
    return ('<Hmi.Event.Event ID="0" CompositionName="Events"><AttributeList><Name>%s</Name></AttributeList>'
            '<ObjectList><Hmi.Event.FunctionListEventHandler ID="0" CompositionName="EventHandler"><ObjectList>%s'
            '</ObjectList></Hmi.Event.FunctionListEventHandler></ObjectList></Hmi.Event.Event>' % (name, ''.join(funcs)))


def button(name, text, events='', left=10, top=100, width=120, height=40, **attrs):
    return item('Hmi.Screen.Button', name, '<ObjectList>%s%s%s%s</ObjectList>' % (
        events, font(13), ml_text('TextOff', [text]), ml_text('TextOn', [text])),
        Left=left, Top=top, Width=width, Height=height, **attrs)


def nav_button(name, target, left=10, top=100):
    return button(name, 'Go ' + target, event('Click', func('ActivateScreen', ('Screen name', 'link', target),
                                                            ('Object number', 'int', 0))), left=left, top=top)


def box_of(node):
    b = node.body()
    return tuple(b.num(k) for k in ('x', 'y', 'width', 'height'))


class DrawingTest(BrowserCase):
    def test_text_field_and_button_draw_their_text_lines(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.TextField', 'txtTitle', '<ObjectList>%s%s</ObjectList>' % (
                font(16, 'Bold'), ml_text('Text', ['Silo', 'Station G05'])),
                Left=20, Top=100, Width=300, Height=60),
            button('btnStart', 'Start', left=400, top=100)], Number=1))

        dom = self.page(screen='Main')

        txt = dom.obj('txtTitle')
        self.assertEqual((20, 100, 300, 60), box_of(txt))
        self.assertEqual(['Silo', 'Station G05'], txt.lines())
        first = txt.find(lambda n: 'line' in n.classes)
        self.assertEqual(('16', 'bold'), (first.attrs['font-size'], first.attrs['font-weight']))
        btn = dom.obj('btnStart')
        self.assertEqual((400, 100, 120, 40), box_of(btn))
        self.assertEqual(['Start'], btn.lines())

    def test_other_culture_with_lang_hook(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.TextField', 't1', '<ObjectList>%s%s</ObjectList>' % (font(13), ml_text('Text', ['Hello'])),
                 Left=0, Top=100, Width=100, Height=20)], Number=1))
        self.assertEqual(['Hello ES'], self.page(screen='Main', lang='es-ES').obj('t1').lines())

    def test_io_fields_show_format_pattern_and_text_list(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.IOField', 'io1', '<ObjectList>%s</ObjectList>' % font(13), Left=10, Top=100, Width=80,
                 Height=24, FormatPattern='s99.99'),
            item('Hmi.Screen.SymbolicIOField', 'sym1', '<LinkList>%s</LinkList><ObjectList>%s</ObjectList>' % (
                link('TextList', 'tlModes'), font(13)),
                 Left=100, Top=100, Width=120, Height=24)], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual((10, 100, 80, 24), box_of(dom.obj('io1')))
        self.assertEqual(['+00.00'], dom.obj('io1').lines())
        self.assertEqual(['[tlModes]'], dom.obj('sym1').lines())

    def test_attributes_a_document_leaves_out_are_not_guessed_but_marked(self):
        # Full exports only (2026-10-06): before, a missing Height was drawn as TIA's default 30 (project B 040 - Mode
        # Change, copies of minimally exported fields). Now the object is drawn as written and marked incomplete.
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.TextField', 'txtSafety', '<ObjectList>%s%s</ObjectList>' % (
                font(13, 'Bold'), ml_text('Text', ['Safety circuit'])),
                Left=400, Top=176, Width=236, ForeColor=None),
            rect('rectNoColour', BackColor=None),
            item('Hmi.Screen.IOField', 'ioValue', '<ObjectList>%s</ObjectList>' % font(13), Width=80, FormatPattern='9999',
                 HorizontalAlignment='Left')],
            Number=1))

        dom = self.page(screen='Main')

        txt = dom.obj('txtSafety')
        self.assertEqual((400, 176, 236, 0), box_of(txt))
        self.assertIn('incomplete', txt.classes)
        self.assertEqual(['ForeColor', 'Height'], sorted(txt.attrs['data-missing'].split()))
        self.assertIsNotNone(txt.find(lambda n: 'incomplete-mark' in n.classes))
        rect_ = dom.obj('rectNoColour')
        self.assertEqual('none', rect_.body().attrs['fill'])
        self.assertEqual('BackColor', rect_.attrs['data-missing'])
        io = dom.obj('ioValue')
        self.assertEqual((0, 0, 80, 0), box_of(io))
        self.assertEqual(['Height', 'Left', 'Top'], sorted(io.attrs['data-missing'].split()))
        line = io.find(lambda n: 'line' in n.classes)
        self.assertEqual(('start', 0.0), (line.attrs['text-anchor'], line.num('x')))   # LeftMargin 0, no 6 px

    def test_full_attributes_shape_borders_corners_gradients_and_flashing(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.TextField', 'txtRound', Left=10, Top=100, Width=100, Height=30, CornerRadius=3,
                 BackFillStyle='Solid', BackColor='255, 255, 255', BorderWidth=1, EdgeStyle='Solid'),
            item('Hmi.Screen.IOField', 'ioDouble', Left=10, Top=200, Width=100, Height=40, BorderWidth=4,
                 BorderColor='10, 20, 30', BorderBackColor='200, 210, 220'),
            button('btnRound', 'Round', left=200, top=100, CornerStyle='Round', CornerRadius=5),
            button('btnPointed', 'Pointed', left=200, top=200, CornerStyle='Pointed', CornerRadius=5),
            button('btnGradient', 'Grad', left=400, top=100, BackFillStyle='GradientVertical'),
            button('btnSolid', 'Solid', left=520, top=100, BackColor='0, 68, 102', BackFillStyle='Solid',
                   UseFirstGradient='true', UseSecondGradient='true'),
            item('Hmi.Screen.Circle', 'lampFlash', Left=600, Top=100, Width=20, Height=20, Flashing='Standard'),
            item('Hmi.Screen.Line', 'arrow1', StartLeft=10, StartTop=400, EndLeft=200, EndTop=400,
                 StartStyle='FilledArrow', LineWidth=2),
            item('Hmi.Screen.Polygon', 'gon1', Points='\ufeff<Item>300, 400</Item><Item>340, 380</Item>'
                 '<Item>340, 420</Item>', BorderWidth=3, BorderColor='1, 2, 3')], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual('3', dom.obj('txtRound').body().attrs['rx'])
        borders = dom.obj('ioDouble').find_all(lambda n: 'border' in n.classes)
        self.assertEqual([('rgb(10, 20, 30)', 2.0), ('rgb(200, 210, 220)', 2.0)],
                         [(b.attrs['stroke'], b.num('stroke-width')) for b in borders])
        self.assertEqual((11, 201, 98, 38), tuple(borders[0].num(k) for k in ('x', 'y', 'width', 'height')))
        self.assertEqual('5', dom.obj('btnRound').body().attrs['rx'])
        self.assertNotIn('rx', dom.obj('btnPointed').body().attrs)
        self.assertTrue(dom.obj('btnGradient').body().attrs['fill'].startswith('url(#grad'))
        self.assertEqual('rgb(0, 68, 102)', dom.obj('btnSolid').body().attrs['fill'])
        stops = dom.obj('btnGradient').find_all(lambda n: n.tag == 'stop')
        self.assertEqual(['rgb(131, 132, 142)', 'rgb(99, 101, 113)', 'rgb(88, 90, 103)'],
                         [s.attrs['stop-color'] for s in stops])
        self.assertIsNotNone(dom.obj('lampFlash').find(lambda n: 'flash-mark' in n.classes))
        self.assertIsNone(dom.obj('txtRound').find(lambda n: 'flash-mark' in n.classes))
        arrow = dom.obj('arrow1').body()
        self.assertTrue(arrow.attrs['marker-start'].startswith('url(#arrow'))
        self.assertNotIn('marker-end', arrow.attrs)
        self.assertEqual(('round', '2'), (arrow.attrs['stroke-linecap'], arrow.attrs['stroke-width']))
        gon = dom.obj('gon1').body()
        self.assertEqual(('rgb(1, 2, 3)', '3', 'rgb(255, 255, 0)'),
                         (gon.attrs['stroke'], gon.attrs['stroke-width'], gon.attrs['fill']))
        self.assertNotIn('incomplete', dom.obj('gon1').classes)

    def test_symbolic_io_field_shows_the_text_list_entry_for_0_aligned_as_written(self):
        # project B 040 - Operating Mode: the placeholder '[tlOperatingMode]' was wider than the field and, aligned right,
        # lost its start. Without a tag value the field shows the entry a tag at 0 selects.
        entries = ''.join(
            '<Hmi.TextGraphicList.TextListEntry ID="0" CompositionName="Entries"><AttributeList><From>%d</From>'
            '<To>%d</To></AttributeList><ObjectList>%s</ObjectList></Hmi.TextGraphicList.TextListEntry>'
            % (v, v, ml_text('Text', [t])) for v, t in ((1, 'Auto'), (0, 'Off')))
        self.repo.export('textlist', 'tlMode', (
            '<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
            '<Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>tlMode</Name></AttributeList>'
            '<ObjectList>%s</ObjectList></Hmi.TextGraphicList.TextList></Document>\n' % entries))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.SymbolicIOField', 'symMode', '<LinkList>%s</LinkList><ObjectList>%s</ObjectList>' % (
                link('TextList', 'tlMode'), font(13)),
                 Left=276, Top=176, Width=112, Mode='Output', HorizontalAlignment='Right', RightMargin=4,
                 LeftMargin=0)], Number=1))

        sym = self.page(screen='Main').obj('symMode')

        self.assertEqual(['Off'], sym.lines())
        line = sym.find(lambda n: 'line' in n.classes)
        self.assertEqual(('end', 384.0), (line.attrs['text-anchor'], line.num('x')))

    def test_a_field_inside_a_text_draws_nothing_and_the_text_around_it_stays(self):
        def text(body):
            return ('<ObjectList><MultilingualText ID="0" CompositionName="Text"><ObjectList><MultilingualTextItem '
                    'ID="0" CompositionName="Items"><AttributeList><Culture>en-US</Culture><Text><body><p>%s</p></body>'
                    '<fieldinfos><fieldinfo name="0" domaintype="HMICommonTextList"><reference TargetID="@OpenLink">'
                    '<name>Vendor.Hmi.Lists.HmiTextList:Modes</name></reference><subreference TargetID="@OpenLink">'
                    '<name>Vendor.Hmi.Tag.HmiTag:modeNow</name></subreference></fieldinfo></fieldinfos></Text>'
                    '</AttributeList></MultilingualTextItem></ObjectList></MultilingualText>%s</ObjectList>'
                    % (body, font(12)))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.TextField', 'lbl', text('Mode: <field ref="0" />!'), Left=10, Top=10, Width=400, Height=30),
            item('Hmi.Screen.TextField', 'odd', text('<field ref="9" />'), Left=10, Top=50, Width=400, Height=30),
        ], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual(['Mode: !'], dom.obj('lbl').lines())
        self.assertEqual([], dom.obj('odd').lines())

    def test_graphic_view_and_button_draw_the_project_graphic_and_label_one_no_browser_draws(self):
        for name, ext in (('Logo', 'png'), ('Vector', 'emf')):
            self.repo.write('project/graphics/%s.xml' % name,
                            '<Document><Hmi.Globalization.MultiLingualGraphic ID="0"><AttributeList><DefaultImageStream '
                            'external="path">%s files\\DefaultImageStream.%s</DefaultImageStream><Name>%s</Name>'
                            '</AttributeList></Hmi.Globalization.MultiLingualGraphic></Document>' % (name, ext, name))
            full = os.path.join(self.repo.path, 'project', 'graphics', name + ' files', 'DefaultImageStream.' + ext)
            os.makedirs(os.path.dirname(full))
            with open(full, 'wb') as f:
                f.write(b'x')
        pic = lambda kind, name: '<LinkList>%s</LinkList>' % link(kind, name)
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.GraphicView', 'pic1', pic('Picture', 'Logo'), Left=700, Top=100, Width=64, Height=64,
                 AutoSizing='StretchPicture'),
            item('Hmi.Screen.GraphicView', 'pic2', pic('Picture', 'Vector'), Left=800, Top=100, Width=64, Height=64,
                 AutoSizing='StretchPicture'),
            item('Hmi.Screen.Button', 'btn1', pic('PictureOff', 'Logo'), Left=100, Top=100, Width=64, Height=64,
                 Mode='Graphic'),
        ], Number=1))

        dom = self.page(screen='Main')

        image = dom.obj('pic1').find(lambda n: n.tag == 'image')
        self.assertTrue(image.attrs['href'].startswith('/api/picture?name=Logo&v='), image.attrs['href'])
        self.assertEqual((700, 100, 64, 64), tuple(image.num(k) for k in ('x', 'y', 'width', 'height')))
        self.assertIsNone(dom.obj('pic2').find(lambda n: n.tag == 'image'))
        self.assertEqual(['Vector'], dom.obj('pic2').lines())
        self.assertEqual(image.attrs['href'], dom.obj('btn1').find(lambda n: n.tag == 'image').attrs['href'])

    def test_io_field_shows_a_sign_and_a_zero_per_position_and_keeps_a_pattern_not_known(self):
        field = lambda name, pattern, left: item('Hmi.Screen.IOField', name, FONT, Left=left, Top=100, Width=100, Height=30,
                                                 FormatPattern=pattern)
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            field('text', '????', 0), field('digits', '999', 100), field('point', '99.9', 200),
            field('signed', 's999', 300), field('hex', 'FFFF', 400), field('other', 'b1', 500)], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual({'text': ['0000'], 'digits': ['000'], 'point': ['00.0'], 'signed': ['+000'], 'hex': ['0000'],
                          'other': ['b1']},
                         {n: dom.obj(n).lines() for n in ('text', 'digits', 'point', 'signed', 'hex', 'other')})

    def test_a_pattern_with_no_editor_shot_behind_it_is_marked(self):
        field = lambda name, pattern, left: item('Hmi.Screen.IOField', name, FONT, Left=left, Top=100, Width=90, Height=30,
                                                 FormatPattern=pattern)
        cases = {'seen1': ('????', None), 'seen2': ('9999', None), 'seen3': ('FFFF', None), 'seen4': ('s999', None),
                 'inferred1': ('99.9', 'inferred'), 'inferred2': ('s9,999', 'inferred'),
                 'unknown1': ('1111', 'unknown'), 'unknown2': ('123', 'unknown'), 'unknown3': ('FAULT', 'unknown')}
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            field(n, p, 100 * i) for i, (n, (p, _)) in enumerate(cases.items())], Number=1))

        dom = self.page(screen='Main')

        for name, (_, state) in cases.items():
            mark = dom.obj(name).find(lambda n: 'pattern-mark' in n.classes)
            self.assertEqual(state, dom.obj(name).attrs.get('data-pattern'), name)
            self.assertEqual(state is not None, mark is not None, name)

    def test_digital_clock_and_date_time_field_show_the_sample_date(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Clock', 'clock1', FONT, Left=0, Top=0, Width=200, Height=24, Analog='false',
                 DialColor='230, 230, 230', NeedleBorderColor='40, 40, 40'),
            item('Hmi.Screen.Clock', 'analog1', Left=0, Top=50, Width=100, Height=100, Analog='true'),
            item('Hmi.Screen.DateTimeField', 'dt1', FONT, Left=300, Top=0, Width=200, Height=40, BackColor='255, 255, 255',
                 BackFillStyle='Solid', BorderColor='71, 73, 87', BorderWidth=2, CornerRadius=0, EdgeStyle='Solid',
                 Flashing='None', ForeColor='49, 52, 74', LongDateTimeFormat='false', ShowDate='true', ShowTime='true',
                 HorizontalAlignment='Left', VerticalAlignment='Middle', LeftMargin=3, RightMargin=2, TopMargin=2, BottomMargin=2),
            item('Hmi.Screen.DateTimeField', 'dt2', FONT, Left=300, Top=50, Width=200, Height=40, BackColor='255, 255, 255',
                 BackFillStyle='Solid', BorderColor='71, 73, 87', BorderWidth=2, CornerRadius=0, EdgeStyle='Solid',
                 Flashing='None', ForeColor='49, 52, 74', LongDateTimeFormat='false', ShowDate='true', ShowTime='false',
                 HorizontalAlignment='Left', VerticalAlignment='Middle', LeftMargin=3, RightMargin=2, TopMargin=2, BottomMargin=2),
        ], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual(['12/31/2000 10:59 AM'], dom.obj('clock1').lines())
        self.assertEqual('rgb(230, 230, 230)', dom.obj('clock1').body().attrs['fill'])
        self.assertEqual(['clock'], dom.obj('analog1').lines())
        self.assertEqual(['12/31/2000 10:59:39 AM'], dom.obj('dt1').lines())
        self.assertEqual(['12/31/2000'], dom.obj('dt2').lines())

    def test_bar_going_up_has_its_ranges_scale_and_value_marker(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Bar', 'bar1', FONT, Left=236, Top=223, Width=64, Height=498, BackColor='241, 241, 242',
                 BorderColor='71, 73, 87', BorderWidth=1, CornerRadius=0, EdgeStyle='Solid', Flashing='None',
                 BarOrientation='Up', ScalePosition='LeftUp', ShowScale='true', ShowTickLabels='true', ShowProcessValue='true',
                 ShowLimitRanges='true', MinimumValue=0, MaximumValue=100, CountSubDivisions=9, ScaleColor='49, 52, 74',
                 RangeUpper2Enabled='true', RangeUpper2Color='237, 88, 97', RangeUpper1Enabled='false',
                 RangeUpper1Color='241, 161, 44', RangeNormalEnabled='true', RangeNormalColor='56, 195, 70',
                 RangeLower1Enabled='false', RangeLower1Color='241, 161, 44', RangeLower2Enabled='true',
                 RangeLower2Color='237, 88, 97')], Number=1))

        dom = self.page(screen='Main')

        bar = dom.obj('bar1')
        self.assertEqual([str(v) for v in range(0, 101, 10)] + ['50'], bar.lines())
        ranges = bar.find_all(lambda n: 'bar-range' in n.classes)
        self.assertEqual(['rgb(237, 88, 97)', 'rgb(56, 195, 70)', 'rgb(237, 88, 97)'], [z.attrs['fill'] for z in ranges])
        self.assertEqual(11, len(bar.find_all(lambda n: 'bar-major' in n.classes)))
        self.assertEqual(90, len(bar.find_all(lambda n: 'bar-minor' in n.classes)))
        self.assertIsNotNone(bar.find(lambda n: 'bar-value' in n.classes))

    def test_bar_labels_are_rounded(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Bar', 'bar1', FONT, Left=236, Top=223, Width=64, Height=498, BackColor='241, 241, 242',
                 BorderColor='71, 73, 87', BorderWidth=1, CornerRadius=0, EdgeStyle='Solid', Flashing='None',
                 BarOrientation='Up', ScalePosition='LeftUp', ShowScale='true', ShowTickLabels='true', ShowProcessValue='true',
                 ShowLimitRanges='false', MinimumValue=-1, MaximumValue=0.2, CountSubDivisions=0, ScaleColor='49, 52, 74')],
            Number=1))

        lines = self.page(screen='Main').obj('bar1').lines()

        self.assertEqual(['-1', '-0.88', '-0.76', '-0.64', '-0.52', '-0.4', '-0.28', '-0.16', '-0.04', '0.08', '0.2', '-0.4'],
                         lines)

    def test_invisible_button_has_the_black_frame_of_the_editor(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Button', 'inv1', Left=300, Top=300, Width=50, Height=50, Mode='Invisible')], Number=1))

        dom = self.page(screen='Main')

        frame = dom.obj('inv1').find(lambda n: 'invisible-frame' in n.classes)     # app.css: the Run mode switch
        self.assertEqual('rgb(0, 0, 0)', frame.attrs['stroke'])
        self.assertTrue(dom.obj('inv1').body().attrs['fill'].startswith('url(#invisible'))

    def test_the_template_layer_carries_half_strength_under_a_screen_and_not_in_its_own_view(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [rect('tplRect')]))
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('own')], template='Tpl', Number=1))

        under = self.page(screen='Main').find(lambda n: 'layer-template' in n.classes)
        own = self.page(template='Tpl')

        self.assertEqual('0.5', under.attrs['opacity'])
        self.assertNotIn('opacity', own.find(lambda n: 'layer-template' in n.classes).attrs)

    def test_shapes_lines_and_boxes(self):
        pts = '\ufeff<Item>10, 100</Item><Item>60, 150</Item><Item>110, 100</Item>'
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Polyline', 'poly1', Points=pts),
            item('Hmi.Screen.Polygon', 'gon1', Points=pts),
            item('Hmi.Screen.Line', 'line1', StartLeft=5, StartTop=200, EndLeft=305, EndTop=200),
            item('Hmi.Screen.Circle', 'circ1', Left=400, Top=100, Width=40, Height=40),
            item('Hmi.Screen.Circle', 'circ2', Left=500, Top=100, Radius=15),
            item('Hmi.Screen.Clock', 'clock1', Left=600, Top=100, Width=100, Height=30),
            item('Hmi.Screen.GraphicView', 'pic1', '<LinkList>%s</LinkList>' % link('Picture', 'Logo'),
                 Left=700, Top=100, Width=64, Height=64),
            item('Hmi.Screen.FaceplateInstance', 'fp1', Left=10, Top=300, Width=200, Height=100,
                 FaceplateTypeName='_Library@$@Silo@$@Faceplate@$@faceplateSilo V 0.0.3'),
            item('Hmi.Screen.Button', 'inv1', Left=300, Top=300, Width=50, Height=50, Mode='Invisible'),
        ], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual('10,100 60,150 110,100', dom.obj('poly1').body().attrs['points'])
        self.assertEqual('polygon', dom.obj('gon1').body().tag)
        line = dom.obj('line1').body()
        self.assertEqual((5, 200, 305, 200), tuple(line.num(k) for k in ('x1', 'y1', 'x2', 'y2')))
        c = dom.obj('circ1').body()                    # the 1 px border lies inside the circle
        self.assertEqual((420, 120, 19.5, 19.5), tuple(c.num(k) for k in ('cx', 'cy', 'rx', 'ry')))
        c2 = dom.obj('circ2').body()
        self.assertEqual((515, 115, 14.5), (c2.num('cx'), c2.num('cy'), c2.num('rx')))
        self.assertEqual((600, 100, 100, 30), box_of(dom.obj('clock1')))
        self.assertEqual(['Logo'], dom.obj('pic1').lines())
        self.assertEqual(['faceplateSilo V 0.0.3'], dom.obj('fp1').lines())
        self.assertEqual((300, 300, 50, 50), box_of(dom.obj('inv1')))
        self.assertEqual([], dom.obj('inv1').lines())

    def test_unknown_type_is_a_labelled_not_drawn_box(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.TrendView', 'trend1', Left=10, Top=100, Width=400, Height=200)], Number=1))

        obj = self.page(screen='Main').obj('trend1')

        self.assertIn('not-drawn', obj.classes)
        self.assertEqual((10, 100, 400, 200), box_of(obj))
        self.assertEqual(['not drawn: TrendView'], obj.lines())

    def test_bar_and_date_time_field_are_labelled_boxes(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Bar', 'bar1', Left=10, Top=100, Width=60, Height=300, BackColor='241, 241, 242',
                 BorderColor='71, 73, 87', BorderWidth=1, CornerRadius=0, EdgeStyle='Solid', Flashing='None',
                 BarOrientation='Right', ScalePosition='LeftUp', ShowScale='true'),
            item('Hmi.Screen.DateTimeField', 'dt1', Left=100, Top=100, Width=200, Height=40,
                 BackColor='255, 255, 255', BackFillStyle='Solid', BorderColor='71, 73, 87', BorderWidth=2,
                 CornerRadius=0, EdgeStyle='Solid', Flashing='None', LongDateTimeFormat='true')], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual(['bar'], dom.obj('bar1').lines())
        self.assertEqual(['date/time'], dom.obj('dt1').lines())
        self.assertNotIn('not-drawn', dom.obj('bar1').classes)
        self.assertEqual((10, 100, 60, 300), box_of(dom.obj('bar1')))

    def test_layer_hidden_in_the_editor_is_not_drawn(self):
        hidden = ('<Hmi.Screen.ScreenLayer ID="0" CompositionName="Layers"><AttributeList><Index>2</Index><Name />'
                  '<VisibleES>false</VisibleES></AttributeList><ObjectList>%s</ObjectList></Hmi.Screen.ScreenLayer>'
                  % rect('onHidden', left=300))
        doc = document('screen', 'Main', [rect('shown')], Number=1)
        doc = doc.replace('</ObjectList></Hmi.Screen.Screen>', hidden + '</ObjectList></Hmi.Screen.Screen>')
        self.repo.export('screen', 'Main', doc)

        dom = self.page(screen='Main')

        self.assertIsNotNone(dom.obj('shown'))
        self.assertIsNone(dom.obj('onHidden'))

    def test_group_members_are_drawn_inside_the_group(self):
        members = rect('m1', left=10, top=100) + rect('m2', left=200, top=100)
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.Group', 'grp1', '<ObjectList>%s</ObjectList>' % members)], Number=1))

        dom = self.page(screen='Main')

        grp = dom.find(lambda n: 'group' in n.classes and n.attrs.get('data-name') == 'grp1')
        self.assertEqual(['m1', 'm2'], [n.attrs['data-name'] for n in grp.find_all(lambda n: 'obj' in n.classes)])
        self.assertEqual((200, 100, 100, 50), box_of(dom.obj('m2')))

    def test_template_is_drawn_under_the_screen(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [rect('tplHeader', left=0, top=0, width=1280,
                                                                               height=80)]))
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], template='Tpl', Number=1))

        dom = self.page(screen='Main')

        objs = self.screen(dom).find_all(lambda n: 'obj' in n.classes)
        self.assertEqual([('tplHeader', 'template'), ('r1', 'screen')],
                         [(n.attrs['data-name'], n.attrs['data-source']) for n in objs])
        self.assertEqual((0, 0, 1280, 80), box_of(dom.obj('tplHeader')))

    def test_screen_is_drawn_at_device_resolution_portrait_swapped(self):
        self.repo = FixtureRepo(type_identifier='OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0//Portrait')
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))

        svg = self.screen(self.page())

        self.assertEqual(('480', '800', '1'), (svg.attrs['width'], svg.attrs['height'], svg.attrs['data-zoom']))
        self.assertEqual('Main', svg.attrs['data-screen'])      # start screen

    def test_fit_hook_zooms_to_fit(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))
        self.assertEqual('fit', self.screen(self.page(fit='1')).attrs['data-zoom'])

    def test_rectangle_is_drawn_at_its_position_and_size(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            rect('r1', left=10, top=90, width=100, height=50, BackColor='255, 0, 0')], Number=1))

        dom = self.page(screen='Main')

        body = dom.obj('r1').body()
        self.assertEqual((10, 90, 100, 50), (body.num('x'), body.num('y'), body.num('width'), body.num('height')))
        self.assertEqual('Rectangle', dom.obj('r1').attrs['data-type'])
        self.assertEqual('Main', self.screen(dom).attrs['data-screen'])


def loaded_screen():
    """Screen Main with a Loaded event (SetTag hmiScreen 7) and a rectangle r1."""
    loaded = event('Loaded', func('SetTag', ('Tag', 'link', 'hmiScreen'), ('Value', 'int', 7)))
    return document('screen', 'Main', [rect('r1')], Number=1).replace(
        '<ObjectList><Hmi.Screen.ScreenLayer', '<ObjectList>%s<Hmi.Screen.ScreenLayer' % loaded, 1)


def fit_height(dom):
    """The screen's drawn height in pixels (its style, set by the zoom)."""
    return float(re.search(r'height:\s*([\d.]+)px', dom.by_id('screen').attrs['style']).group(1))


def log_lines(dom):
    """The event log's sentences, newest first (without the time)."""
    return [n.find(lambda c: 'say' in c.classes).text()
            for n in dom.by_id('event-log').find_all(lambda n: 'log-entry' in n.classes)]


class EditorLookTest(BrowserCase):
    """Inspect mode and a PNG look as the editor, Run mode as the panel; pixels of a real screenshot."""
    RED, GREEN, BLACK = (255, 0, 0), (0, 255, 0), (0, 0, 0)

    def setUp(self):
        super().setUp()
        fill = dict(BackFillStyle='Solid', BorderWidth=0)
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [
            rect('tplRect', left=10, top=10, width=100, height=100, BackColor='255, 0, 0', **fill)]))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            rect('under', left=150, top=10, width=100, height=100, BackColor='0, 255, 0', **fill),
            item('Hmi.Screen.Button', 'inv1', Left=175, Top=35, Width=50, Height=50, Mode='Invisible'),
            rect('other', left=300, top=10, width=20, height=20, BackColor='255, 255, 255', **fill),
        ], template='Tpl', Number=1, BackColor='0, 0, 255'))

    def look(self, **params):
        """(a pixel in the template's red at full strength, at half strength over the blue screen, black pixels of the
        invisible button's frame and dots: those inside the green rectangle under it)."""
        px = self.shot(screen='Main', **params)
        green = [p for p, c in px.items() if c == self.GREEN]
        xs, ys = [p[0] for p in green], [p[1] for p in green]
        black = sum(c == self.BLACK and min(xs) <= p[0] <= max(xs) and min(ys) <= p[1] <= max(ys) for p, c in px.items())
        half = any(abs(c[0] - 128) <= 1 and c[1] == 0 and abs(c[2] - 128) <= 1 for c in px.values())
        return self.RED in px.values(), half, black

    def test_run_mode_looks_as_the_panel(self):
        self.assertEqual((True, False, 0), self.look())

    def test_inspect_mode_looks_as_the_editor(self):
        full, half, black = self.look(inspect='other')
        self.assertEqual((False, True), (full, half))
        self.assertGreaterEqual(black, 196)                     # the frame of a 50 x 50 button alone

    def test_a_png_looks_as_the_editor(self):
        full, half, black = self.look(png='1')
        self.assertEqual((False, True), (full, half))
        self.assertGreaterEqual(black, 196)


class RunModeTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            nav_button('btnSilo', 'Silo'), nav_button('btnGhost', 'Ghost', left=200)], Number=1))
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [
            rect('siloPanel'),
            button('btnBack', 'Back', event('Click', func('ActivatePreviousScreen')), left=300, top=300)], Number=2))

    def test_click_on_a_navigation_button_shows_the_target_screen(self):
        dom = self.page(screen='Main', click='btnSilo')

        svg = self.screen(dom)
        self.assertEqual(('Silo', 'ok', 'generated'), (svg.attrs['data-screen'], svg.attrs['data-state'],
                                                      svg.attrs['data-origin']))
        self.assertIsNotNone(dom.obj('siloPanel'))
        self.assertIsNone(dom.obj('btnSilo'))
        self.assertEqual('Button btnSilo, Click: open screen Silo', log_lines(dom)[0])

    def test_previous_screen_returns_to_where_the_click_came_from(self):
        svg = self.screen(self.page(screen='Main', click='btnSilo,btnBack'))
        self.assertEqual('Main', svg.attrs['data-screen'])

    def test_missing_target_shows_screen_not_found(self):
        dom = self.page(screen='Main', click='btnGhost')

        svg = self.screen(dom)
        self.assertEqual(('Ghost', 'not-found'), (svg.attrs['data-screen'], svg.attrs['data-state']))
        self.assertIn('Screen not found: Ghost', svg.text())

    def test_navigation_button_on_the_template_works(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [nav_button('tplSilo', 'Silo', top=740)]))
        self.repo.export('screen', 'Other', document('screen', 'Other', [rect('r1')], template='Tpl', Number=3))
        self.assertEqual('Silo', self.screen(self.page(screen='Other', click='tplSilo')).attrs['data-screen'])

    def test_other_functions_go_to_the_event_log(self):
        tag = '<Hmi.Event.FunctionListEntryParameter ID="0" CompositionName="Parameters"><AttributeList><Name>Tag' \
              '</Name></AttributeList><LinkList>%s</LinkList></Hmi.Event.FunctionListEntryParameter>' % link('Tag', 'hmiMode')
        set_tag = func('SetTag', ('Value', 'int', 3)).replace('<ObjectList>', '<ObjectList>' + tag, 1)
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            button('btnSet', 'Set', event('Press', func('SetBitWhileKeyPressed', ('Bit', 'int', 0))) +
                   event('Release', set_tag))], Number=1))

        dom = self.page(screen='Main', click='btnSet')

        lines = log_lines(dom)
        self.assertIn('Button btnSet, Press: would set bit 0 while pressed', lines)
        self.assertIn('Button btnSet, Release: would set tag hmiMode to 3', lines)
        self.assertEqual('Main', self.screen(dom).attrs['data-screen'])


class PopupTest(BrowserCase):
    def setUp(self):
        super().setUp()
        show = event('Click', func('ShowPopupScreen', ('Name of the screen', 'link', 'Pop'), ('X coordinate', 'int', 200),
                                   ('Y coordinate', 'int', 150), ('Display mode', 'int', -1),
                                   ('Animation', 'int', -1), ('Animation speed', 'int', 1)))
        self.repo.export('screen', 'Main', document('screen', 'Main', [button('btnPop', 'Pop', show)], Number=1))
        close = event('Click', func('ShowPopupScreen', ('Name of the screen', 'self', None), ('X coordinate', 'int', 0),
                                    ('Y coordinate', 'int', 0), ('Display mode', 'int', 0)))
        self.repo.export('popup', 'Pop', document('popup', 'Pop', [
            rect('popRect', left=10, top=10, width=50, height=20),
            button('btnClose', 'X', close, left=100, top=10, width=30, height=30)], Width=300, Height=200))

    def popup(self, dom):
        return dom.find(lambda n: n.attrs.get('data-popup') == 'Pop')

    def test_show_popup_opens_it_at_its_coordinates(self):
        dom = self.page(screen='Main', click='btnPop')

        pop = self.popup(dom)
        self.assertEqual('translate(200,150)', pop.attrs['transform'])
        self.assertEqual((10, 10, 50, 20), box_of(dom.obj('popRect')))       # relative to the pop-up
        self.assertEqual('popup', dom.obj('popRect').attrs['data-source'])

    def test_toggle_closes_it_again(self):
        self.assertIsNone(self.popup(self.page(screen='Main', click='btnPop,btnPop')))

    def test_popup_closes_itself(self):
        dom = self.page(screen='Main', click='btnPop,btnClose')
        self.assertIsNone(self.popup(dom))
        self.assertEqual('Main', self.screen(dom).attrs['data-screen'])
        self.assertEqual(['Button btnClose, Click: close pop-up Pop', 'Button btnPop, Click: open pop-up Pop at 200, 150'],
                         log_lines(dom))


class EventStripTest(BrowserCase):
    """The event log is a strip along the bottom, newest first, each entry a sentence."""

    def setUp(self):
        super().setUp()
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            nav_button('btnSilo', 'Silo'), nav_button('btnGhost', 'Ghost', left=200)], Number=1))
        self.repo.export('screen', 'Silo', document('screen', 'Silo', [
            button('btnBack', 'Back', event('Click', func('ActivatePreviousScreen')), left=300, top=300)], Number=2))

    def test_the_strip_is_below_the_screen_outside_the_tree_and_the_side_panel(self):
        dom = self.page(screen='Main')

        strip = dom.by_id('events')
        self.assertIsNotNone(strip.find(lambda n: n.attrs.get('id') == 'event-log'))
        app = dom.find(lambda n: 'app' in n.classes and n.tag == 'div')
        self.assertIn(strip, app.children)
        self.assertGreater(app.children.index(strip), app.children.index(app.find(lambda n: 'body' in n.classes)))

    def test_logging_moves_nothing_outside_the_strip(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            button('btnSet', 'Set', event('Click', func('SetTag', ('Tag', 'link', 'hmiMode'), ('Value', 'int', 1))))],
            Number=1))
        before = self.shot(screen='Main')
        after = self.shot(screen='Main', click=','.join(['btnSet'] * 12))       # more entries than the strip shows

        # the tree at full height; right of it all but the header (its load time) and the strip at the bottom
        kept = [p for p in before if p[0] < 260 or 60 <= p[1] < 600 - 170]
        moved = [p for p in kept if before[p] != after[p]]
        self.assertEqual([], sorted({p[1] for p in moved}))

    def test_the_strip_shows_in_run_mode_only(self):
        self.repo.export('screen', 'Main', loaded_screen())
        bar = (240, 240, 240)                                       # the strip's bar, var(--row)

        def bar_pixels(px):
            return sum(1 for (x, y), c in px.items() if x >= 260 and y > 400 and c == bar)

        self.assertGreater(bar_pixels(self.shot(screen='Main')), 500)
        self.assertEqual(0, bar_pixels(self.shot(screen='Main', inspect='r1')))
        self.assertEqual([], log_lines(self.page(screen='Main', inspect='r1')))   # events come from Run only

    def test_fit_follows_the_mode_the_strip_shows_in_run_only(self):
        wide = (1600, 600)                                  # the fit is bound by the height, which the strip takes
        run = fit_height(self.page(wide, screen='Main', fit='1'))
        inspect = fit_height(self.page(wide, screen='Main', fit='1', inspect='btnSilo'))
        self.assertGreater(inspect, run)

        self.assertEqual(inspect, fit_height(self.page(wide, screen='Main', fit='1', keys='i')))
        self.assertEqual(run, fit_height(self.page(wide, screen='Main', fit='1', inspect='btnSilo', keys='r')))

    def test_key_l_closes_the_strip_in_run_mode_only(self):
        self.assertIn('shut', self.page(screen='Main', keys='l').by_id('events').classes)
        self.assertNotIn('shut', self.page(screen='Main', keys='i,l,r').by_id('events').classes)

    def test_entries_are_sentences_newest_first(self):
        dom = self.page(screen='Main', click='btnSilo,btnBack,btnGhost')

        self.assertEqual(['Button btnGhost, Click: open screen Ghost, not in the project',
                          'Button btnBack, Click: back to screen Main',
                          'Button btnSilo, Click: open screen Silo'], log_lines(dom))
        self.assertEqual('3', dom.by_id('events-n').text())
        entries = dom.by_id('event-log').find_all(lambda n: 'log-entry' in n.classes)
        self.assertEqual([('missing', 'btnGhost', 'Click'), ('nav', 'btnBack', 'Click'), ('nav', 'btnSilo', 'Click')],
                         [(e.classes[1], e.attrs['data-object'], e.attrs['data-event']) for e in entries])

    def test_the_newest_entry_shows_in_the_bar(self):
        dom = self.page(screen='Main', click='btnSilo')
        self.assertEqual('Button btnSilo, Click: open screen Silo', dom.by_id('events-last').text())

    def test_tag_functions_say_what_they_would_do(self):
        calls = (func('SetTag', ('Tag', 'link', 'hmiMode'), ('Value', 'int', 3)) +
                 func('SetBit', ('Tag', 'link', 'bitA')) + func('ResetBit', ('Tag', 'link', 'bitB')) +
                 func('InvertBit', ('Tag', 'link', 'bitC')) +
                 func('IncreaseTag', ('Tag', 'link', 'count'), ('Value', 'int', 5)) +
                 func('DecreaseTag', ('Tag', 'link', 'count'), ('Value', 'int', 2)) +
                 func('StopRuntime', ('Mode', 'int', 0)))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            button('btnAll', 'All', event('Click', calls)),
            button('btnBits', 'Bits', event('Press', func('SetBitWhileKeyPressed', ('Tag', 'link', 'hmiKeys'),
                                                                ('Bit', 'int', 4))), left=200)], Number=1))

        dom = self.page(screen='Main', click='btnAll,btnBits')

        self.assertEqual(['Button btnBits, Press: would set bit 4 of tag hmiKeys while pressed',
                          'Button btnAll, Click: would call StopRuntime with Mode = 0',
                          'Button btnAll, Click: would subtract 2 from tag count',
                          'Button btnAll, Click: would add 5 to tag count',
                          'Button btnAll, Click: would invert tag bitC',
                          'Button btnAll, Click: would set tag bitB to 0',
                          'Button btnAll, Click: would set tag bitA to 1',
                          'Button btnAll, Click: would set tag hmiMode to 3'], log_lines(dom))

    def test_screen_events_name_the_screen(self):
        self.repo.export('screen', 'Main', loaded_screen())

        dom = self.page(screen='Main')

        self.assertEqual(['Screen Main, Loaded: would set tag hmiScreen to 7'], log_lines(dom))

    def test_the_type_is_the_toolbox_name(self):
        io = item('Hmi.Screen.IOField', 'ioSpeed', '<ObjectList>%s</ObjectList>' % event(
            'Click', func('SetTag', ('Tag', 'link', 'speed'), ('Value', 'int', 0))),
            Left=10, Top=100, Width=120, Height=24)
        self.repo.export('screen', 'Main', document('screen', 'Main', [io], Number=1))

        dom = self.page(screen='Main', click='ioSpeed')

        self.assertEqual(['I/O field ioSpeed, Click: would set tag speed to 0'], log_lines(dom))


class MarkingTest(BrowserCase):
    def test_exported_screen_says_exported(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual('tia', self.screen(dom).attrs['data-origin'])
        self.assertEqual('Exported', dom.by_id('origin').text())          # the maintainer's words

    def test_generated_screen_says_generated(self):
        self.repo.generated('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))
        dom = self.page(screen='Main')
        self.assertEqual('generated', self.screen(dom).attrs['data-origin'])
        self.assertEqual('Generated', dom.by_id('origin').text())

    def test_object_with_a_planned_link_carries_a_planned_badge(self):
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew', 'note': 'modes'}])
        self.repo.generated('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.SymbolicIOField', 'sym1', '<LinkList>%s</LinkList>' % link('TextList', 'tlNew'),
                 Left=100, Top=100, Width=120, Height=24),
            rect('r1', left=400)], Number=1))

        dom = self.page(screen='Main')

        self.assertIsNotNone(dom.obj('sym1').find(lambda n: 'planned' in n.classes and 'badge' in n.classes))
        self.assertIsNone(dom.obj('r1').find(lambda n: 'badge' in n.classes))
        planned = dom.by_id('planned').find_all(lambda n: 'planned-item' in n.classes)
        self.assertEqual([('textlist', 'tlNew')], [(n.attrs['data-kind'], n.attrs['data-name']) for n in planned])

    def test_handbuilt_objects_are_hatched_labelled_placeholders(self):
        self.repo.export('screen', 'Alarms', document('screen', 'Alarms', [rect('r1')], Number=1))
        self.repo.handbuilt([{'screen': 'Alarms', 'kind': 'alarm view', 'x': 0, 'y': 80, 'w': 1280, 'h': 500},
                             {'screen': 'Other', 'kind': 'trend view', 'x': 0, 'y': 80, 'w': 100, 'h': 100}])

        dom = self.page(screen='Alarms')

        hb = dom.find_all(lambda n: 'handbuilt' in n.classes and 'obj' in n.classes)
        self.assertEqual(1, len(hb))
        self.assertEqual((0, 80, 1280, 500), box_of(hb[0]))
        self.assertEqual('url(#hatch)', hb[0].body().attrs['fill'])
        self.assertIn('alarm view', hb[0].text())


def tree_of(dom):
    """The project tree as {folder path: [(name, kind, state)]}, folder paths joined with /."""
    out = {}

    def walk(ul, path):
        for li in [c for c in ul.children if not isinstance(c, str) and c.tag == 'li']:
            if 'fd' in li.classes:
                name = li.find(lambda n: 'nm' in n.classes).text()
                walk(li.find(lambda n: n.tag == 'ul'), path + [name])
            else:
                a = li.find(lambda n: n.tag == 'a')
                out.setdefault('/'.join(path), []).append(
                    (a.attrs['data-name'], a.attrs['data-kind'], a.classes[1]))
    walk(dom.find(lambda n: n.tag == 'ul' and 'tree' in n.classes), [])
    return out


class ProjectTreeTest(BrowserCase):
    """The change report's project tree, TIA's folders, each document once by its name."""

    def test_tias_folders_with_screens_templates_popups_and_text_lists(self):
        self.repo.export('screen', '010 - Overview', document('screen', '010 - Overview', Number=10), folder='Main')
        self.repo.generated('screen', '020 - Silo', document('screen', '020 - Silo', Number=20),
                            folder='Stations/G05')
        self.repo.export('template', 'Tpl', document('template', 'Tpl'))
        self.repo.export('popup', 'Pop', document('popup', 'Pop', Width=300, Height=200))
        self.repo.export('textlist', 'tlMode', TEXTLIST % ('tlMode', ''))

        dom = self.page()

        self.assertEqual({'HMI/Screens/Main': [('010 - Overview', 'screen', 'none')],
                          'HMI/Screens/Stations/G05': [('020 - Silo', 'screen', 'none')],
                          'HMI/Screen management/Pop-up screens': [('Pop', 'popup', 'none')],
                          'HMI/Screen management/Templates': [('Tpl', 'template', 'none')],
                          'HMI/Text and graphic lists': [('tlMode', 'textlist', 'none')]}, tree_of(dom))
        self.assertEqual('010 - Overview', self.screen(dom).attrs['data-screen'])   # start screen: lowest number
        sel = dom.find(lambda n: n.tag == 'a' and 'sel' in n.classes)
        self.assertEqual('010 - Overview', sel.attrs['data-name'])                  # the open view marked
        self.assertEqual('010 - Overview', sel.find(lambda n: 'nm' in n.classes).text())   # the name once

    def test_marks_are_the_change_reports_and_follow_the_diff(self):
        self.repo.export('screen', 'Same', document('screen', 'Same', [rect('r1')], Number=1))
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1')], Number=2))
        self.repo.commit()
        self.repo.generated('screen', 'Silo', document('screen', 'Silo', [rect('r1', left=50)], Number=2))
        self.repo.generated('screen', 'New', document('screen', 'New', Number=3))

        states = {n: s for n, _, s in tree_of(self.page(screen='Silo', diff='commit'))['HMI/Screens']}
        self.assertEqual({'Same': 'same', 'Silo': 'changed', 'New': 'new'}, states)
        states = {n: s for n, _, s in tree_of(self.page(screen='Silo', diff='export'))['HMI/Screens']}
        self.assertEqual({'Same': 'same', 'Silo': 'new', 'New': 'new'}, states)     # Silo is not in TIA yet

    def test_every_device_in_one_tree_the_header_follows_the_open_one(self):
        self.repo = FixtureRepo(type_identifier={'HMI_A': TP1200, 'HMI_B': 'OrderNumber:6AV2 124-0GC01-0AX0/17.0.0.0'})
        self.addCleanup(self.repo.cleanup)
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('rA')], Number=1), device='HMI_A')
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('rB')], Number=1, Width=800, Height=480),
                         device='HMI_B')

        dom = self.page(device='HMI_B', screen='Main')

        self.assertEqual({'HMI_A/Screens': [('Main', 'screen', 'none')], 'HMI_B/Screens': [('Main', 'screen', 'none')]},
                         tree_of(dom))
        self.assertEqual(('800', 'HMI_B'), (self.screen(dom).attrs['width'], dom.by_id('view-device').text()))
        self.assertIsNotNone(dom.obj('rB'))
        sel = dom.find(lambda n: n.tag == 'a' and 'sel' in n.classes)
        self.assertEqual('HMI_B', sel.attrs['data-device'])
        self.assertEqual('1280', self.screen(self.page(device='HMI_A', screen='Main')).attrs['width'])

    def test_the_rail_is_the_change_reports(self):
        dom = self.page()

        nav = dom.find(lambda n: n.tag == 'nav' and 'rail' in n.classes)
        self.assertIsNotNone(nav.find(lambda n: n.tag == 'input' and n.attrs.get('type') == 'search'))
        self.assertIsNotNone(dom.find(lambda n: 'lch' in n.classes))                  # the Ctrl+K lookup
        self.assertEqual('?', nav.find(lambda n: 'rq' in n.classes).text())           # the button of the key list


TEXTLIST = ('<?xml version="1.0" encoding="utf-8"?>\n<Document><Engineering version="V20" />'
            '<Hmi.TextGraphicList.TextList ID="0"><AttributeList><Name>%s</Name></AttributeList>'
            '<ObjectList>%s</ObjectList></Hmi.TextGraphicList.TextList></Document>\n')


def textlist_entries(*entries):
    return ''.join('<Hmi.TextGraphicList.TextListEntry ID="0" CompositionName="Entries"><AttributeList><From>%d</From>'
                   '<To>%d</To></AttributeList><ObjectList>%s</ObjectList></Hmi.TextGraphicList.TextListEntry>'
                   % (v, v, ml_text('Text', [t])) for v, t in entries)


class HeaderTest(BrowserCase):
    def test_panel_start_screen_and_findings_count(self):
        self.repo.panel('TP1200 Comfort', 1280, 800)
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Invented', 'thing1', Left=1, Top=90, Width=2, Height=2)], Number=2))

        dom = self.page(screen='New')

        self.assertEqual('TP1200 Comfort 1280 x 800', dom.by_id('device').text())
        self.assertEqual('Main', dom.by_id('start-screen').text())
        fc = dom.by_id('findings-count')
        self.assertEqual('error', fc.classes[1])
        self.assertGreaterEqual(int(fc.attrs['data-errors']), 1)
        self.assertEqual('New', dom.by_id('view-title').text())

    def test_text_list_shows_its_entries(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', Number=1))
        self.repo.export('textlist', 'tlMode', TEXTLIST % ('tlMode', textlist_entries((0, 'Off'), (1, 'Auto'))))

        dom = self.page(textlist='tlMode')

        rows = dom.by_id('textlist').find_all(lambda n: 'entry' in n.classes)
        self.assertEqual([('0', 'Off'), ('1', 'Auto')],
                         [(r.attrs['data-value'], r.children[1].text()) for r in rows])
        self.assertEqual('textlist', self.screen(dom).attrs['data-state'])
        self.assertEqual('Text list tlMode', dom.by_id('view-title').text())


class FindingsListTest(BrowserCase):
    """The findings below the screen, in sentences, by document and rule; a click opens the object."""

    def overlaps(self):
        self.repo.export('screen', 'Ref', document('screen', 'Ref', [rect('r0')], Number=1))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            rect('recBack', 100, 100, 400, 100),
            item('Hmi.Screen.Rectangle', 'rA', Left=80, Top=120, Width=60, Height=40),
            item('Hmi.Screen.Rectangle', 'rB', Left=460, Top=180, Width=60, Height=40),
            item('Hmi.Screen.Invented', 'gauge1', Left=600, Top=400, Width=20, Height=20)], Number=2))

    def test_findings_are_listed_below_the_screen_in_sentences(self):
        self.overlaps()

        dom = self.page(screen='Ref')

        main = dom.by_id('main')
        self.assertEqual(['canvas', 'findings'], [c.attrs.get('id') for c in main.children if not isinstance(c, str)])
        box = dom.find(lambda n: 'fdoc' in n.classes)
        self.assertEqual('hmi/generated/screens/New.xml', box.attrs['data-document'])
        rows = {(n.attrs['data-rule'], n.attrs['data-object']): n.text() for n in
                dom.by_id('findings').find_all(lambda n: 'finding' in n.classes)}
        self.assertIn(('vocabulary.element-type', 'gauge1'), rows)
        self.assertEqual('Rectangle rA overlaps rectangle recBack.', rows[('geometry.overlap', 'rA')])
        fold = dom.find(lambda n: 'ffold' in n.classes)
        self.assertIn('2 rectangles overlap rectangle recBack', fold.text())
        self.assertNotIn('open', fold.classes)

    def test_a_click_on_a_finding_opens_its_screen_with_the_object_selected(self):
        self.overlaps()

        dom = self.page(screen='Ref', finding='rB')

        self.assertEqual('New', self.screen(dom).attrs['data-screen'])
        self.assertIn('selected', dom.obj('rB').classes)
        self.assertEqual('rB', dom.by_id('inspect').attrs['data-name'])
        self.assertTrue([n for n in dom.by_id('findings').find_all(lambda n: 'finding' in n.classes and 'sel' in n.classes)
                         if n.attrs['data-object'] == 'rB'])

    def test_a_click_selects_the_object_of_the_finding_s_document_not_one_of_an_open_pop_up(self):
        show = event('Click', func('ShowPopupScreen', ('Name of the screen', 'link', 'Pop'), ('X coordinate', 'int', 0),
                                   ('Y coordinate', 'int', 0), ('Display mode', 'int', -1)))
        self.repo.generated('screen', 'Main', document('screen', 'Main', [
            button('btnPop', 'Pop', show, left=600, top=400, width=60, height=30),
            rect('recBack', 100, 100, 400, 100), rect('dup', 80, 120, 60, 40)], Number=1))
        self.repo.export('popup', 'Pop', document('popup', 'Pop', [rect('dup', 10, 10, 50, 20)], Width=300, Height=200))

        dom = self.page(screen='Main', click='btnPop', finding='dup')

        self.assertIsNotNone(dom.find(lambda n: n.attrs.get('data-popup') == 'Pop'))
        [sel] = dom.find_all(lambda n: n.attrs.get('data-name') == 'dup' and 'selected' in n.classes)
        self.assertEqual('screen', sel.attrs['data-source'])

    def test_a_group_s_finding_opens_its_screen_without_promising_a_selection(self):
        self.repo.export('screen', 'Ref', document('screen', 'Ref', [rect('r0')], Number=1))
        self.repo.generated('screen', 'New', document('screen', 'New', [
            group('grp', rect('a', 10, 100)), group('grp', rect('b', 300, 100))], Number=2))

        dom = self.page(screen='Ref', finding='grp')

        self.assertEqual('New', self.screen(dom).attrs['data-screen'])
        row = dom.find(lambda n: 'finding' in n.classes and n.attrs.get('data-object') == 'grp')
        self.assertEqual('Open New', row.attrs['title'])
        self.assertNotIn('no such object', dom.by_id('notice').text())

    def test_findings_of_an_export_a_generated_document_replaces_do_not_open(self):
        self.repo.export('screen', 'Ref', document('screen', 'Ref', [rect('r0')], Number=1, export_setting='None'))
        self.repo.export('screen', 'New', document('screen', 'New', [rect('r0')], Number=2, export_setting='None'))
        self.repo.generated('screen', 'New', document('screen', 'New', [rect('r1')], Number=2))

        dom = self.page(screen='New')

        rows = {n.attrs['data-document']: 'go' in n.classes for n in
                dom.by_id('findings').find_all(lambda n: 'finding' in n.classes and n.attrs['data-rule'] ==
                                               'document.not-full')}
        self.assertEqual({'hmi/screens/Ref.xml': True, 'hmi/screens/New.xml': False}, rows)

    def test_objects_with_findings_carry_a_mark_shown_in_inspect_mode(self):
        self.overlaps()

        dom = self.page(screen='New', inspect='rA')

        marks = {n.attrs['data-name']: n.classes[1] for n in dom.find_all(lambda n: 'finding-mark' in n.classes)}
        self.assertEqual('warning', marks['rA'])
        self.assertEqual('error', marks['gauge1'])
        self.assertNotIn('recBack', marks)

    def test_c_collapses_and_e_expands_every_box_and_fold(self):
        self.overlaps()

        shut = self.page(screen='Ref', keys='c')
        opened = self.page(screen='Ref', keys='c,e')

        self.assertTrue(all('shut' in b.classes for b in shut.find_all(lambda n: 'fbx' in n.classes)))
        self.assertFalse(any('shut' in b.classes for b in opened.find_all(lambda n: 'fbx' in n.classes)))
        self.assertTrue(all('open' in f.classes for f in opened.find_all(lambda n: 'ffold' in n.classes)))


class InspectTest(BrowserCase):
    def test_an_object_not_on_the_screen_is_added_to_the_notices(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], template='Nope', Number=1))

        dom = self.page(screen='Main', inspect='ghost')

        self.assertEqual('Template not found: Nope; Inspect ghost: no such object on this screen',
                         dom.by_id('notice').text())
        self.assertIn('hidden', dom.by_id('inspect-section').attrs)

    def test_inspect_shows_name_type_preset_attributes_links_and_findings(self):
        self.repo.export('screen', 'Ref', document('screen', 'Ref', [rect('S-Panel', BackColor='1, 2, 3')], Number=1))
        self.repo.planned([{'kind': 'textlist', 'name': 'tlNew'}])
        path = self.repo.generated('screen', 'New', document('screen', 'New', [
            item('Hmi.Screen.Rectangle', 'r1', '<LinkList>%s</LinkList>' % link('TextList', 'tlNew'),
                 Left=10, Top=100, Width=50, Height=40, BackColor='1, 2, 3')], Number=2))
        self.repo.write('hmi/generated/generated.json', json.dumps(
            {path: {'generated': '2026-10-06T10:00:00+02:00',
                    'presets': {'r1': {'preset': 'S-Panel', 'source': 'S-Panel', 'document': 'hmi/screens/Ref.xml'}}}}))

        dom = self.page(screen='New', inspect='r1')

        panel = dom.by_id('inspect')
        self.assertEqual(('r1', 'Rectangle', 'screen'),
                         (panel.attrs['data-name'], panel.attrs['data-type'], panel.attrs['data-source']))
        props = {n.attrs['data-prop']: n.find_all(lambda c: c.tag == 'td')[1].text()
                 for n in panel.find_all(lambda n: 'data-prop' in n.attrs)}
        self.assertEqual('S-Panel', props['Style preset'])
        self.assertEqual('S-Panel in hmi/screens/Ref.xml', props['Copied from'])
        attrs = {n.attrs['data-attr']: n.find_all(lambda c: c.tag == 'td')[1].text()
                 for n in panel.find_all(lambda n: 'data-attr' in n.attrs)}
        self.assertEqual(('10', '100', '1, 2, 3'), (attrs['Left'], attrs['Top'], attrs['BackColor']))
        links = {(n.attrs['data-kind'], n.attrs['data-name']): n.attrs['data-state']
                 for n in panel.find_all(lambda n: 'link' in n.classes)}
        self.assertEqual({('textlist', 'tlNew'): 'planned', ('style', 'S-Panel'): 'exists'}, links)
        self.assertIn('links.planned', [n.attrs['data-rule'] for n in panel.find_all(lambda n: 'finding' in n.classes)])
        self.assertIn('selected', dom.obj('r1').classes)

    def test_overlap_with_template_object_keeps_both_visible(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [
            rect('tplBar', left=0, top=0, width=1280, height=80)]))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            rect('r1', left=10, top=60, width=100, height=50)], template='Tpl', Number=1))

        dom = self.page(screen='Main', inspect='r1')

        outline = dom.find(lambda n: 'overlap-outline' in n.classes)
        self.assertEqual(('tplBar', 'r1'), (outline.attrs['data-name'], outline.attrs['data-over']))
        self.assertEqual((0, 0, 1280, 80), tuple(outline.num(k) for k in ('x', 'y', 'width', 'height')))
        overlaps = dom.by_id('inspect').find_all(lambda n: 'overlap' in n.classes)
        self.assertEqual([('tplBar', 'template')], [(n.attrs['data-name'], n.attrs['data-source']) for n in overlaps])


def range_animation(tag, *ranges):
    """RangeAppearanceAnimation on a tag; ranges (lower, upper, back colour)."""
    rs = ''.join('<Hmi.Dynamic.Range ID="0" CompositionName="RangeValues"><AttributeList><BackColor>%s</BackColor>'
                 '<FlashingType>No</FlashingType><LowerLimit>%s</LowerLimit><UpperLimit>%s</UpperLimit>'
                 '</AttributeList></Hmi.Dynamic.Range>' % (c, lo, hi) for lo, hi, c in ranges)
    return ('<Hmi.Dynamic.RangeAppearanceAnimation ID="0" CompositionName="Animations"><AttributeList>'
            '<Name>RangeAppearanceAnimation</Name></AttributeList><ObjectList><Hmi.Dynamic.TagElementTrigger ID="0" '
            'CompositionName="RangeTag"><LinkList>%s</LinkList></Hmi.Dynamic.TagElementTrigger>%s</ObjectList>'
            '</Hmi.Dynamic.RangeAppearanceAnimation>' % (link('Tag', tag), rs))


def tag_property(prop, tag):
    return ('<Hmi.Screen.Property ID="0" CompositionName="Properties"><AttributeList><Name>%s</Name></AttributeList>'
            '<ObjectList><Hmi.Dynamic.TagConnectionDynamic ID="0" CompositionName="Dynamic"><AttributeList>'
            '<Indirect>false</Indirect></AttributeList><LinkList>%s</LinkList></Hmi.Dynamic.TagConnectionDynamic>'
            '</ObjectList></Hmi.Screen.Property>' % (prop, link('Tag', tag)))


class PropertyPanelTest(BrowserCase):
    """The panel laid out like TIA's Properties window, from the catalogue."""

    def rows(self, pane):
        """{export name: (display name, value text, classes)} of a pane's rows."""
        return {n.attrs['data-attr']: (n.find_all(lambda c: c.tag == 'td')[0].text(),
                                       n.find_all(lambda c: c.tag == 'td')[1].text(), n.classes)
                for n in pane.find_all(lambda n: 'row' in n.classes)}

    def pane(self, dom, tab):
        return dom.by_id('inspect').find(lambda n: 'pane' in n.classes and n.attrs.get('data-tab') == tab)

    def test_properties_in_tia_groups_with_tia_names_and_values(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            button('btnGo', 'Go', Mode='Text', BackColor='10, 20, 30', BackFillStyle='Solid', Enabled='true',
                   Invented='7')], Number=1))

        dom = self.page(screen='Main', inspect='btnGo')

        panel = dom.by_id('inspect')
        self.assertEqual('btnGo [Button]', panel.find(lambda n: 'ptitle' in n.classes).text())
        tabs = [n.attrs['data-tab'] for n in panel.find_all(lambda n: 'tab' in n.classes and n.tag == 'button')]
        self.assertEqual(['properties', 'animations', 'events', 'texts'], tabs)
        props = self.pane(dom, 'properties')
        groups = [n.attrs['data-group'] for n in props.find_all(lambda n: 'grp' in n.classes)]
        self.assertEqual(['Appearance', 'Design'], groups[:2])
        self.assertEqual('Other', groups[-1])          # the maintainer, 2026-11-05
        rows = self.rows(props)
        self.assertEqual(('Background color', '10, 20, 30'), rows['BackColor'][:2])
        self.assertEqual(('Font', 'Tahoma, 13px'), rows['@Font'][:2])
        self.assertEqual('Go', rows['@TextOff'][1])
        self.assertEqual(('Invented', '7'), rows['Invented'][:2])
        other = props.find(lambda n: n.attrs.get('data-group') == 'Other')
        self.assertIsNotNone(other)
        self.assertEqual(['TabIndex', 'Invented'], [r for r in rows if r in ('TabIndex', 'Invented')])
        self.assertIn('grey', rows['PictureAutoSizing'][2])        # Mode Text greys the graphic rows
        self.assertNotIn('grey', rows['BackColor'][2])            # greyed only by a gradient fill
        self.assertEqual(('Layer', '0'), rows['Layer'][:2])
        self.assertEqual(('Device style', ''), rows['Device style'][:2])    # TIA shows it, the export has none
        self.assertEqual('BackColor: Fill colour of the object\'s area.',
                         props.find(lambda n: n.attrs.get('data-attr') == 'BackColor')
                         .find(lambda c: c.tag == 'td').attrs['title'])

    def test_search_keeps_the_rows_whose_names_match(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [button('btnGo', 'Go')], Number=1))

        dom = self.page(screen='Main', inspect='btnGo', prop='bgcol')

        props = self.pane(dom, 'properties')
        shown = [n.attrs['data-attr'] for n in props.find_all(lambda n: 'row' in n.classes and 'hidden' not in n.attrs)]
        self.assertIn('BackColor', shown)                          # Background color
        self.assertNotIn('Width', shown)
        self.assertNotIn('TabIndex', shown)
        groups = [n.attrs['data-group'] for n in props.find_all(lambda n: 'grp' in n.classes and 'hidden' not in n.attrs)]
        self.assertIn('Appearance', groups)
        self.assertNotIn('Layout', groups)
        name = props.find(lambda n: n.attrs.get('data-attr') == 'BackColor').find(lambda c: c.tag == 'td')
        self.assertTrue(name.find(lambda c: c.tag == 'mark'))
        self.assertEqual('Background color', name.text())

        dom = self.page(screen='Main', inspect='btnGo', prop='tabindex')    # the export name matches too

        shown = [n.attrs['data-attr'] for n in self.pane(dom, 'properties').find_all(
            lambda n: 'row' in n.classes and 'hidden' not in n.attrs)]
        self.assertEqual(['TabIndex'], shown)

    def test_search_reaches_every_tab(self):
        self.repo.export('screen', 'Next', document('screen', 'Next', Number=2))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            nav_button('btnNext', 'Next'),
            item('Hmi.Screen.IOField', 'ioCount', '<ObjectList>%s</ObjectList>' % tag_property('ProcessValue', 'n'),
                 Left=10, Top=300, Width=100, Height=30)], Number=1))

        def shown(pane, cls, key):
            return [n.attrs[key] for n in pane.find_all(lambda n: cls in n.classes and 'hidden' not in n.attrs)]

        def tab_hits(dom):
            return {b.attrs['data-tab']: b.find(lambda c: 'tcount' in c.classes).text()
                    for b in dom.by_id('inspect').find_all(lambda n: 'tab' in n.classes and n.tag == 'button')}

        dom = self.page(screen='Main', inspect='btnNext', prop='activscr')  # a function's name

        events = self.pane(dom, 'events')
        self.assertEqual(['Click'], shown(events, 'ev', 'data-event'))
        self.assertEqual(['ActivateScreen'], shown(events, 'fn', 'data-function'))
        fname = events.find(lambda n: 'fname' in n.classes)
        self.assertTrue(fname.find(lambda c: c.tag == 'mark'))
        self.assertEqual('1', tab_hits(dom)['events'])

        dom = self.page(screen='Main', inspect='btnNext', prop='textoff')   # a text's export name

        self.assertEqual(['TextOff'], shown(self.pane(dom, 'texts'), 'txt', 'data-text'))
        self.assertEqual('0', tab_hits(dom)['events'])

        dom = self.page(screen='Main', inspect='ioCount', prop='procval')   # a tag connection's row

        anims = self.pane(dom, 'animations')
        self.assertEqual(['TagConnections'], shown(anims, 'anim', 'data-animation'))
        self.assertEqual(['ProcessValue'], shown(anims, 'row', 'data-attr'))

        dom = self.page(screen='Main', inspect='ioCount', prop='visib')     # an animation's own name keeps all of it

        self.assertIn('SingleBitVisibilityAnimation', shown(self.pane(dom, 'animations'), 'anim', 'data-animation'))
        self.assertNotIn('TagConnections', shown(self.pane(dom, 'animations'), 'anim', 'data-animation'))

    def test_a_font_the_document_lacks_shows_tias_default_as_tia_writes_it(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            item('Hmi.Screen.IOField', 'ioCount', Left=10, Top=300, Width=100, Height=30)], Number=1))

        dom = self.page(screen='Main', inspect='ioCount')

        font = self.pane(dom, 'properties').find(lambda n: n.attrs.get('data-attr') == '@Font')
        self.assertEqual('Not in the document; TIA takes Tahoma, 13px, Bold', font.attrs['title'])

    def test_events_animations_and_texts_tabs(self):
        self.repo.export('screen', 'Next', document('screen', 'Next', Number=2))
        self.repo.export('screen', 'Main', document('screen', 'Main', [
            nav_button('btnNext', 'Next'),
            item('Hmi.Screen.IOField', 'ioCount', '<ObjectList>%s%s</ObjectList>' % (
                tag_property('ProcessValue', 'telegramCount'),
                range_animation('telegramCount', (0, 3, '140, 140, 140'), (4, 4, '0, 160, 70'))),
                Left=10, Top=300, Width=100, Height=30)], Number=1))

        dom = self.page(screen='Main', inspect='ioCount')

        anims = self.pane(dom, 'animations')
        shown = [n.attrs['data-animation'] for n in anims.find_all(lambda n: 'anim' in n.classes)]
        self.assertEqual(['TagConnections', 'RangeAppearanceAnimation'], shown[:2])
        self.assertEqual(('Process value', 'telegramCount'), self.rows(anims)['ProcessValue'][:2])
        ranges = [n.find_all(lambda c: c.tag == 'td')[0].text() for n in anims.find_all(lambda n: 'range' in n.classes)]
        self.assertEqual(['0 - 3', '4'], ranges)
        self.assertEqual('telegramCount', self.rows(self.pane(dom, 'properties'))['tag:ProcessValue'][1])

        dom = self.page(screen='Main', inspect='btnNext')

        click = self.pane(dom, 'events').find(lambda n: n.attrs.get('data-event') == 'Click')
        fn = click.find(lambda n: 'fn' in n.classes)
        self.assertEqual('ActivateScreen', fn.attrs['data-function'])
        params = [tuple(td.text() for td in n.find_all(lambda c: c.tag == 'td'))
                  for n in fn.find_all(lambda n: 'param' in n.classes)]
        self.assertEqual([('Screen name', 'Next'), ('Object number', '0')], params)
        texts = {n.attrs['data-text']: [td.text() for td in n.find_all(lambda c: c.tag == 'td')]
                 for n in self.pane(dom, 'texts').find_all(lambda n: 'txt' in n.classes)}
        self.assertEqual(['Text OFF', 'Go Next', 'Go Next ES'], texts['TextOff'])

    def test_nothing_selected_shows_the_view_or_with_the_diff_on_the_changes(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))

        dom = self.page(screen='Main')

        self.assertEqual('view', dom.by_id('side').attrs['data-show'])
        self.assertIn('hidden', dom.by_id('diff-slot').attrs)
        view = dom.by_id('view-props')
        self.assertEqual('Main [Screen]', view.find(lambda n: 'ptitle' in n.classes).text())
        self.assertEqual('1280', self.rows(view)['Width'][1])

        dom = self.page(screen='Main', diff='commit')

        self.assertEqual('diff', dom.by_id('side').attrs['data-show'])
        self.assertNotIn('hidden', dom.by_id('diff-slot').attrs)
        self.assertIn('hidden', dom.by_id('view-section').attrs)

        dom = self.page(screen='Main', diff='commit', inspect='r1')

        self.assertEqual('object', dom.by_id('side').attrs['data-show'])
        self.assertIn('hidden', dom.by_id('diff-slot').attrs)

    def test_a_click_on_a_change_selects_its_object(self):
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1')], Number=1))
        self.repo.commit()
        self.repo.export('screen', 'Main', document('screen', 'Main', [rect('r1'), rect('r2', left=300)], Number=1))

        dom = self.page(screen='Main', diff='commit', change='r2')

        self.assertEqual(('object', 'r2'), (dom.by_id('side').attrs['data-show'], dom.by_id('inspect').attrs['data-name']))
        self.assertIn('inspect', dom.find(lambda n: n.tag == 'body').classes)
        self.assertIn('selected', dom.obj('r2').classes)


class LiveReloadTest(BrowserCase):
    def reloaded(self, items, template=None, **params):
        """The page of screen Main after a live reload that writes it with items (on that template); params: more URL
        hooks."""
        connected = threading.Event()
        i = next(i for i, r in enumerate(server.ROUTES) if r[1] == '/api/events')
        method, path, stream = server.ROUTES[i]

        def watched(req):
            connected.set()
            return stream(req)
        server.ROUTES[i] = (method, path, watched)
        self.addCleanup(server.ROUTES.__setitem__, i, (method, path, stream))

        done = threading.Event()

        def regenerate():
            # The stream takes its first snapshot just after the request arrives: write until the page is dumped,
            # so a write that lands before that snapshot is followed by one the stream reports.
            if connected.wait(30):
                n = 0
                while not done.is_set():
                    self.repo.generated('screen', 'Main', document('screen', 'Main', items, template=template,
                                                                   Number=1, BackColor='%d, 0, 0' % n))
                    n += 1
                    done.wait(1.0)
        threading.Thread(target=regenerate, daemon=True).start()
        self.addCleanup(done.set)

        dom = self.page(screen='Main', live='once', **params)    # closes the change stream after the first reload
        done.set()
        return dom

    def test_open_screen_redraws_when_its_document_changes(self):
        self.repo.generated('screen', 'Main', document('screen', 'Main', [rect('r1', left=10)], Number=1))

        dom = self.reloaded([rect('r1', left=500)])

        self.assertEqual(500, dom.obj('r1').body().num('x'))
        self.assertIn('reloaded', dom.by_id('status').text())

    def test_a_reload_that_removes_the_selected_object_unselects_it(self):
        self.repo.generated('screen', 'Main', document('screen', 'Main', [rect('r1'), rect('r2', left=300)], Number=1))

        dom = self.reloaded([rect('r2', left=300)], inspect='r1')

        self.assertEqual('view', dom.by_id('side').attrs['data-show'])
        self.assertNotIn('data-name', dom.by_id('inspect').attrs)

    def test_a_reload_that_removes_the_selected_object_leaves_the_templates_namesake(self):
        self.repo.export('template', 'Tpl', document('template', 'Tpl', [rect('r1', left=600)]))
        self.repo.generated('screen', 'Main', document('screen', 'Main', [rect('r1'), rect('r2', left=300)],
                                                       template='Tpl', Number=1))

        dom = self.reloaded([rect('r2', left=300)], template='Tpl', inspect='r1')

        self.assertEqual('view', dom.by_id('side').attrs['data-show'])
        self.assertNotIn('data-name', dom.by_id('inspect').attrs)
        self.assertNotIn('selected', dom.obj('r1').classes)


if __name__ == '__main__':
    unittest.main()
