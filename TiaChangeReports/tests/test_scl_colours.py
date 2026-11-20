"""An SCL network's words in TIA's colours (scl_colours, page.scl_table, the viewer): the kinds TIA's SCL editor colours
apart, as read from its pictures of zzBenSclColours (tests/fixtures/scl-colours, the block exported from the
benchmark project as .s7dcl and as SimaticML); the same colours from both formats; colouring that never changes a
character or a change mark; what stays in one colour.

The test over every SCL network runs on the fixtures, and also on the project repos TIA_CR_SCL_REPOS names (paths
apart by the system's separator, ';' on Windows), such as the benchmark repo, when that is set."""
import contextlib
import difflib
import io
import json
import os
import re
import tempfile
import unittest
from html import escape
from unittest import mock

from TiaChangeReports import page, scl_colours, twoformats
from TiaChangeReports.__main__ import main
from TiaChangeReports.s7dcl import Interface, Member, Network, scl_lines
from TiaChangeReports.viewer import view

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
COLOURS = os.path.join(FIXTURES, 'scl-colours')
COLOUR_SPAN = re.compile(r'<span class="s[a-z]">([^<]*)</span>')


def uncoloured(html):
    """The HTML with the colour spans taken out, their text kept."""
    return COLOUR_SPAN.sub(r'\1', html)


def colour_block(ext):
    return view.block_of(os.path.join(COLOURS, 'zzBenSclColours' + ext))[0]


