"""An SCL network's words in TIA's colours (scl_colours, page.scl_table, the viewer): the kinds TIA's SCL editor colours
apart, as read from its pictures of zzBenSclColours (tests/fixtures/scl-colours, the block exported from the
benchmark project as .s7dcl and as SimaticML); the same colours from both formats; colouring that never changes a
character or a change mark; what stays in one colour.

The test over every SCL network runs on the fixtures, and also on the project repos TIA_CR_SCL_REPOS names (paths
apart by the system's separator, ';' on Windows), such as the benchmark repo, when that is set."""
import contextlib
from collections import Counter
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
from TiaChangeReports import scl_colours as sc
from TiaChangeReports.__main__ import main
from TiaChangeReports.s7dcl import Interface, Member, Network, scl_lines
from TiaChangeReports.viewer import view

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
COLOURS = os.path.join(FIXTURES, 'scl-colours')
NEWLINE = chr(10)
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

    def test_eno_is_an_operand_and_a_parameter_only_with_a_parenthesis_open(self):
        """TIA colours ENO := FALSE; as an operand; a name before := is a parameter only with a parenthesis open, also
        on the lines after the one that opened it."""
        self.assertEqual(self.line('ENO := FALSE;'), [('operand', 'ENO'), ('operator', ':='), ('constant', 'FALSE'),
                                                       ('semicolon', ';')])
        self.assertEqual(self.line('PT := T#5s,')[0], ('parameter', 'PT'))
        self.assertEqual(kinds(scl_colours.lines(['x := 1;'])[0])[0], (None, 'x'))

    def test_a_data_type_after_typeof_as_tia_colours_it(self):
        """TIA colours what a type test compares with as a constant: a system type and a PLC data type alike, told by
        where it stands, in quotes or not (the SimaticML reader writes the PLC data type bare)."""
        self.assertEqual(self.line('IF TypeOf(#ioVar) = Int THEN')[1:],
                         [('instruction', 'TypeOf'), ('operator', '('), ('operand', '#ioVar'), ('operator', ')'),
                          ('operator', '='), ('constant', 'Int'), ('keyword', 'THEN')])
        self.assertIn(('constant', '"zzBenSclColType"'), self.line('ELSIF TypeOf(#ioVar) = "zzBenSclColType" THEN'))
        for line in ('ELSIF TypeOf(#ioVar) = zzBenSclColType THEN', 'IF TypeOfDB(#tmpDb) <> IEC_TIMER THEN'):
            self.assertEqual(kinds(scl_colours.lines([line])[0])[-2][0], 'constant')
        self.assertEqual(kinds(scl_colours.lines(['#a := #b = "Tag";'])[0])[-2], ('operand', '"Tag"'))

    def test_a_call_after_a_dot_as_tia_colours_it(self):
        """TIA colours the instance before the dot as an operand and the called name in a called block's colour."""
        self.assertEqual(self.line('#statTimer.TON(IN := #inEnable, PT := T#2s);')[:5],
                         [('operand', '#statTimer'), ('operator', '.'), ('block call', 'TON'), ('operator', '('),
                          ('parameter', 'IN')])
        self.assertEqual(kinds(scl_colours.lines(['#x := "Db".motor.speed;'])[0])[2:], [
            ('operand', '"Db"'), ('operator', '.'), ('operand', 'motor'), ('operator', '.'), ('operand', 'speed'),
            ('semicolon', ';')])

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


# The lines of zzBenSclColours the SimaticML reader writes otherwise than the .s7dcl holds them: ENO := FALSE; without
# its ENO, a name with letters outside ASCII in quotes (#"statÄnderung"), a PLC data type after TypeOf without its
# quotes. Their colours hold on the .s7dcl side (TheKindsAsReadFromTia); the colours follow the text either way.
READ_OTHERWISE = {89: 'ENO := FALSE;', 91: '#statÄnderung := 1;', 92: 'ELSIF TypeOf(#ioVar) = "zzBenSclColType" THEN',
                  93: '#statÄnderung := 2;', 96: '#statÜbung := #statÄnderung + 1;'}


def both_formats():
    """((lines, tokens) of the .s7dcl, (lines, tokens) of the SimaticML) of zzBenSclColours' network."""
    out = []
    for ext in ('.s7dcl', '.xml'):
        b = colour_block(ext)
        lines = scl_lines(b.networks[0].body)
        out.append((lines, scl_colours.lines(lines, b.interface)))
    return out


class BothFormatsAlike(unittest.TestCase):
    def test_the_same_lines_get_the_same_colours_from_s7dcl_and_simaticml(self):
        (ls, ks), (lx, kx) = both_formats()
        self.assertEqual((len(ls), len(lx)), (104, 104))
        self.assertEqual({k + 1: ls[k].strip() for k in range(104) if ls[k] != lx[k]}, READ_OTHERWISE)
        for k in range(104):
            if ls[k] == lx[k]:
                with self.subTest(line=k + 1):
                    self.assertEqual(ks[k], kx[k])

    def test_the_same_change_names_a_line_coloured_otherwise_beside_a_line_read_otherwise(self):
        """The bed's second check, line by line: a line of the same text coloured otherwise is SCL colours, also
        where another line of the network differs in its text between the formats."""
        n = (1, 1, '')
        line = ('o', 'line', n, '+', '#a := 1;')
        fs = Counter({line + ((('operand', '#a'),),): 1, ('o', 'line', n, '+', 'ENO := FALSE;', ()): 1})
        fx = Counter({line + ((('label', '#a'),),): 1, ('o', 'line', n, '+', ' := FALSE;', ()): 1})
        self.assertEqual(twoformats._net_part(n, None, fs, fx), {'unknown: SCL colours', 'unknown: lines'})
        fx = Counter({line + ((('operand', '#a'),),): 1, ('o', 'line', n, '+', ' := FALSE;', ()): 1})
        self.assertEqual(twoformats._net_part(n, None, fs, fx), {'unknown: lines'})

    def test_the_same_change_counts_a_repeated_line_coloured_otherwise(self):
        """The same changed line three times in each report, coloured A, A, B in one and A, B, B in the other."""
        n = (1, 1, '')
        a, b = (('operand', '#a'),), (('label', '#a'),)

        def facts(*toks):
            return Counter([('o', 'line', n, '+', '#a := 1;', t) for t in toks])
        self.assertEqual(twoformats._net_part(n, None, facts(a, a, b), facts(a, b, b)), {'unknown: SCL colours'})
        self.assertEqual(twoformats._net_part(n, None, facts(a, a), facts(a)), {'unknown: lines'})
        self.assertEqual(twoformats._net_part(n, None, facts(a, a), facts(b)),
                         {'unknown: lines', 'unknown: SCL colours'})

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