def report(argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return main(argv)


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def kinds(toks):
    """The words of a line with their kind, spaces left out."""
    return [(k, t) for k, t in toks if t.strip()]


def _inline_before(a, b):
    """page._inline as it was before the SCL colours: the changed words the report marks."""
    ta = page.WORD.findall(a)
    tb = page.WORD.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    oa, ob = [], []

    def mark(toks):
        return ''.join(escape(t) if t.isspace() else '<span>%s</span>' % escape(t) for t in toks)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            oa.append(escape(''.join(ta[i1:i2])))
            ob.append(escape(''.join(tb[j1:j2])))
        else:
            oa.append(mark(ta[i1:i2]))
            ob.append(mark(tb[j1:j2]))
    return ''.join(oa), ''.join(ob)


def changed(lines):
    """The lines with changes of each sort: a word changed in every third, every seventh gone, a line added after
    every fifth."""
    out = []
    for k, line in enumerate(lines):
        if k % 7 == 6:
            continue
        if k % 3 == 1:
            line = re.sub(r'\d+|#\w+|\b[A-Z_]+\b', lambda m: m.group() + '1', line, count=1)
        out.append(line)
        if k % 5 == 4:
            out.append('#added := %s; // added' % k)
    return out


def scl_networks(root):
    """(file, block, network) of every SCL network of the exports under root that the readers read."""
    for folder, _, files in os.walk(root):
        if '.git' in folder.split(os.sep):
            continue
        for name in sorted(files):
            if not name.endswith(('.s7dcl', '.xml')):
                continue
            path = os.path.join(folder, name)
            try:
                blk = view.block_of(path)[0]
            except Exception:                   # noqa: BLE001 - no block export, or one the readers do not read
                continue
            for net in blk.networks:
                if net.lang == 'SCL':
                    yield path, blk, net


def roots():
    extra = [p for p in os.environ.get('TIA_CR_SCL_REPOS', '').split(os.pathsep) if p]
    return [FIXTURES] + extra


class TheKindsAsReadFromTia(unittest.TestCase):
    """The lines of zzBenSclColours with the kind of each word, as TIA's editor coloured them on its pictures."""

    @classmethod
    def setUpClass(cls):
        blk = colour_block('.s7dcl')
        cls.lines = scl_lines(blk.networks[0].body)
        cls.toks = scl_colours.lines(cls.lines, blk.interface)

    def line(self, text):
        k = [x.strip() for x in self.lines].index(text)
        return kinds(self.toks[k])

    def test_every_constant_as_written(self):
        for text, const in (('#statFlag := TRUE;', 'TRUE'), ('#statResult := 42;', '42'),
                            ('#statWord := 16#00FF;', '16#00FF'), ('#statByte := 2#1010_0101;', '2#1010_0101'),
                            ('#statReal := 3.14;', '3.14'), ('#statReal := 1.5E-3;', '1.5E-3'),
                            ('#statTime := T#1s_200ms;', 'T#1s_200ms'), ('#statDate := D#2026-11-20;', 'D#2026-11-20'),
                            ('#statTod := TOD#12:30:00;', 'TOD#12:30:00'), ("#statChar := 'A';", "'A'"),
                            ("#statWide := WSTRING#'wide';", "WSTRING#'wide'"), ('#tmpSum := DINT#-7;', 'DINT#-7'),
                            ('#statWord := WORD#16#0F0F;', 'WORD#16#0F0F')):
            with self.subTest(text):
                self.assertEqual(self.line(text), [('operand', text.split()[0]), ('operator', ':='),
                                                   ('constant', const), ('semicolon', ';')])
        self.assertEqual(self.line('#statResult := -8#17;')[2:4], [('operator', '-'), ('constant', '8#17')])

    def test_a_string_holds_what_would_open_a_comment(self):
        self.assertEqual(self.line("#outText := 'a string with // and (* inside';")[2],
                         ('constant', "'a string with // and (* inside'"))

    def test_regions_with_their_names(self):
        self.assertEqual(self.line('REGION Constants of each form'),
                         [('region', 'REGION'), ('constant', 'Constants of each form')])
        self.assertEqual(self.line('END_REGION'), [('region', 'END_REGION')])

    def test_comments_on_their_own_line_after_code_and_over_two_lines(self):
        self.assertEqual(self.line('// A line comment on a line of its own'),
                         [('comment', '// A line comment on a line of its own')])
        self.assertEqual(self.line('(* A block comment'), [('comment', '(* A block comment')])
        self.assertEqual(self.line('over two lines *)'), [('comment', '       over two lines *)')])
        self.assertEqual(self.line('#outActive := #inEnable AND "zzMcTag1"; // a comment after code')[-1],
                         ('comment', '// a comment after code'))

    def test_operands_local_global_members_index_and_slice(self):
        self.assertEqual(self.line('"zzBenSclColDb".motor.speed := #inMode;'),
                         [('operand', '"zzBenSclColDb"'), ('operator', '.'), ('operand', 'motor'), ('operator', '.'),
                          ('operand', 'speed'), ('operator', ':='), ('operand', '#inMode'), ('semicolon', ';')])
        self.assertEqual(self.line('#tmpBit := #statWord.%X3;')[2:5],
                         [('operand', '#statWord'), ('operator', '.'), ('operand', '%X3')])
        self.assertIn(('operand', '#tmpI'), self.line('"zzBenSclColDb".values[#tmpI] := #statValues[#LAST];'))

    def test_a_local_constant_from_the_interface(self):
        self.assertIn(('local constant', '#LAST'), self.line('"zzBenSclColDb".values[#tmpI] := #statValues[#LAST];'))
        self.assertIn(('local constant', '#LAST'), self.line('FOR #tmpI := 0 TO #LAST BY 1 DO'))

    def test_keywords_and_the_words_that_are_operators(self):
        self.assertEqual(self.line('WHILE #tmpI < #LAST AND NOT #statFlag DO'),
                         [('keyword', 'WHILE'), ('operand', '#tmpI'), ('operator', '<'), ('local constant', '#LAST'),
                          ('keyword', 'AND'), ('operator', 'NOT'), ('operand', '#statFlag'), ('keyword', 'DO')])
        self.assertIn(('operator', 'MOD'), self.line('#statResult := #inMode MOD 2;'))
        self.assertEqual(self.line('1..3, 5:'), [('constant', '1'), ('operator', '..'), ('constant', '3'),
                                                 ('operator', ','), ('constant', '5'), ('operator', ':')])

    def test_calls_of_an_instance_an_instruction_an_fc_and_an_fb_through_its_db(self):
        self.assertEqual(self.line('#instDelay(IN := #inEnable,')[:3],
                         [('block call', '#instDelay'), ('operator', '('), ('parameter', 'IN')])
        self.assertEqual(self.line('ET => #statTime);')[:2], [('parameter', 'ET'), ('operator', '=>')])
        self.assertEqual([x for x in self.line('#statReal := SQRT(ABS(#inSetpoint)) ** 2.0;') if x[0] == 'instruction'],
                         [('instruction', 'SQRT'), ('instruction', 'ABS')])
        self.assertEqual(self.line('#statResult := "zzBenSclColFc"(inA := #statResult, inB := 5);')[2:5],
                         [('block call', '"zzBenSclColFc"'), ('operator', '('), ('parameter', 'inA')])
        self.assertEqual(self.line('"zzBenSclColFbDb"(inStart := #inEnable);')[0], ('block call', '"zzBenSclColFbDb"'))
        self.assertEqual(self.line('#outActive := #instColFb.outDone OR "zzBenSclColFbDb".outDone;')[2:5],
                         [('operand', '#instColFb'), ('operator', '.'), ('operand', 'outDone')])

    def test_a_jump_label_where_it_stands_and_after_goto(self):
        self.assertEqual(self.line('GOTO lblEnd;'), [('keyword', 'GOTO'), ('label', 'lblEnd'), ('semicolon', ';')])
        self.assertEqual(self.line('lblEnd: #outActive := FALSE;')[:2], [('label', 'lblEnd'), ('operator', ':')])
        self.assertEqual(self.line('lblEnd: #outActive := FALSE;')[-2], ('constant', 'FALSE'))

    def test_a_region_line_with_a_comment_and_a_multilingual_comment(self):
        """TIA colours the whole rest of a REGION line, its // too, as the region's name, and (/* */) as a comment."""
        self.assertEqual(self.line("REGION Settled by TIA // a comment on the region's line"),
                         [('region', 'REGION'), ('constant', "Settled by TIA // a comment on the region's line")])
        self.assertEqual(self.line('(/*A multilingual comment in code*/)'),
                         [('comment', '(/*A multilingual comment in code*/)')])

    def test_eno_is_an_operand_and_a_parameter_only_inside_a_call(self):
        """TIA colours ENO := FALSE; as an operand; a name before := is a parameter inside a call's parentheses only,
        also on the call's next lines."""
        self.assertEqual(self.line('ENO := FALSE;'), [('operand', 'ENO'), ('operator', ':='), ('constant', 'FALSE'),
                                                       ('semicolon', ';')])
        self.assertEqual(self.line('PT := T#5s,')[0], ('parameter', 'PT'))
        self.assertEqual(kinds(scl_colours.lines(['x := 1;'])[0])[0], (None, 'x'))

    def test_what_the_maintainer_chose_where_tia_differs(self):
        """TIA colours a data type after TypeOf as a constant and the called TON of #statTimer.TON( as a block call;
        the maintainer chose to keep them black and an operand."""
        self.assertEqual(self.line('IF TypeOf(#ioVar) = Int THEN')[1:],
                         [('instruction', 'TypeOf'), ('operator', '('), ('operand', '#ioVar'), ('operator', ')'),
                          ('operator', '='), (None, 'Int'), ('keyword', 'THEN')])
        self.assertIn(('operand', '"zzBenSclColType"'), self.line('ELSIF TypeOf(#ioVar) = "zzBenSclColType" THEN'))
        self.assertEqual(self.line('#statTimer.TON(IN := #inEnable, PT := T#2s);')[:5],
                         [('operand', '#statTimer'), ('operator', '.'), ('operand', 'TON'), ('operator', '('),
                          ('parameter', 'IN')])

    def test_names_in_other_letters(self):
        self.assertEqual(self.line('#statÜbung := #statÄnderung + 1;')[:3],
                         [('operand', '#statÜbung'), ('operator', ':='), ('operand', '#statÄnderung')])

    def test_each_kind_has_the_colour_read_from_tia(self):
        self.assertEqual({k: v[1] for k, v in scl_colours.KINDS.items()}, {
            'keyword': '#0000ff', 'region': '#c91ffe', 'constant': '#005989', 'comment': '#187e2b',
            'operand': '#4c3f88', 'local constant': '#02284e', 'block call': '#670667', 'instruction': '#51120f',
            'parameter': '#350034', 'operator': '#414141', 'semicolon': '#000000', 'label': '#000000'})
        seen = {k for line in self.toks for k, _ in line}
        self.assertEqual(seen - {None}, set(scl_colours.KINDS))       # the block holds every kind


class BothFormatsAlike(unittest.TestCase):
    def test_the_same_lines_get_the_same_colours_from_s7dcl_and_simaticml(self):
        sd, xml = colour_block('.s7dcl'), colour_block('.xml')
        got = [[scl_colours.lines(scl_lines(n.body), b.interface) for n in b.networks] for b in (sd, xml)]
        self.assertEqual(len(got[0][0]), 104)
        self.assertEqual(got[0], got[1])

    def test_the_simaticml_reader_writes_eno_names_in_other_letters_and_a_data_type_as_the_sd_export(self):
        lines = scl_lines(colour_block('.xml').networks[0].body)
        for line in ('ENO := FALSE;', '#statÜbung := #statÄnderung + 1;', 'IF TypeOf(#ioVar) = Int THEN',
                     'ELSIF TypeOf(#ioVar) = "zzBenSclColType" THEN'):
            self.assertIn(line, [x.strip() for x in lines])

    def test_the_bed_names_a_network_coloured_otherwise(self):
        sd, xml = colour_block('.s7dcl'), colour_block('.xml')
        d = mock.Mock(before=sd, after=xml)
        self.assertEqual(twoformats.scl_colours_differ(d), [])
        del xml.interface.root.children['LAST']        # a reader that would not read the local constant
        self.assertEqual(twoformats.scl_colours_differ(d), [(1, 1, xml.networks[0].title)])


class TextAndMarksUnchanged(unittest.TestCase):
    """Colouring never changes a character: every SCL network of the fixtures (and of TIA_CR_SCL_REPOS), each line's
    text with the colour spans taken out the line as the report wrote it before, the change marks on the same
    characters."""

    def test_every_scl_network(self):
        count = 0
        for root in roots():
            for path, blk, net in scl_networks(root):
                count += 1
                bl = scl_lines(net.body)
                al = changed(bl)
                kb, ka = scl_colours.lines(bl, blk.interface), scl_colours.lines(al, blk.interface)
                with self.subTest(path=path, network=net.index):
                    for line, toks in zip(bl, kb):
                        self.assertEqual(''.join(t for _, t in toks), line)
                    for b, a in ((bl, bl), (bl, al)):
                        plain = page.scl_table(b, a)
                        coloured = page.scl_table(b, a, kb=kb, ka=kb if a is bl else ka)
                        self.assertEqual(uncoloured(coloured), plain)
                    for x, y in zip(bl, al):
                        self.assertEqual(page._inline(x, y), _inline_before(x, y))
        self.assertGreater(count, 2)

    def test_a_whole_report_reads_as_before_with_the_colours_taken_out(self):
        with tempfile.TemporaryDirectory() as d:
            v1, v2 = (os.path.join(FIXTURES, 'plant', v) for v in ('v1', 'v2'))
            assert report([v1, v2, '--all', '-o', os.path.join(d, 'c.html')]) == 0
            with mock.patch.object(scl_colours, 'of_network', return_value=None):
                assert report([v1, v2, '--all', '-o', os.path.join(d, 'p.html')]) == 0
            coloured, plain = (_read(os.path.join(d, n)) for n in ('c.html', 'p.html'))
        self.assertIn('<span class="sk">', coloured)
        self.assertEqual(uncoloured(coloured), plain)

    def test_a_changed_word_keeps_its_mark_and_its_colours_inside(self):
        b, a = '#x := #a + 1;', '#x := #b + 1;'
        hb, ha = page._inline(b, a, *(scl_colours.lines([t])[0] for t in (b, a)))
        self.assertEqual(ha, '<span class="so">#x</span> <span class="sx">:=</span> <span class="so">#</span>'
                             '<span><span class="so">b</span></span> <span class="sx">+</span> '
                             '<span class="sc">1</span>;')
        self.assertEqual(uncoloured(ha), _inline_before(b, a)[1])


class WhatDoesNotParse(unittest.TestCase):
    def test_its_text_stays_and_what_the_tokenizer_does_not_take_is_black(self):
        for line in ("#a := 'open string", '#a := @ ? ~ $ \\ `', '{ S7_MLC := "MLC_1" } #a := 1;', '#a := (#b',
                     'IF #a THEN (* open comment', '"no end', '#'):
            with self.subTest(line):
                toks = scl_colours.lines([line])[0]
                self.assertEqual(''.join(t for _, t in toks), line)
        self.assertEqual(kinds(scl_colours.lines(["#a := 'open string"])[0])[-1], ('constant', "'open string"))
        self.assertEqual([t for k, t in scl_colours.lines(['#a := @ ? ~;'])[0] if k is None and t.strip()],
                         ['@', '?', '~'])
        self.assertEqual(scl_colours.lines(['{ S7_MLC := "MLC_1" }'])[0], [(None, '{ S7_MLC := "MLC_1" }')])

    def test_a_comment_left_open_goes_on_over_the_next_lines(self):
        got = scl_colours.lines(['#a := 1; (* opens', 'still the comment', 'ends *) #b := 2;', '(/* a multilingual',
                                 'comment */) #c := 3;'])
        self.assertEqual(got[1], [('comment', 'still the comment')])
        self.assertEqual(kinds(got[2])[:2], [('comment', 'ends *)'), ('operand', '#b')])
        self.assertEqual(kinds(got[4])[:2], [('comment', 'comment */)'), ('operand', '#c')])


class LocalConstants(unittest.TestCase):
    def interface(self):
        itf = Interface()
        itf.root.children['LIMIT'] = Member('LIMIT', 'Int', value='5', section='CONSTANT')
        itf.root.children['limit2'] = Member('limit2', 'Int', section='STAT')
        return itf

    def test_told_from_the_interface_not_the_text(self):
        line = '#a := #LIMIT + #limit2 + #OTHER;'
        got = kinds(scl_colours.lines([line], self.interface())[0])
        self.assertEqual([t for k, t in got if k == 'local constant'], ['#LIMIT'])
        self.assertEqual([t for k, t in got if k == 'operand'], ['#a', '#limit2', '#OTHER'])

    def test_in_any_case_and_in_quotes(self):
        got = kinds(scl_colours.lines(['#a := #limit + #"LIMIT" + #LIMIT.x;'], self.interface())[0])
        self.assertEqual([t for k, t in got if k == 'local constant'], ['#limit', '#"LIMIT"'])

    def test_without_an_interface_every_name_is_an_operand(self):
        got = kinds(scl_colours.lines(['#a := #LIMIT;'])[0])
        self.assertEqual(got[2], ('operand', '#LIMIT'))


class NamesOfAnyLetters(unittest.TestCase):
    def test_a_name_is_one_word_whatever_letters_it_holds(self):
        line = '#Übung := #ärger + "Füllstand_Tank".Ölstand + #Motorstörung + MAX(IN1 := #Größe, IN2 := 1);'
        self.assertEqual(kinds(scl_colours.lines([line])[0]), [
            ('operand', '#Übung'), ('operator', ':='), ('operand', '#ärger'), ('operator', '+'),
            ('operand', '"Füllstand_Tank"'), ('operator', '.'), ('operand', 'Ölstand'), ('operator', '+'),
            ('operand', '#Motorstörung'), ('operator', '+'), ('instruction', 'MAX'), ('operator', '('),
            ('parameter', 'IN1'), ('operator', ':='), ('operand', '#Größe'), ('operator', ','), ('parameter', 'IN2'),
            ('operator', ':='), ('constant', '1'), ('operator', ')'), ('semicolon', ';')])

    def test_a_local_constant_and_a_call_in_other_letters(self):
        itf = Interface()
        itf.root.children['GRÖSSE'] = Member('GRÖSSE', 'Int', value='5', section='CONSTANT')
        got = kinds(scl_colours.lines(['#Zähler := #GRÖSSE; #Ölpumpe(Ein := TRUE);'], itf)[0])
        self.assertIn(('local constant', '#GRÖSSE'), got)
        self.assertIn(('block call', '#Ölpumpe'), got)
        self.assertIn(('parameter', 'Ein'), got)


class WhatStaysInOneColour(unittest.TestCase):
    """STL, a LAD network shown as text and declarations: the report's output as before, byte for byte."""

    def test_stl_and_lad_as_text_get_no_tokens_and_their_table_as_before(self):
        body = '      L     #a\n      T     #b\n'
        for lang in ('STL', 'LAD', 'FBD', ''):
            net = Network(1, lang, '', '', body)
            with self.subTest(lang):
                lines = scl_lines(body)
                self.assertIsNone(scl_colours.of_network(net, lines, None))
                self.assertIsNone(COLOUR_SPAN.search(page.scl_table(lines, ['L #a', 'T #c'])))
        self.assertIsNotNone(scl_colours.of_network(Network(1, 'SCL', '', '', body), scl_lines(body), None))

    def test_a_network_of_another_language_on_one_side(self):
        """An SCL network that became STL: the SCL side coloured, the STL side and the line naming its language not."""
        stl, scl = Network(1, 'STL', '', '', 'L #a\n'), Network(1, 'SCL', '', '', '#a := 1;\n')
        blk = mock.Mock(interface=None)
        pair = mock.Mock(before=stl, after=scl, lad=None, state='changed', moved=False, reordered=False,
                         not_shown=False)
        html = page.network_html(pair, blk, blk)
        before = [x for x in re.findall(r'<td class="b [^"]*">(.*?)</td>', html) if x != '&#8203;']
        self.assertEqual(before, ['(STL network)', 'L #a'])
        self.assertIn('<span class="so">#a</span>', html)

    def test_byte_for_byte_as_before(self):
        """one-colour.json: the report's STL, LAD and FBD networks shown as text, the viewer's interface and Source
        view of zzBenSclColours, as the code before the colours wrote them."""
        with open(os.path.join(COLOURS, 'one-colour.json'), encoding='utf-8') as f:
            before = json.load(f)
        blk = mock.Mock(interface=None)
        for c in before['cases']:
            pair = mock.Mock(before=Network(1, c['lang'], 'T', '', c['before']),
                             after=Network(1, c['lang'], 'T', '', c['after']), lad=None, state='changed', moved=False,
                             reordered=False, not_shown=False)
            with self.subTest(c['lang']):
                self.assertEqual(page.network_html(pair, blk, blk), c['html'])
        path = os.path.join(COLOURS, 'zzBenSclColours.s7dcl')
        b, src, root, rel = view.block_of(path)
        drawn = view.block_html(b, src, rel, root)
        self.assertEqual(drawn[:drawn.index('<div class="nwt">')], before['interface'])
        self.assertEqual(view.source_html(path), before['source'])

    def test_declarations_get_no_colours(self):
        blk, src, root, rel = view.block_of(os.path.join(COLOURS, 'zzBenSclColours.s7dcl'))
        drawn = view.block_html(blk, src, rel, root)
        itf = drawn[drawn.index('<b>Interface</b>'):drawn.index('<div class="nwt">')]
        self.assertIn('LAST', itf)
        self.assertIsNone(COLOUR_SPAN.search(itf))


class TheViewer(unittest.TestCase):
    def test_the_block_in_its_colours_the_source_as_it_is(self):
        for ext in ('.s7dcl', '.xml'):
            path = os.path.join(COLOURS, 'zzBenSclColours' + ext)
            blk, src, root, rel = view.block_of(path)
            drawn = view.block_html(blk, src, rel, root)
            with self.subTest(ext):
                self.assertIn('<span class="sl">#LAST</span>', drawn)
                self.assertIn('<span class="sr">REGION</span> <span class="sc">Constants of each form</span>', drawn)
                self.assertIsNone(COLOUR_SPAN.search(view.source_html(path)))
        sd, xml = (view.block_of(os.path.join(COLOURS, 'zzBenSclColours' + e))[0] for e in ('.s7dcl', '.xml'))
        self.assertEqual(view.network_html(sd.networks[0], sd), view.network_html(xml.networks[0], xml))


if __name__ == '__main__':
    unittest.main()