class TheRulesAsAGrid(unittest.TestCase):
    """Each rule that goes by position (scl_colours' doc, pass 2), with each kind of gap in the place it reads across:
    nothing, a space, a comment, two comments and a line end, which SCL reads as a space, keep the rule (HOLD); a
    string, a quoted name or a ";", tokens of the network, break it (BREAK). What a comment, string or quoted name
    holds (a call of its own) is never read. Each construct also twice on one line, both alike."""
    HOLD = {'nothing': '', 'space': ' ', 'comment': ' (* #b( *) ', 'two comments': ' (* #b( *) (/* x( */) ',
            'line end': NEWLINE}
    BREAK = {'string': " '#b(' ", 'quoted name': ' "#b(" ', 'semicolon': ' ; '}
    # rule: (line with {g} in the gap the rule reads across, the word it colours, its kind when the rule holds,
    # its kind when a string, quoted name or ";" stands in the gap, the line can hold the construct twice)
    RULES = {
        'a call of an instruction': ('#x := MAX{g}(1, 2);', 'MAX', 'instruction', None, True),
        'a call of an instance': ('#i{g}(IN := 1);', '#i', 'block call', 'operand', True),
        'a call after a dot': ('#t.TON{g}(IN := 1);', 'TON', 'block call', 'operand', True),
        'a member': ('#s.{g}a := 1;', 'a', 'operand', None, True),
        'a parameter name': ('#f(IN{g}:= 1);', 'IN', 'parameter', None, True),
        'a data type after a type test, before =': ('IF TypeOf(#v){g}= Int THEN #c := 1; END_IF;', 'Int', 'constant',
                                                    None, True),
        'a data type after a type test, after =': ('IF TypeOf(#v) ={g}Int THEN #c := 1; END_IF;', 'Int', 'constant',
                                                   None, True),
        'a jump label where it stands': ('lbl{g}: #a := 1;', 'lbl', 'label', None, False),
        'a jump label after GOTO': ('GOTO{g} lbl;', 'lbl', 'label', None, True),
        'a local constant': ('#a := #LAST{g}.x;', '#LAST', 'operand', 'local constant', True),
        "a region's name": ('{g}REGION Calls', 'Calls', 'constant', None, False),
    }

    def kinds_of(self, text, word):
        """[the kinds of word], all the tokens: text's lines as one network."""
        itf = Interface()
        itf.root.children['LAST'] = Member('LAST', 'Int', value='9', section='CONSTANT')
        texts = text.split(NEWLINE)
        got = scl_colours.lines(texts, itf)
        for line, toks in zip(texts, got):
            self.assertEqual(''.join(t for _, t in toks), line)
        toks = [x for line in got for x in line]
        return [k for k, t in toks if t == word], toks

    def test_each_rule_across_each_gap(self):
        for rule, (line, word, holds, broken, twice) in self.RULES.items():
            for gap, fill in list(self.HOLD.items()) + list(self.BREAK.items()):
                text = line.format(g=fill)
                expected = holds if gap in self.HOLD else broken
                with self.subTest(rule=rule, gap=gap):
                    if rule == "a region's name" and gap in self.HOLD:
                        self.assertEqual(self.kinds_of(text, 'Calls')[1][-1], ('constant', 'Calls'))
                        continue
                    got, toks = self.kinds_of(text, word)
                    self.assertEqual(got, [expected])
                    if 'comment' in gap:
                        self.assertIn(('comment', '(* #b( *)'), toks)
                    elif gap == 'string':
                        self.assertIn(('constant', "'#b('"), toks)
                if twice and gap in self.HOLD:
                    with self.subTest(rule=rule, gap=gap, twice=True):
                        self.assertEqual(self.kinds_of(text + ' ' + text, word)[0], [expected, expected])

    def test_a_comparison_after_a_type_test_is_the_only_one_read_as_a_data_type(self):
        """The audit's lines: a second comparison on a line with a type test is read as it is, not as a data type."""
        for line, word, kind in (('IF TypeOf(#v) = Int AND #a = "Db".x THEN', '"Db"', 'operand'),
                                 ('IF TypeOf(#v) = Int OR #k = LREAL_TO_INT(#r) THEN', 'LREAL_TO_INT', 'instruction'),
                                 ('IF TypeOf(#v) = Int AND #f = "Fc"() THEN', '"Fc"', 'block call'),
                                 ('IF TypeOf(#v) = Int AND #f = NOT #g THEN', 'NOT', 'operator'),
                                 ('IF TypeOf(#v) = Int AND #b = cnt THEN', 'cnt', None)):
            with self.subTest(line):
                self.assertEqual(self.kinds_of(line, word)[0], [kind])
                self.assertEqual(self.kinds_of(line, 'Int')[0], ['constant'])

    def test_a_comment_after_a_name_is_no_call(self):
        self.assertEqual(self.kinds_of('#x := #s.a (* note *);', 'a')[0], ['operand'])
        self.assertEqual(self.kinds_of('#x := #a (* note *);', '#a')[0], ['operand'])
        self.assertEqual(self.kinds_of('#x := MAX (/* note */);', 'MAX')[0], [None])


def locations():
    """Where an address or an ANY pointer points, from the tokenizer's lists: each area of the list ADDRESS_AREAS as a
    bit (with and without the first size of the list ADDRESS_SIZES, X) and in each other size of that list; a DB's
    data as a bit and in each other size."""
    bit, wide = sc.ADDRESS_SIZES[0], sc.ADDRESS_SIZES[1:]
    out = []
    for a in sc.ADDRESS_AREAS:
        out += ['%s1.0' % a, '%s%s1.0' % (a, bit)] + ['%s%s2' % (a, s) for s in wide]
    return out + ['DB1.DB%s0.0' % bit] + ['DB10.DB%s2' % s for s in wide]


def addresses():
    """Every absolute address form of the tokenizer's lists: each of locations() with %, those of an area of the list
    PERIPHERAL_AREAS also with :P, each area of the list NUMBERED_AREAS with a number, a slice of each size of the list
    ADDRESS_SIZES."""
    out = ['%' + loc for loc in locations()]
    out += ['%' + loc + ':P' for loc in locations() if loc[0] in sc.PERIPHERAL_AREAS]
    out += ['%%%s3' % a for a in sc.NUMBERED_AREAS] + ['%%%s3' % s for s in sc.ADDRESS_SIZES]
    return out


def pointers():
    """Every ANY pointer form: P# and each of locations(), alone and with the type word BYTE and a count; and with each
    data type of the list DATA_TYPES, in capitals and in small letters."""
    out = []
    for loc in locations():
        out += ['P#' + loc, 'P#%s BYTE 1' % loc]
    return out + ['P#DB1.DBX0.0 %s 10' % t for t in sc.DATA_TYPES] + ['P#M10.0 %s 1' % t.lower() for t in sc.DATA_TYPES]


class TheLiteralsAsATable(unittest.TestCase):
    """The literal forms of the S7DCL guide, section 5 "Literals and constants" (docs/agent/s7dcl-format.md: T#,
    reals, integers, Int#, 16#, W#16#, C#, TRUE and FALSE), in the base, sign and exponent forms FORMS writes, and
    the forms SCL has and the guide lacks: the other bases (2#, 8#), exponents, the typed numbers of the other data
    types, dates, times of day, dates and times (DT, LDT, DTL), LTIME, S5TIME, strings of both kinds with their $
    escapes and typed (STRINGS), and the ANY pointers (pointers()). Each one token in the constants' colour, alone and
    before +1 and -1; each address of addresses() one operand."""
    FORMS = {
        'untyped number': '42 3.0 3.14 1.5E-3 1.0E+10 1.0e10 1e10 2.5E3 1_000 16#100 16#00FF 16#ff 2#1010_0101 8#17',
        'Bool': 'TRUE FALSE BOOL#TRUE BOOL#1',
        'typed integer': 'Int#256 DINT#-7 DINT#+7 W#16#100 WORD#16#0F0F WORD#16#FE B#16#FF DW#16#FFFF_FFFF '
                         'DWORD#16#FFFF_FFFF BYTE#2#1010 UINT#8#17 LINT#-9223372036854775808 CHAR#16#41',
        'typed real': 'REAL#1.5E-3 LREAL#1.0E+10 REAL#-1.5E+3 LREAL#-1.0e-10 REAL#1.5e+3 REAL#2.0 LREAL#1e5 REAL#3',
        'time': 'T#500MS t#5s T#10s T#1s_200ms T#-1d2h3m4s5ms T#+5s T#1.5s T#-1.5s LT#1ns LTIME#5us '
                'LTIME#1d2h3m4s5ms6us7ns TIME#1h S5T#10s S5TIME#2h_46m_30s C#100',
        'date and time of day': 'D#2026-11-20 DATE#2026-11-20 TOD#12:30 TOD#12:30:00 TOD#12:30:00.500 '
                                'TIME_OF_DAY#12:30:00 LTOD#12:30:00.123456789 LTIME_OF_DAY#12:30:00 '
                                'DT#2026-11-20-12:30:00 DT#2026-11-20-12:30:00.123456789 '
                                'DATE_AND_TIME#2026-11-20-12:30:00.000 LDT#2026-11-20-12:30:00.123 '
                                'LDATE_AND_TIME#2026-11-20-12:30:00 DTL#2026-11-20-12:30:00.250',
    }
    STRINGS = ["'A'", "''", "'a $'quote$' inside'", "'$N'", "'$$'", "'$R$L'", "'a string with // and (* inside'",
               "WSTRING#'wide'", "WSTRING#'$''", "STRING#'x'", "CHAR#'A'", "WCHAR#'A'", "WCHAR#'$0041'"]

    @classmethod
    def all(cls):
        return [lit for text in cls.FORMS.values() for lit in text.split()] + cls.STRINGS + pointers()

    def test_each_form_is_one_constant(self):
        for lit in self.all():
            for after in ('', '+1', '-1'):
                with self.subTest(literal=lit, after=after):
                    toks = kinds(scl_colours.lines(['#x := %s%s;' % (lit, after)])[0])
                    rest = [('operator', after[0]), ('constant', '1')] if after else []
                    self.assertEqual(toks, [('operand', '#x'), ('operator', ':='), ('constant', lit)] + rest
                                     + [('semicolon', ';')])

    def test_each_address_is_one_operand(self):
        for address in addresses():
            with self.subTest(address=address):
                self.assertEqual(kinds(scl_colours.lines(['#x := %s;' % address])[0])[2], ('operand', address))

    def test_the_older_peripheral_form_is_outside_the_lists(self):
        """%PIW256, the peripheral form of the S7-300 and S7-400, is in no list (scl_colours' comment over the address
        lists): no address, so a "%" and a name, both black."""
        self.assertEqual(kinds(scl_colours.lines(['#x := %PIW256;'])[0])[2:4], [(None, '%'), (None, 'PIW256')])

    def test_without_the_percent_sign_an_address_is_a_name(self):
        """SCL in TIA V20 writes an absolute address with %; M10.0 is a name and a member."""
        self.assertEqual(kinds(scl_colours.lines(['#x := M10.0;'])[0])[2:4], [(None, 'M10'), ('operator', '.')])


class WhereATokenEnds(unittest.TestCase):
    """Every pair from whole lists: each token of TheLiteralsAsATable.all(), addresses(), the tokenizer's own words
    (scl_colours.STATEMENT_KEYWORDS, LOGIC_KEYWORDS, WORD_OPERATORS, BOOLS, REGION_WORDS, TYPE_TESTS, DATA_TYPES), a
    name of each prefix and a comment of each kind, followed directly by each operator of scl_colours.OPERATORS, the
    ";" and each comment kind, and each bracket, "," or comment followed by it: the cut gives exactly the two tokens."""
    NAMES = ['#a', '#Größe', '#"a b"', '"Q"', '"My.Db"', 'a', 'Übung']
    COMMENTS = ['(* c *)', '(/* c */)']

    @classmethod
    def tokens(cls):
        words = (sc.STATEMENT_KEYWORDS | sc.LOGIC_KEYWORDS | sc.WORD_OPERATORS | sc.BOOLS | sc.REGION_WORDS
                 | sc.TYPE_TESTS | set(sc.DATA_TYPES))
        return TheLiteralsAsATable.all() + addresses() + sorted(words) + cls.NAMES + cls.COMMENTS

    def cut(self, text):
        return [t for _, t in scl_colours._cut(text, {'end': None})]

    def test_each_token_followed_by_each_operator_and_comment(self):
        for tok in self.tokens():
            for nxt in list(sc.OPERATORS) + [';'] + self.COMMENTS:
                with self.subTest(token=tok, then=nxt):
                    self.assertEqual(self.cut(tok + nxt), [tok, nxt])

    def test_a_bracket_or_comment_followed_by_each_token(self):
        for tok in self.tokens():
            for before in ['(', ')', '[', ']', ','] + self.COMMENTS:
                with self.subTest(before=before, token=tok):
                    self.assertEqual(self.cut(before + tok), [before, tok])

    def test_a_line_comment_takes_the_rest_of_its_line(self):
        for tok in self.tokens():
            if tok in self.COMMENTS or tok.upper() == 'REGION':
                continue                         # REGION // c is a region's name (WhichLineRuleGoesFirst)
            with self.subTest(token=tok):
                self.assertEqual(self.cut(tok + '// ' + tok + ' (* ;'), [tok, '// ' + tok + ' (* ;'])


class WhichLineRuleGoesFirst(unittest.TestCase):
    """The rules about a whole line (scl_colours' doc, pass 1, its table): the pairs of them listed in test_each_pair
    on one line, and over two lines each of LINE_RULES on the line after a comment left open, after a string left open
    and after a line comment."""
    LINE_RULES = ['REGION x', 'REGION // c', '// c', '(* c *) #a := 1;', '(/* c */) #a := 1;', "#s := 'a // b';",
                  '{ p := "1" } #a := 1;', '{ p := "}" } REGION x', '#a := 1;']

    def test_each_pair(self):
        for line, expected in (
                ('REGION // only a note', [('region', 'REGION'), ('constant', '// only a note')]),
                ('REGION (* a note *)', [('region', 'REGION'), ('constant', '(* a note *)')]),
                ("REGION 'x' // y", [('region', 'REGION'), ('constant', "'x' // y")]),
                ('REGION (* open', [('region', 'REGION'), ('constant', '(* open')]),
                ('// REGION x', [('comment', '// REGION x')]),
                ('(* REGION *) #a := 1;', [('comment', '(* REGION *)'), ('operand', '#a'), ('operator', ':='),
                                            ('constant', '1'), ('semicolon', ';')]),
                ('(* c *) REGION Calls', [('comment', '(* c *)'), ('region', 'REGION'), ('constant', 'Calls')]),
                ('{ S7_X := "1" } // c', [(None, '{ S7_X := "1" }'), ('comment', '// c')]),
                ('{ S7_X := "1" } REGION x', [(None, '{ S7_X := "1" }'), ('region', 'REGION'), ('constant', 'x')]),
                ('{ S7_X := "a}b" } #a := 1;', [(None, '{ S7_X := "a}b" }'), ('operand', '#a'), ('operator', ':='),
                                                ('constant', '1'), ('semicolon', ';')]),
                ("#s := 'a // b';", [('operand', '#s'), ('operator', ':='), ('constant', "'a // b'"),
                                      ('semicolon', ';')]),
                ("#s := 'a (* b';", [('operand', '#s'), ('operator', ':='), ('constant', "'a (* b'"),
                                      ('semicolon', ';')]),
                ('#a := 1; // (* not open', [('operand', '#a'), ('operator', ':='), ('constant', '1'),
                                             ('semicolon', ';'), ('comment', '// (* not open')]),
                ('(* // *) #a := 1;', [('comment', '(* // *)'), ('operand', '#a'), ('operator', ':='),
                                       ('constant', '1'), ('semicolon', ';')]),
                ('"REGION" := 1;', [('operand', '"REGION"'), ('operator', ':='), ('constant', '1'),
                                    ('semicolon', ';')])):
            with self.subTest(line):
                self.assertEqual(kinds(scl_colours.lines([line])[0]), expected)

    def test_each_line_rule_after_a_comment_left_open(self):
        """The comment open from the line before goes first: inside it nothing is read, after its close the line is
        read as it is alone."""
        for rule in self.LINE_RULES:
            for opened in ('#a := 1; (* open', '(/* open'):
                close = '*)' if '(*' in opened else '*/)'
                with self.subTest(rule=rule, opened=opened):
                    if close not in rule:               # one holding the close closes the comment there
                        self.assertEqual(scl_colours.lines([opened, rule])[1], [('comment', rule)])
                    after = scl_colours.lines([opened, 'x ' + close + ' ' + rule])[1]
                    self.assertEqual(after[0], ('comment', 'x ' + close))
                    self.assertEqual(kinds(after[1:]), kinds(scl_colours.lines([rule])[0]))

    def test_each_line_rule_after_a_string_or_a_line_comment(self):
        """Neither crosses its line: the next line is read as it is alone."""
        for rule in self.LINE_RULES:
            for opened in ("#s := 'open", '#a := 1; // (* x'):
                with self.subTest(rule=rule, opened=opened):
                    self.assertEqual(scl_colours.lines([opened, rule])[1], scl_colours.lines([rule])[0])


class HalfWrittenNetworks(unittest.TestCase):
    """Something left open (a parenthesis, a comment, a string, a REGION, a type test): what stands after it is
    coloured as if the open one were not there, as far as the grammar allows. A call's or type test's parentheses end
    at a ";" and at each word of the tokenizer's list scl_colours.STOPPERS; the words of its lists LOGIC_KEYWORDS and
    WORD_OPERATORS stand inside parentheses and end nothing."""
    AFTER = ['x := 2;', 'IN2 := 3;', '#a := MAX(1, 2);', 'lbl: #b := 1;', '#c := #d = Int;']

    def test_each_thing_left_open(self):
        for opened in (['#f(IN := 1,', 'ENO := FALSE;'], ['#f(IN := 1;'], ['IF TypeOf(#v;'],
                       ['#a := 1; (* open', 'still open *)'], ["#s := 'open"], ['REGION open'],
                       ['#f(IN := (* open', '*) 1;']):
            for line in self.AFTER:
                with self.subTest(opened=opened, line=line):
                    self.assertEqual(scl_colours.lines(opened + [line])[-1], scl_colours.lines([line])[0])

    def test_each_stopper_ends_a_call_left_open(self):
        for stopper in sorted(sc.STOPPERS) + [';']:
            for line in self.AFTER:
                if stopper == 'GOTO' and line[0] != '#':
                    continue                     # the word after GOTO is its label
                with self.subTest(stopper=stopper, line=line):
                    for opened in (['#f(IN := 1 ' + stopper], ['IF TypeOf(#v ' + stopper]):
                        got = scl_colours.lines(opened + [line])[-1]
                        self.assertEqual(got, scl_colours.lines([line])[0])

    def test_a_logic_keyword_or_word_operator_ends_nothing(self):
        for word in sorted(sc.LOGIC_KEYWORDS | sc.WORD_OPERATORS):
            with self.subTest(word=word):
                got = scl_colours.lines(['#f(IN := #a ' + word, '#b, IN2 := 1);'])
                self.assertIn(('parameter', 'IN2'), got[1])
                got = scl_colours.lines(['IF TypeOf(#v) = Int ' + word, '#b = 1 THEN'])
                self.assertIn(('constant', 'Int'), got[0])

    def test_the_networks_end_ends_every_rule(self):
        """The construct cut off where the network ends: what the rule wants after it is not there."""
        for lines_, word, kind in ((['#i'], '#i', 'operand'), (['#x := MAX'], 'MAX', None),
                                   (['#t.TON'], 'TON', 'operand'), (['#f(IN'], 'IN', None),
                                   (['IF TypeOf(#v) ='], 'TypeOf', 'instruction'), (['lbl'], 'lbl', None),
                                   (['GOTO'], 'GOTO', 'keyword'), (['REGION'], 'REGION', 'region')):
            with self.subTest(lines_):
                got = [k for line in scl_colours.lines(lines_) for k, t in line if t == word]
                self.assertEqual(got, [kind])

    def test_inside_the_open_call_a_name_before_assign_is_a_parameter(self):
        got = scl_colours.lines(['#f(IN := 1,', 'ENO := FALSE;', 'x := 2;'])
        self.assertEqual(kinds(got[1])[0], ('parameter', 'ENO'))
        self.assertEqual(kinds(got[2])[0], (None, 'x'))


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
    """STL, a LAD or FBD network shown as text, and declarations: the report's output byte for byte the one main
    wrote (one-colour.json)."""

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
        rows = [re.findall(r'<tr><td class="ln">(\d+)</td><td>(.*?)</td></tr>', view.network_html(b.networks[0], b))
                for b in (sd, xml)]
        self.assertEqual(len(rows[0]), 104)
        self.assertEqual([r for r in rows[0] if int(r[0]) not in READ_OTHERWISE],
                         [r for r in rows[1] if int(r[0]) not in READ_OTHERWISE])


if __name__ == '__main__':
    unittest.main()
