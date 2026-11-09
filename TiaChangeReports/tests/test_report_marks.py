"""What a change report marks in a LAD network: each thing that changed has its mark, whatever else changed with it."""
import contextlib
import io
import itertools
import os
import re
import shutil
import tempfile
import unittest
from html import unescape
from types import SimpleNamespace

from TiaChangeReports.__main__ import main
from TiaChangeReports.compare import compare_blocks
from TiaChangeReports.diff import Graph, NetDiff
from TiaChangeReports.page import CSS, network_html, render
from TiaChangeReports.render_lad import Layout
from TiaChangeReports.s7dcl import parse_block
from TiaChangeReports.source import BlockSource
from TiaChangeReports.tests.test_change_reports import _put, src
from TiaChangeReports.tests.test_git_context import fixture_git

NET = '''FUNCTION_BLOCK "K"
    VAR
        a : Int;
        b : Int;
        x : Bool;
        y : Bool;
        q : Bool;
        s : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #x )
            { S7_Templates := "SrcType := Int" }
            EQ_Contact(
                in1 := #a,
                in2 := #b
            )
            Coil( #q )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''

CALL = '''FUNCTION_BLOCK "K"
    VAR
        inst : _.Drive;
        a : Bool;
        b : Bool;
        c : Int;
        d : Int;
        q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            #inst(
                start := wire#w1,
                speed := 5,
                cmd := #c,
                state => #c
            )
            Coil( #q )
        END_RUNG
        RUNG wire#powerrail
            Contact( #b )
        END_RUNG wire#w1
    END_NETWORK
END_FUNCTION_BLOCK
'''

COMMENTED = NET.replace('a : Int;', '{ S7_MLC := "MLC_a" }\n        a : Int;').replace(
    'x : Bool;', '{ S7_MLC := "MLC_x" }\n        x : Bool;')


def texts(**comments):
    """The .s7res of COMMENTED: its comments by member."""
    return 'MultiLingualTexts:\n' + ''.join('  - id: MLC_%s\n    en-US: %s\n' % c for c in comments.items())


def pair(before, after, res_b='', res_a=''):
    """(network pair, before layout, after layout) of the one network of two versions."""
    d = compare_blocks(src(before, res_b, 'K'), src(after, res_a, 'K'), all_=True)
    (p,) = d.nets
    return p, Layout(p.before.rungs, d.before.interface), Layout(p.after.rungs, d.after.interface)


def element(lay, instr):
    return next(e for e in lay.g.elements.values() if e.instr == instr)


def box_of(lay):
    return next(e for e in lay.g.elements.values() if e.kind == 'box')


def where(lay, el):
    """(x, y) the element is drawn at."""
    return next((x, y) for e, x, y in lay._placed() if e is el)


class EveryChangeHasItsMark(unittest.TestCase):
    """A mark must not depend on what else changed (a contact's relation stayed unmarked next to its operand)."""

    def marks(self, after, instr_b, instr_a):
        p, lb, la = pair(NET, after)
        out = []
        for lay, instr, side in ((lb, instr_b, 'removed'), (la, instr_a, 'added')):
            el = element(lay, instr)
            self.assertEqual(p.lad.status[el.eid], 'changed')
            x, y = where(lay, el)
            view = lay.views[el.eid]
            out.append(([m[3:] for m in lay.marks(p.lad.status, p.lad.other, side) if m[0] == el.eid], x, y, view))
        return out

    def assert_on_symbol(self, marks, x, y, view):
        cx = x + view.w / 2
        self.assertTrue(any(mx < cx < mx + w and my < y < my + h and w < view.w and h < view.above + view.below
                            for mx, my, w, h in marks), marks)

    def assert_on_top_text(self, marks, x, y, view):
        cx = x + view.w / 2
        self.assertTrue(any(mx < cx < mx + w and my + h <= y - 8 for mx, my, w, h in marks), marks)

    def test_relation_alone(self):
        for marks, x, y, view in self.marks(NET.replace('EQ_Contact', 'GE_Contact'), 'EQ_Contact', 'GE_Contact'):
            self.assert_on_symbol(marks, x, y, view)

    def test_relation_with_its_operand(self):
        after = NET.replace('EQ_Contact', 'GE_Contact').replace('in1 := #a', 'in1 := #b')
        for marks, x, y, view in self.marks(after, 'EQ_Contact', 'GE_Contact'):
            self.assert_on_symbol(marks, x, y, view)
            self.assert_on_top_text(marks, x, y, view)

    def test_relation_mark_stands_the_same_whatever_else_changed(self):
        alone = self.marks(NET.replace('EQ_Contact', 'GE_Contact'), 'EQ_Contact', 'GE_Contact')
        both = self.marks(NET.replace('EQ_Contact', 'GE_Contact').replace('in2 := #b', 'in2 := #a'),
                          'EQ_Contact', 'GE_Contact')
        for (marks_alone, *_), (marks_both, *_) in zip(alone, both):
            self.assertTrue(set(marks_alone) <= set(marks_both), (marks_alone, marks_both))

    def test_type_of_a_compare_with_its_operand(self):
        after = NET.replace('SrcType := Int', 'SrcType := DInt').replace('in1 := #a', 'in1 := #b')
        for marks, x, y, view in self.marks(after, 'EQ_Contact', 'EQ_Contact'):
            self.assert_on_symbol(marks, x, y, view)
            self.assert_on_top_text(marks, x, y, view)

    def test_negated_contact_with_its_operand(self):
        after = NET.replace('Contact( #x )', 'I_Contact( #y )')
        for marks, x, y, view in self.marks(after, 'Contact', 'I_Contact'):
            self.assert_on_symbol(marks, x, y, view)
            self.assert_on_top_text(marks, x, y, view)

    def test_kind_of_a_coil_with_its_operand(self):
        after = NET.replace('Coil( #q )', 'S_Coil( #s )')
        for marks, x, y, view in self.marks(after, 'Coil', 'S_Coil'):
            self.assert_on_symbol(marks, x, y, view)
            self.assert_on_top_text(marks, x, y, view)

    def test_operand_alone_leaves_the_symbol_unmarked(self):
        for marks, x, y, view in self.marks(NET.replace('in1 := #a', 'in1 := #b'), 'EQ_Contact', 'EQ_Contact'):
            self.assert_on_top_text(marks, x, y, view)
            self.assertEqual(len(marks), 1)
            self.assertFalse(marks[0][1] < y < marks[0][1] + marks[0][3])

    def test_a_change_no_pin_shows_marks_the_head_beside_a_pin(self):
        """The head stands for what has no place of its own, also when something else has one."""
        p, lb, _ = pair(CALL, CALL.replace('speed := 5', 'speed := 6'))
        box = box_of(lb)
        got = lb.views[box.eid].marks(0, 0, 'changed', {'speed', 'nowhere'}, p.lad.other[box.eid])
        self.assertEqual(sorted(m[0] for m in got), ['box', 'under'])


class PinOfOneVersion(unittest.TestCase):
    """A pin only one version has: its name and its value are marked, as a whole line of an SCL diff."""

    def pin_marks(self, lay, p, name):
        box = box_of(lay)
        view = lay.views[box.eid]
        x, y = where(lay, box)
        side, r = view.pinrow[name]
        py = y + (view.rowy if side == 'L' else view.rowy_r)[r]
        got = [m for m in lay.marks(p.lad.status, p.lad.other, 'removed') if m[0] == box.eid and m[4] < py < m[4] + m[6]]
        return got, x + view.lw

    def test_removed_input_marks_name_and_value(self):
        p, lb, _ = pair(CALL, CALL.replace('                speed := 5,\n', ''))
        got, bx = self.pin_marks(lb, p, 'speed')
        self.assertEqual(sorted(m[2] for m in got), ['box', 'under'])
        self.assertGreater(next(m for m in got if m[2] == 'box')[3], bx - 1)             # on the name, in the box
        value = next(m for m in got if m[2] == 'under')
        self.assertLess(value[3] + value[5], bx)                                         # on the value, left of the box

    def test_removed_output_marks_name_and_value(self):
        p, lb, _ = pair(CALL, CALL.replace(',\n                state => #c', ''))
        got, _ = self.pin_marks(lb, p, 'state')
        self.assertEqual(sorted(m[2] for m in got), ['box', 'under'])

    def test_added_pin_marks_name_and_value_on_the_after_side(self):
        p, _, la = pair(CALL.replace('                speed := 5,\n', ''), CALL)
        box = box_of(la)
        layers = [m[2] for m in la.marks(p.lad.status, p.lad.other, 'added') if m[0] == box.eid]
        self.assertEqual(sorted(layers), ['box', 'under'])

    def test_other_value_marks_only_the_value(self):
        p, lb, _ = pair(CALL, CALL.replace('speed := 5', 'speed := 6'))
        got, _ = self.pin_marks(lb, p, 'speed')
        self.assertEqual([m[2] for m in got], ['under'])

    def test_the_side_without_the_pin_marks_only_what_changed_there(self):
        """The pin's mark stands on the side that has it: no head mark on this one."""
        after = CALL.replace('                speed := 5,\n', '').replace('cmd := #c', 'cmd := #d')
        p, _, la = pair(CALL, after)
        box = box_of(la)
        self.assertEqual([m[2] for m in la.marks(p.lad.status, p.lad.other, 'added') if m[0] == box.eid], ['under'])

    def box_marks(self, fewer, more):
        """(marks of the box on the side without the pin, on the side with it), both ways round, as the page asks for them."""
        out = []
        for before, after, at_short, at_long in ((fewer, more, 0, 1), (more, fewer, 1, 0)):
            p, lb, la = pair(before, after)
            got = [[m for m in lay.marks(p.lad.status, p.lad.other, side, partner) if m[0] == box_of(lay).eid]
                   for lay, partner, side in ((lb, la, 'removed'), (la, lb, 'added'))]
            self.assertEqual(p.lad.status[box_of(lb).eid], 'changed')
            out.append((got[at_short], got[at_long]))
        return out

    def assert_only_on_the_side_with_the_pin(self, fewer, more, layers):
        for short, long in self.box_marks(fewer, more):
            self.assertEqual(short, [])
            self.assertEqual(sorted(m[2] for m in long), layers)

    def test_the_side_without_the_pin_marks_nothing_when_that_is_all(self):
        """The title reads the same on both sides: a fill on it reads as a call taken out or put in."""
        without = {'an input': '                speed := 5,\n', 'an in-out': '                cmd := #c,\n',
                   'an output': ',\n                state => #c'}
        for kind, text in without.items():
            with self.subTest(kind):
                self.assert_only_on_the_side_with_the_pin(CALL.replace(text, ''), CALL, ['box', 'under'])

    def test_the_side_without_the_pin_marks_nothing_for_a_pin_fed_by_logic(self):
        fewer = CALL.replace('                start := wire#w1,\n', '').replace(
            '        RUNG wire#powerrail\n            Contact( #b )\n        END_RUNG wire#w1\n', '')
        self.assert_only_on_the_side_with_the_pin(fewer, CALL, ['box'])

    def test_the_side_without_the_pin_marks_nothing_on_a_call_with_no_instance(self):
        call = CALL.replace('#inst(', '"Fc"(')
        self.assert_only_on_the_side_with_the_pin(call.replace('                speed := 5,\n', ''), call, ['box', 'under'])

    def test_the_side_without_the_pin_marks_nothing_for_a_pin_of_the_rung_with_an_operand(self):
        timer = CALL.replace('#inst(', '#inst.TON(').replace('''                start := wire#w1,
                speed := 5,
                cmd := #c,
                state => #c
''', '                pt := T#1s,\n                q => #q\n').replace(
            '        RUNG wire#powerrail\n            Contact( #b )\n        END_RUNG wire#w1\n', '')
        self.assert_only_on_the_side_with_the_pin(timer.replace(',\n                q => #q', ''), timer, ['box', 'under'])

    def test_a_block_renamed_keeps_its_mark_on_the_title_beside_a_pin(self):
        call = CALL.replace('#inst(', '"Fc"(')
        p, lb, la = pair(call, call.replace('"Fc"(', '"Fd"(').replace('                speed := 5,\n', ''))
        box = box_of(la)
        view = la.views[box.eid]
        x, y = where(la, box)
        self.assertEqual(la.marks(p.lad.status, p.lad.other, 'added', lb),
                         [(box.eid, 'added', 'box') + view._title_box(x + view.lw, y)])

    def test_another_type_setting_keeps_the_head_mark_beside_a_pin(self):
        call = CALL.replace('            #inst(', '            { S7_Templates := "SrcType := Int" }\n            #inst(')
        p, _, la = pair(call, call.replace('SrcType := Int', 'SrcType := DInt').replace('                speed := 5,\n', ''))
        box = box_of(la)
        view = la.views[box.eid]
        x, y = where(la, box)
        self.assertIn((box.eid, 'added', 'box', x + view.lw + .5, y - view.head + .5, view.bw - 1, view.head - 6),
                      la.marks(p.lad.status, p.lad.other, 'added'))


class CommentOfAnOperand(unittest.TestCase):
    """What the drawing shows of an operand besides its name is marked when it differs, the operand being the same."""

    def marks(self, before, after, pick, res_b='', res_a=''):
        p, lb, la = pair(before, after, res_b, res_a)
        out = []
        for lay, other, side in ((lb, la, 'removed'), (la, lb, 'added')):
            eid = pick(lay).eid
            out.append([m for m in lay.marks(p.lad.status, p.lad.other, side, other) if m[0] == eid])
        return out

    def contact(self, res_b, res_a):
        return self.marks(COMMENTED, COMMENTED, lambda l: element(l, 'Contact'), res_b, res_a)

    def test_contact(self):
        mb, ma = self.contact(texts(x='the switch'), texts(x='the key'))
        self.assertEqual(([m[1] for m in mb], [m[1] for m in ma]), (['removed'], ['added']))

    def test_compare_marks_only_the_operand_with_the_other_comment(self):
        res = texts(a='the first'), texts(a='the second')
        mb, _ = self.marks(COMMENTED, COMMENTED, lambda l: element(l, 'EQ_Contact'), *res)
        _, lb, _ = pair(COMMENTED, COMMENTED, *res)
        (m,) = mb
        self.assertLess(m[4] + m[6], where(lb, element(lb, 'EQ_Contact'))[1])            # in1, above the rung

    def test_network_stays_same(self):
        """The interface table tells the change: the network does not come on the page for it."""
        p, _, _ = pair(COMMENTED, COMMENTED, texts(x='the switch'), texts(x='the key'))
        self.assertEqual(p.state, 'same')

    def test_comment_added(self):
        mb, ma = self.contact('', texts(x='the switch'))
        self.assertEqual((len(mb), len(ma)), (1, 1))

    def test_same_comment_marks_nothing(self):
        self.assertEqual(self.contact(texts(x='the switch'), texts(x='the switch')), [[], []])

    def test_a_wire_of_another_number_marks_nothing(self):
        p, lb, la = pair(CALL, CALL.replace('wire#w1', 'wire#w7'))
        self.assertEqual(lb.marks(p.lad.status, p.lad.other, 'removed', la), [])

    def test_a_constant_of_another_value(self):
        with_const = NET.replace('    { S7_Language', '    VAR CONSTANT\n        LIMIT : Int := 5;\n    END_VAR\n'
                                 '    { S7_Language', 1).replace('in2 := #b', 'in2 := #LIMIT')
        mb, _ = self.marks(with_const, with_const.replace(':= 5', ':= 6'), lambda l: element(l, 'EQ_Contact'))
        self.assertEqual(len(mb), 1)

    def test_instance_comment_of_a_call(self):
        b = CALL.replace('inst : _.Drive;', '{ S7_MLC := "MLC_i" }\n        inst : _.Drive;')
        p, lb, la = pair(b, b, texts(i='the drive'), texts(i='the pump'))
        box = box_of(lb)
        (m,) = [m for m in lb.marks(p.lad.status, p.lad.other, 'removed', la) if m[0] == box.eid]
        self.assertLess(m[4] + m[6], where(lb, box)[1])                                  # above the box

    def test_on_the_page(self):
        d = compare_blocks(src(COMMENTED, texts(x='the switch'), 'K'),
                           src(COMMENTED.replace('EQ_Contact', 'GE_Contact'), texts(x='the key'), 'K'))
        html = network_html(d.nets[0], d.before, d.after)
        self.assertEqual((html.count('class="hl removed"'), html.count('class="hl added"')), (2, 2))    # comment, relation


class TheBoxOfACall(unittest.TestCase):
    """What a call box draws through the declaration of its instance or the block it calls: the same operand, drawn
    otherwise, is marked."""
    CHAIN = CALL.replace('inst : _.Drive;', 'inst : "DriveA";')

    def marks_of(self, before, after):
        p, lb, la = pair(before, after)
        return p, lb, la, [[m for m in lay.marks(p.lad.status, p.lad.other, side, other) if m[0] == box_of(lay).eid]
                           for lay, other, side in ((lb, la, 'removed'), (la, lb, 'added'))]

    def assert_on_title(self, lay, marks):
        box = box_of(lay)
        x, y = where(lay, box)
        view = lay.views[box.eid]
        tx, ty, tw_, th = view._title_box(x + view.lw, y)
        self.assertIn(('box', tx, ty, tw_, th), [tuple(m[2:]) for m in marks])

    def test_title_through_the_instance_type_alone(self):
        p, lb, la, (mb, ma) = self.marks_of(self.CHAIN, self.CHAIN.replace('"DriveA"', '"DriveB"'))
        self.assertEqual((lb.views[box_of(lb).eid].title, la.views[box_of(la).eid].title), ('"DriveA"', '"DriveB"'))
        self.assert_on_title(lb, mb)
        self.assert_on_title(la, ma)
        self.assertEqual(({m[1] for m in mb}, {m[1] for m in ma}), ({'removed'}, {'added'}))

    def test_title_beside_a_changed_pin(self):
        after = self.CHAIN.replace('"DriveA"', '"DriveB"').replace('speed := 5', 'speed := 6')
        _, lb, la, (mb, ma) = self.marks_of(self.CHAIN, after)
        self.assert_on_title(lb, mb)
        self.assert_on_title(la, ma)
        self.assertEqual(sorted(m[2] for m in mb), ['box', 'under'])

    def test_network_alone_stays_off_the_page(self):
        p, _, _, _ = self.marks_of(self.CHAIN, self.CHAIN.replace('"DriveA"', '"DriveB"'))
        self.assertEqual(p.state, 'same')

    def test_same_title_marks_nothing(self):
        self.assertEqual(self.marks_of(self.CHAIN, self.CHAIN)[3], [[], []])

    def conversion(self, before, after):
        """Two versions of a Switch box whose K is fed #c of another type than its SrcType."""
        text = '''FUNCTION_BLOCK "K"
    VAR
        c : %s;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            { S7_Templates := "SrcType := Int" }
            Switch(
                k := #c,
                dst0 => m1
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''
        return self.marks_of(text % before, text % after)

    def test_conversion_mark_that_appears(self):
        _, lb, la, (mb, ma) = self.conversion('Int', 'DInt')
        vb, va = lb.views[box_of(lb).eid], la.views[box_of(la).eid]
        self.assertEqual((len(vb.conv), len(va.conv)), (0, 1))
        self.assertEqual(([m[2] for m in mb], [m[2] for m in ma]), (['under'], ['under']))

    def test_conversion_mark_that_goes(self):
        _, lb, la, (mb, ma) = self.conversion('DInt', 'Int')
        self.assertEqual((len(lb.views[box_of(lb).eid].conv), len(la.views[box_of(la).eid].conv)), (1, 0))
        self.assertEqual(([m[2] for m in mb], [m[2] for m in ma]), (['under'], ['under']))

    def test_conversion_mark_on_both_marks_nothing(self):
        _, lb, _, (mb, ma) = self.conversion('DInt', 'LInt')
        self.assertEqual(len(lb.views[box_of(lb).eid].conv), 1)
        self.assertEqual((mb, ma), ([], []))
    def called(self, number, comment):
        itf = parse_block(src('''FUNCTION "Called" : Void
    VAR_INPUT
        speed : Int;
    END_VAR
END_FUNCTION
''', '', 'Called')).interface
        itf.block = SimpleNamespace(kind='FUNCTION', props={'S7_BlockNumber': number, 'S7_BlockComment': comment})
        return lambda name: itf if name == 'Called' else None

    def fc_marks(self, before, after):
        """The marks of a call of a block drawn with its number and comment, the block in another state on each side."""
        text = '''FUNCTION_BLOCK "K"
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            "Called"(
                speed := 5
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''
        d = compare_blocks(src(text, '', 'K'), src(text, '', 'K'), all_=True)
        (p,) = d.nets
        lb = Layout(p.before.rungs, d.before.interface, self.called(*before))
        la = Layout(p.after.rungs, d.after.interface, self.called(*after))
        return lb, [m[2:] for m in lb.marks(p.lad.status, p.lad.other, 'removed', la)]

    def test_number_of_the_called_block(self):
        lb, marks = self.fc_marks(('5', 'Runs'), ('6', 'Runs'))
        box = box_of(lb)
        x, y = where(lb, box)
        view = lb.views[box.eid]
        (layer, mx, my, _, h), = marks
        self.assertEqual(layer, 'box')
        self.assertLess(my + h, view._title_box(x + view.lw, y)[1] + 1)                  # above the title, on the number

    def test_comment_of_the_called_block(self):
        lb, marks = self.fc_marks(('5', 'Runs'), ('5', 'Stops'))
        box = box_of(lb)
        view = lb.views[box.eid]
        (layer, _, my, _, h), = marks
        self.assertEqual(layer, 'under')
        self.assertLess(my + h, where(lb, box)[1] - view.head + 6)                       # above the box

    def test_same_called_block_marks_nothing(self):
        self.assertEqual(self.fc_marks(('5', 'Runs'), ('5', 'Runs'))[1], [])


def xml_block(*texts):
    """A SimaticML FB with no network, its multilingual texts as a real export writes them: (composition, text)."""
    item = ('<MultilingualText CompositionName="%s"><ObjectList><MultilingualTextItem><AttributeList><Culture>en-US'
            '</Culture><Text>%s</Text></AttributeList></MultilingualTextItem></ObjectList></MultilingualText>')
    return ('<Document><SW.Blocks.FB ID="0"><AttributeList><Interface><Sections xmlns="http://www.siemens.com/'
            'automation/Openness/SW/Interface/v5"><Section Name="Static"><Member Name="speed" Datatype="Int"/>'
            '</Section></Sections></Interface><Name>F</Name>'
            '<ProgrammingLanguage>SCL</ProgrammingLanguage></AttributeList><ObjectList>%s</ObjectList></SW.Blocks.FB>'
            '</Document>' % ''.join(item % x for x in texts))


def _dom(page, script, query='', size=(1100, 800)):
    """The document of that page with that script added, as a browser of that size holds it after its scripts ran."""
    import pathlib
    import sys
    from TiaChangeReports import __main__ as cli
    sys.path.insert(0, os.path.join(os.path.dirname(cli.HERE), 'TiaHmiGenerator'))
    try:
        from hmipreview.edge import Edge, edge_path
    except ImportError:
        raise unittest.SkipTest('hmipreview missing')
    if not edge_path():
        raise unittest.SkipTest('no Microsoft Edge or Google Chrome')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'p.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(page.replace('</body>', script + '</body>'))
        e = Edge()
        try:
            with contextlib.redirect_stderr(None):
                return e.dump_dom(pathlib.Path(out).as_uri() + query, timeout=120, size=size)
        finally:
            e.close()


class NewBlocks(unittest.TestCase):
    """A new block shows its members and code as added, a deleted one as removed; on request (draw_added_removed False,
    --new-blocks-listed) each is its heading only."""
    SCL = '''FUNCTION "F" : Void
    VAR_INPUT
        speed : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        #speed := 1;
    END_NETWORK
END_FUNCTION
'''
    UDT = '''TYPE "U"
    STRUCT
        speed : Int;
    END_STRUCT;
END_TYPE
'''

    def html(self, before, after, name='K', **kw):
        return render([compare_blocks(src(before, '', name) if before else None,
                                      src(after, '', name) if after else None)], 'b', 'a', **kw)

    def test_by_default_its_contents(self):
        for text, name in ((NET, 'K'), (self.SCL, 'F'), (self.UDT, 'U')):
            self.assertEqual(self.html(None, text, name), self.html(None, text, name, draw_added_removed=True), name)

    def test_listed_a_heading(self):
        for (text, name), deleted in itertools.product(((NET, 'K'), (self.SCL, 'F'), (self.UDT, 'U')), (False, True)):
            sides = (text, None) if deleted else (None, text)
            html = self.html(*sides, name, draw_added_removed=False)
            self.assertIn('<b>%s [' % name, html)
            self.assertNotIn('class="hl', html)
            self.assertNotIn('<b>Interface</b>', html)
            self.assertNotIn('#speed := 1', html)
            self.assertNotIn('class="fa"', html)

    def test_listed_but_asked_for_its_interface_and_code(self):
        """--new-blocks-listed with --all, --block or --network (full): a new or deleted block drawn whole, its
        interface too, as the list and --json report it; a UDT, no networks, its interface."""
        for before, after, mark in ((None, NET, 'added'), (NET, None, 'removed')):
            html = self.html(before, after, full=True, draw_added_removed=False)
            self.assertEqual(html.count('class="hl %s"' % mark), 3, mark)
            self.assertIn('<b>Interface</b>', html, mark)
        for before, after, row in ((None, self.UDT, 'ins'), (self.UDT, None, 'del')):
            html = self.html(before, after, 'U', full=True, draw_added_removed=False)
            self.assertRegex(html[html.index('<b>Interface</b>'):], r'<tr class="%s"[^>]*>.*?speed' % row, row)

    def test_listed_but_asked_for_on_the_command_line(self):
        """The same through main: --all and --block, a new and a deleted block and a deleted UDT; each with its
        interface on the page and (interface) in the list."""
        blocks = {'plc/blocks/F.s7dcl': self.SCL, 'plc/types/U.s7dcl': self.UDT}
        for sides, state in (((blocks, {}), 'deleted'), (({}, blocks), 'new')):
            for asked in (('--all',), ('--block', 'F', '--block', 'U')):
                with tempfile.TemporaryDirectory() as tmp:
                    before, after = os.path.join(tmp, 'b'), os.path.join(tmp, 'a')
                    for folder, files in zip((before, after), sides):
                        _put(folder, {'plc/blocks/K.s7dcl': NET, **files})
                    out, page = io.StringIO(), os.path.join(tmp, 'r.html')
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(0, main([before, after, '-o', page, '--only', 'plc', '--new-blocks-listed',
                                                  *asked]))
                    with open(page, encoding='utf-8') as f:
                        html = f.read()
                for name in ('F', 'U'):
                    block = html[html.index('id="blk-%s"' % name):]
                    block = block[:block.index('</section>')]
                    self.assertIn('<b>Interface</b>', block, (state, asked, name))
                    self.assertIn('%s  %-11s %s  (interface)' % (state.ljust(7), 'UDT' if name == 'U' else 'FC', name),
                                  out.getvalue(), (state, asked, name))
                self.assertIn('#speed := 1', unescape(re.sub(r'<[^>]+>', '', html)), (state, asked))

    def test_lad_block(self):
        html = self.html(None, NET, draw_added_removed=True)
        self.assertEqual(html.count('class="hl added"'), 3)                              # the three elements, whole
        self.assertIn('<b>Interface</b>', html)
        self.assertIn('class="fa"', html)
        self.assertIn('no network', html)                                                # nothing before

    def test_scl_block(self):
        html = self.html(None, self.SCL, 'F', draw_added_removed=True)
        self.assertIn('#speed := 1', re.sub(r'<[^>]+>', '', html))
        self.assertIn('speed', html[html.index('<b>Interface</b>'):])

    def test_members_are_added(self):
        html = self.html(None, self.UDT, 'U', draw_added_removed=True)
        table = html[html.index('<b>Interface</b>'):]
        self.assertRegex(table, r'<tr class="ins"[^>]*>.*?speed')
        self.assertNotIn('unchanged', table)

    def test_title_and_comment_of_a_new_block_as_added(self):
        """TIA shows them above the first network; a changed one stood on the page, a new one on neither
        format's."""
        s7dcl = '{ S7_BlockTitle := "Inventory title"; S7_BlockComment := "Inventory: S7" }\n' + self.SCL
        xml = xml_block(('Title', 'Inventory title'), ('Comment', 'Inventory: S7'))
        for after, name in ((src(s7dcl, '', 'F'), 'S7'), (BlockSource('F', '', None, 'F.xml', xml=xml), 'SimaticML')):
            html = render([compare_blocks(None, after)], 'b', 'a', draw_added_removed=True)
            box = html[html.index('<b>Properties</b>'):html.index('<b>Interface</b>')]
            self.assertIn('TitleInventory title', re.sub(r'<[^>]+>', '', box), name)
            self.assertIn('CommentInventory: S7', re.sub(r'<[^>]+>', '', box), name)
            self.assertEqual(box.count('<tr class="ins">'), 2, name)
            self.assertEqual(box.count('class="tx ins"'), 2, name)
            self.assertNotIn('class="tx del"', box, name)

    def test_title_and_comment_wherever_the_new_block_is_drawn(self):
        """--block and --all draw its networks, so its title and comment too."""
        text = '{ S7_BlockTitle := "Inventory title"; S7_BlockComment := "Inventory: S7" }\n' + self.SCL
        d = compare_blocks(None, src(text, '', 'F'), all_=True)
        page = re.sub(r'<[^>]+>', '', render([d], 'b', 'a', full=True))
        self.assertIn('TitleInventory title', page)
        self.assertIn('Inventory: S7', page)
        self.assertIn('#speed := 1', unescape(page))

    def test_drawn_full_its_interface_too(self):
        """--all, --block and --network (full) draw a new block with the default as without them: its
        interface with the members as added, beside its code."""
        d = compare_blocks(None, src(self.SCL, '', 'F'), all_=True)
        pages = [render([d], 'b', 'a', full=True)] + [self.page(*args) for args in (('--all',), ('--block', 'F'))]
        for page in pages:
            block = page[page.index('id="blk-F"'):]
            self.assertRegex(block[block.index('<b>Interface</b>'):], r'<tr class="ins"[^>]*>.*?speed')
            self.assertIn('#speed := 1', unescape(re.sub(r'<[^>]+>', '', block)))

    def test_listed_only_it_stays_a_heading(self):
        """Its texts stay out as well, of a new block and of a deleted one."""
        text = '{ S7_BlockComment := "Why" }\n' + self.SCL
        self.assertNotIn('Why', render([compare_blocks(None, src(text, '', 'F'))], 'b', 'a', draw_added_removed=False))
        self.assertNotIn('Why', render([compare_blocks(src(text, '', 'F'), None)], 'b', 'a', draw_added_removed=False))

    def test_title_and_comment_of_a_deleted_block_as_removed(self):
        text = '{ S7_BlockTitle := "Inventory title"; S7_BlockComment := "Why" }\n' + self.SCL
        html = render([compare_blocks(src(text, '', 'F'), None)], 'b', 'a')
        box = html[html.index('<b>Properties</b>'):html.index('<b>Interface</b>')]
        self.assertIn('TitleInventory title', re.sub(r'<[^>]+>', '', box))
        self.assertIn('CommentWhy', re.sub(r'<[^>]+>', '', box))
        self.assertEqual(box.count('<tr class="del">'), 2)
        self.assertEqual(box.count('class="tx del"'), 2)
        self.assertNotIn('class="tx ins"', box)

    def test_only_its_title_and_comment_stand_there(self):
        html = self.html(None, '{ S7_Version := "0.1"; S7_BlockComment := "Why" }\n' + self.SCL, 'F',
                         draw_added_removed=True)
        box = html[html.index('<b>Properties</b>'):html.index('<b>Interface</b>')]
        self.assertIn('Why', box)
        self.assertNotIn('Version', box)

    def test_no_title_or_comment_no_properties(self):
        self.assertNotIn('<b>Properties</b>', self.html(None, self.SCL, 'F', draw_added_removed=True))

    def test_a_new_block_only_listed_keeps_its_heading(self):
        self.assertNotIn('Why', self.html(None, '{ S7_BlockComment := "Why" }\n' + self.SCL, 'F',
                                          draw_added_removed=False))

    def test_a_deleted_block_by_default_its_contents_as_removed(self):
        """As a new block's, on the other side: its members and code, marked removed."""
        html = self.html(NET, None)
        self.assertEqual(html, self.html(NET, None, draw_added_removed=True))
        self.assertEqual(html.count('class="hl removed"'), 3)                            # the three elements, whole
        self.assertNotIn('class="hl added"', html)
        self.assertIn('<span class="st deleted">deleted</span>', html)
        self.assertIn('class="fa"', html)
        self.assertIn('no network', html)                                                # nothing after
        for text, name in ((self.SCL, 'F'), (self.UDT, 'U')):
            html = self.html(text, None, name)
            table = html[html.index('<b>Interface</b>'):]
            self.assertRegex(table, r'<tr class="del"[^>]*>.*?speed', name)
            self.assertNotIn('<tr class="ins"', table, name)
        self.assertIn('#speed := 1', re.sub(r'<[^>]+>', '', self.html(self.SCL, None, 'F')))

    def test_a_changed_block_does_not_change_with_it(self):
        changed = NET.replace('Contact( #x )', 'Contact( #y )')
        self.assertEqual(self.html(NET, changed, draw_added_removed=False), self.html(NET, changed))

    def run_main(self, folder, args):
        """The page main writes into folder for args, --only plc."""
        out = os.path.join(folder, 'r.html')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, main(list(args) + ['-o', out, '--only', 'plc']))
        with open(out, encoding='utf-8') as f:
            return f.read()

    def page(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = os.path.join(tmp, 'b'), os.path.join(tmp, 'a')
            _put(before, {'plc/blocks/K.s7dcl': NET})
            _put(after, {'plc/blocks/K.s7dcl': NET, 'plc/blocks/F.s7dcl': self.SCL})
            return self.run_main(tmp, (before, after) + args)

    def test_on_the_command_line(self):
        for args in ((), ('--new-blocks',)):                   # --new-blocks: the default, kept for older calls
            self.assertIn('#speed := 1', re.sub(r'<[^>]+>', '', self.page(*args)), args)
        self.assertNotIn('#speed := 1', re.sub(r'<[^>]+>', '', self.page('--new-blocks-listed')))

    def test_listed_in_the_list_and_json_too(self):
        """--new-blocks-listed: a new block's networks and interface stay out of the list and --json, as of the page."""
        import json
        with tempfile.TemporaryDirectory() as tmp:
            before, after = os.path.join(tmp, 'b'), os.path.join(tmp, 'a')
            _put(before, {'plc/blocks/K.s7dcl': NET})
            _put(after, {'plc/blocks/K.s7dcl': NET, 'plc/blocks/F.s7dcl': self.SCL})
            got = {}
            for args in ((), ('--new-blocks-listed',)):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    main([before, after, '-o', os.path.join(tmp, 'r.html'), '--json', *args])
                (b,) = json.loads(out.getvalue())['blocks']
                got[args] = (b['state'], b['interface'], len(b['networks']))
        self.assertEqual({(): ('new', True, 1), ('--new-blocks-listed',): ('new', False, 0)}, got)

    def test_listed_and_drawn_exclude_each_other(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.page('--new-blocks', '--new-blocks-listed')

    def test_a_real_commit_with_a_new_block(self):
        """A project repo's commit that adds a LAD FC (the export as TIA wrote it, fixtures/new-block): the
        default page of --git draws its interface and network as added, --new-blocks-listed its heading only."""
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'new-block', 'zzE2eKindMc.s7dcl')
        with tempfile.TemporaryDirectory() as repo:
            _put(repo, {'plc/blocks/K.s7dcl': NET})
            fixture_git(repo, 'init', '-q')
            fixture_git(repo, 'add', '-A')
            fixture_git(repo, 'commit', '-q', '-m', 'before')
            os.makedirs(os.path.join(repo, 'plc', 'blocks', 'zzFromMc'))
            shutil.copy(fixture, os.path.join(repo, 'plc', 'blocks', 'zzFromMc'))
            fixture_git(repo, 'add', '-A')
            fixture_git(repo, 'commit', '-q', '-m', 'zzE2eKindMc: a new block')
            git = ('--git', repo, 'HEAD~1', 'HEAD')
            drawn, listed = self.run_main(repo, git), self.run_main(repo, git + ('--new-blocks-listed',))
        block = drawn[drawn.index('id="blk-zzE2eKindMc"'):]
        table = block[block.index('<b>Interface</b>'):]
        for member in ('inP', 'outP'):
            self.assertRegex(table, r'<tr class="ins"[^>]*>.*?%s' % member)
        self.assertEqual(block.count('class="hl added"'), 2)            # the contact and the coil, whole
        self.assertIn('<span class="st new">new</span>', block)
        self.assertNotIn('<b>Interface</b>', listed)
        self.assertNotIn('class="hl added"', listed)
        self.assertIn('id="blk-zzE2eKindMc"', listed)


class FocusStackedScl(unittest.TestCase):
    """An SCL network in focus shows before above after, each half filling the window, with the toggle and S
    as a ladder has them. Row by row the halves line up and scroll in step, a long line folds under its one number, and
    the page itself keeps the one table."""
    WINDOW = (1100, 800)
    CALL = '#instGET(REQ := "zzInvCom".bool_1, ID := "zzInvCom".word_1, NDR => "zzInvCom".bool_2, ERROR => "zzInvCom".e); '
    OLD = CALL * 2 + '// 111'                           # folds at the whole width, against NEW that does not
    NEW = CALL + '// 222'
    LINES = ['#line_%d := %d;' % (k, k) for k in range(1, 121)]
    # Step by step, what the window shows of the first SCL network: on the page, in focus, with S, with the toggle, with a
    # fold row clicked, with the first half scrolled, with a key, and back on the page. Headless Edge at a set time draws no
    # frames, so no scroll event of its own: the walk sends it.
    WALK = ("<script>addEventListener('load',function(){try{localStorage.removeItem('ldiff-stack')}catch(e){}"
            "var fc=function(){return document.querySelector('.ldiff .fcs')},"
            "shown=function(e){return !!e&&e.getClientRects().length>0},"
            "box=function(e){var b=e.getBoundingClientRect();"
            "return {top:b.top,bottom:b.bottom,left:b.left,right:b.right,height:b.height}},"
            "lines=function(c){var g=document.createRange();g.selectNodeContents(c);"
            "return new Set([].map.call(g.getClientRects(),function(x){return Math.round(x.top)})).size},"
            "net=function(){return document.querySelector('.ldiff .nw:has(>table.scl)')},"
            "panes=function(){return [].slice.call(net().querySelectorAll(':scope>.panes>.pane'))},"
            "row=function(t){return {cls:t.className,shown:shown(t),top:t.getBoundingClientRect().top,"
            "cells:[].map.call(t.cells,function(c){return {cls:c.className,text:c.textContent.replace(/\\u200b/g,''),"
            "lines:shown(t)?lines(c):0}})}},"
            "see=function(){var n=net(),f=fc(),s=f.querySelector('.fl'),x=f.querySelector('.nwt .fx');return {"
            "focus:!f.hidden,stacked:f.classList.contains('stk'),keep:localStorage.getItem('ldiff-stack'),"
            "view:[innerWidth,innerHeight],"
            "overlayScrolls:f.scrollHeight>f.clientHeight&&getComputedStyle(f).overflowY!='hidden',"
            "table:shown(n.querySelector(':scope>table.scl')),"
            "button:shown(s)?box(s):null,focusButton:shown(x)?box(x):null,"
            "panes:panes().map(function(p){var q=p.querySelector('.pb'),t=q.querySelector('table');return {"
            "shown:shown(p),box:box(p),scroll:q.scrollTop,frame:q.clientHeight,range:q.scrollHeight-q.clientHeight,"
            "stripText:(p.querySelector('.sl')||{}).textContent,title:!!p.querySelector('.sh'),"
            "empty:(q.querySelector('.empty')||{}).textContent,rows:t?[].map.call(t.rows,row):null}})}},"
            "out={},steps=["
            "function(){out.page=see();net().querySelector('.nwt .fx').click()},"
            "function(){out.focus=see();document.dispatchEvent(new KeyboardEvent('keydown',{key:'s',bubbles:true}))},"
            "function(){out.beside=see();fc().querySelector('.fl').click()},"
            "function(){out.again=see();var k=panes()[1].querySelector('tr.skip');if(k)k.click()},"
            "function(){out.all=see();var q=panes()[0].querySelector('.pb');"
            "q.parentNode.dispatchEvent(new Event('pointerenter'));q.scrollTop=q.scrollHeight;"
            "q.dispatchEvent(new Event('scroll'))},"
            "function(){out.scrolled=see();panes().forEach(function(p){p.querySelector('.pb').scrollTop=0});fc().focus();"
            "fc().dispatchEvent(new KeyboardEvent('keydown',{key:'PageDown',bubbles:true}));"
            "panes().forEach(function(p){p.querySelector('.pb').dispatchEvent(new Event('scroll'))})},"
            "function(){out.key=see();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))},"
            "function(){out.back=see()}],"
            "go=function(k){if(k<steps.length){try{steps[k]()}catch(e){out.error=String(e)}"
            "setTimeout(function(){go(k+1)},150)}"
            "else document.body.setAttribute('data-walk',JSON.stringify(out))};setTimeout(function(){go(0)},100)})</script>")

    @classmethod
    def walk(cls, before, after, comment=None):
        """What the walk saw of that code; comment: the network's comment on the after side only."""
        import json
        code = lambda lines: NewBlocks.SCL.replace('#speed := 1;', '\n        '.join(lines))
        res = ''
        late = code(after) if after else None
        if comment:
            res = 'MultiLingualTexts:\n  - id: MLC_c\n    en-US: %s\n' % comment
            late = late.replace('{ S7_Language := "SCL" }', '{ S7_Language := "SCL"; S7_NetworkComment := "MLC_c" }')
        page = render([compare_blocks(src(code(before), '', 'F') if before else None,
                                      src(late, res, 'F') if late else None)], 'b', 'a', draw_added_removed=True)
        found = re.search(r'data-walk="([^"]*)"', _dom(page, cls.WALK, size=cls.WINDOW))
        if not found:
            raise AssertionError('the walk did not finish')
        got = json.loads(unescape(found.group(1)))
        if 'error' in got:
            raise AssertionError(got['error'])
        return got

    @classmethod
    def setUpClass(cls):
        cls.got = cls.walk(cls.LINES + [cls.OLD] + cls.LINES, cls.LINES + [cls.NEW] + cls.LINES)

    @staticmethod
    def code(pane):
        """(number, text) of the rows of a half that hold a line of that half."""
        return [(r['cells'][0]['text'], r['cells'][1]['text']) for r in pane['rows']
                if len(r['cells']) == 2 and r['cells'][0]['text']]

    def test_before_above_after_each_half_filling_the_window(self):
        one, two = self.got['focus']['panes']
        self.assertTrue(self.got['focus']['stacked'])
        self.assertFalse(self.got['focus']['table'])
        self.assertFalse(self.got['focus']['overlayScrolls'])
        self.assertAlmostEqual(one['box']['top'], 0, delta=1)
        self.assertAlmostEqual(one['box']['bottom'], two['box']['top'], delta=1)
        self.assertAlmostEqual(two['box']['bottom'], self.got['focus']['view'][1], delta=1)
        self.assertAlmostEqual(one['box']['height'], two['box']['height'], delta=1)
        self.assertGreater(one['box']['right'] - one['box']['left'], self.got['focus']['view'][0] - 30)   # the whole width

    def test_each_half_has_its_label_and_title(self):
        for pane, label in zip(self.got['focus']['panes'], ('Before', 'After')):
            self.assertTrue(pane['title'])
            self.assertIn(label, pane['stripText'])

    def test_a_changed_line_reads_before_above_after(self):
        one, two = self.got['focus']['panes']
        changed = [k for k, r in enumerate(one['rows']) if 'del' in r['cells'][-1]['cls']]
        self.assertEqual(len(changed), 1)
        k = changed[0]
        self.assertEqual(one['rows'][k]['cells'][0]['text'], '121')
        self.assertEqual(one['rows'][k]['cells'][1]['text'], self.OLD)
        self.assertEqual(two['rows'][k]['cells'][0]['text'], '121')
        self.assertEqual(two['rows'][k]['cells'][1]['text'], self.NEW)
        self.assertIn('ins', two['rows'][k]['cells'][1]['cls'])

    def test_a_folded_line_keeps_its_one_number(self):
        one, two = self.got['focus']['panes']
        row = [r for r in one['rows'] if 'del' in r['cells'][-1]['cls']][0]
        self.assertGreater(row['cells'][1]['lines'], 1)      # it folds, at the whole width as it has
        self.assertEqual(row['cells'][0]['lines'], 1)
        self.assertEqual(two['rows'][one['rows'].index(row)]['cells'][1]['lines'], 1)
        numbers = [str(k) for k in range(1, 242)]
        for pane in self.got['all']['panes']:                # no number added by a fold, none lost
            self.assertEqual([n for n, _ in self.code(pane)], numbers)

    def test_rows_line_up_though_a_line_folds_on_one_side_only(self):
        for state in ('focus', 'again', 'all'):
            one, two = self.got[state]['panes']
            self.assertEqual(len(one['rows']), len(two['rows']))
            rows = [(a, b) for a, b in zip(one['rows'], two['rows']) if a['shown']]
            self.assertTrue(all(b['shown'] for _, b in rows))
            for a, b in rows:
                self.assertAlmostEqual(a['top'] - rows[0][0]['top'], b['top'] - rows[0][1]['top'], delta=.5, msg=state)

    def test_the_halves_scroll_in_step(self):
        one, two = self.got['scrolled']['panes']
        self.assertGreater(one['scroll'], 0)
        self.assertEqual(one['scroll'], two['scroll'])

    def test_a_long_comment_on_one_half_leaves_one_scroll_range(self):
        got = self.walk(self.LINES, self.LINES + [self.NEW], 'one of many words ' * 60)
        one, two = got['scrolled']['panes']
        self.assertGreater(one['frame'], two['frame'] + 30)  # the comment takes room from the second half only
        self.assertGreater(one['range'], 0)
        self.assertAlmostEqual(one['range'], two['range'], delta=1)
        self.assertAlmostEqual(one['scroll'], one['range'], delta=1)     # at its end, and the other with it
        self.assertAlmostEqual(two['scroll'], two['range'], delta=1)

    def test_the_keys_scroll_the_halves(self):
        one, two = self.got['key']['panes']
        self.assertGreater(one['scroll'], 0)
        self.assertEqual(one['scroll'], two['scroll'])

    def test_a_fold_row_opens_on_both_halves(self):
        for pane in self.got['focus']['panes']:
            self.assertTrue(any('skip' in r['cls'] and r['shown'] for r in pane['rows']))
            self.assertFalse(any('ctx' in r['cls'] and r['shown'] for r in pane['rows']))
        for pane in self.got['all']['panes']:
            self.assertFalse(any('skip' in r['cls'] and r['shown'] for r in pane['rows']))
            self.assertTrue(all(r['shown'] for r in pane['rows'] if 'ctx' in r['cls']))

    def test_the_toggle_and_s_go_to_side_by_side_and_back(self):
        beside, again = self.got['beside'], self.got['again']
        self.assertFalse(beside['stacked'])
        self.assertEqual(beside['keep'], '0')
        self.assertTrue(beside['table'])
        self.assertFalse(any(p['shown'] for p in beside['panes']))
        self.assertTrue(again['stacked'])
        self.assertEqual(again['keep'], '1')
        self.assertFalse(again['table'])

    def test_the_buttons_stand_at_one_place_in_both_layouts(self):
        for key in ('button', 'focusButton'):
            self.assertIsNotNone(self.got['focus'][key], key)
            for side in ('top', 'left', 'right'):
                self.assertAlmostEqual(self.got['focus'][key][side], self.got['beside'][key][side], delta=1, msg=key)

    def test_the_buttons_stay_clear_of_the_scrollbar_side_by_side(self):
        self.assertLess(self.got['beside']['focusButton']['right'], self.got['beside']['view'][0] - 20)

    def test_the_page_keeps_its_table(self):
        self.assertTrue(self.got['page']['table'])
        self.assertEqual(self.got['page']['panes'], [])
        self.assertFalse(self.got['back']['focus'])
        self.assertTrue(self.got['back']['table'])
        self.assertFalse(any(p['shown'] for p in self.got['back']['panes']))

    def test_a_new_network_takes_the_window_but_for_the_missing_half(self):
        got = self.walk(None, self.LINES)
        one, two = got['focus']['panes']
        self.assertEqual(one['empty'], 'no network')
        self.assertIsNone(one['rows'])
        self.assertFalse(one['title'])
        self.assertLess(one['box']['height'], 70)
        self.assertGreater(two['box']['height'], got['focus']['view'][1] - 80)
        self.assertEqual([n for n, _ in self.code(two)], [str(k) for k in range(1, 121)])

    def test_a_deleted_network_takes_the_window_but_for_the_missing_half(self):
        second = ['END_NETWORK', '{ S7_Language := "SCL" }', 'NETWORK', '#gone := 1;', '#gone := 2;']
        got = self.walk(self.LINES + second, self.LINES)
        one, two = got['focus']['panes']
        self.assertEqual(two['empty'], 'no network')
        self.assertLess(two['box']['height'], 70)
        self.assertGreater(one['box']['height'], got['focus']['view'][1] - 80)
        self.assertEqual(self.code(one), [('1', '#gone := 1;'), ('2', '#gone := 2;')])

    def test_a_network_with_no_text_is_no_missing_network(self):
        one, two = self.walk([''], ['#speed := 2;'])['focus']['panes']
        self.assertIsNone(one.get('empty'))
        self.assertIsNone(two.get('empty'))
        self.assertTrue(one['title'])


class SclLines(unittest.TestCase):
    """A long SCL line folds, on screen, on paper and in a shot, where TIA keeps one line with a scrollbar, so
    no part of it is out of view. It stays one row with its one number, so a fold adds no line."""
    LONG = '#instGET(REQ := "zzInvCom".bool_1, ID := "zzInvCom".word_1, NDR => "zzInvCom".bool_2, ERROR => "zzInvCom".e);'
    # What a line takes on the page, per row of the table and per side: its number, how many lines of text the number and
    # the code stand on, whether each ends inside its cell, and the text of each line of a folded code.
    MEASURE = ("<script>addEventListener('load',function(){setTimeout(function(){"
               "var box=function(c){var g=document.createRange();g.selectNodeContents(c);return g},"
               "lines=function(c){return new Set([].map.call(box(c).getClientRects(),"
               "function(x){return Math.round(x.top)})).size},"
               "inside=function(c){return box(c).getBoundingClientRect().right<=c.getBoundingClientRect().right+1},"
               "folds=function(c){var out=[],top=null,w=document.createTreeWalker(c,NodeFilter.SHOW_TEXT),n;"
               "while(n=w.nextNode())for(var k=0;k<n.length;k++){var g=document.createRange();g.setStart(n,k);g.setEnd(n,k+1);"
               "var r=g.getClientRects()[0],y=r?Math.round(r.top):top;if(y!==top){out.push('');top=y}"
               "out[out.length-1]+=n.data[k]}return out},"
               "side=function(n,t){return {number:n.textContent,numberLines:lines(n),numberInside:inside(n),"
               "codeLines:lines(t),codeInside:inside(t),codeFolds:lines(t)>1?folds(t):[]}};"
               "document.body.setAttribute('data-layout',JSON.stringify({"
               "wide:document.documentElement.scrollWidth>document.documentElement.clientWidth,"
               "rows:[].map.call(document.querySelectorAll('table.scl tr'),function(t){var c=t.cells;"
               "return {before:side(c[0],c[1]),after:side(c[2],c[3])}})}))},100)})</script>")

    def layout(self, before, after, query='?all'):
        """How a browser 1100 px wide lays out the block of that code; before None: a new block."""
        import json
        code = lambda text: NewBlocks.SCL.replace('#speed := 1;', text)
        page = NewBlocks().html(code(before) if before else None, code(after), 'F', draw_added_removed=True)
        dom = _dom(page, self.MEASURE, query)
        return json.loads(unescape(re.search(r'data-layout="([^"]*)"', dom).group(1)))

    def test_a_long_line_folds_and_keeps_its_one_number(self):
        for query in ('?all', '?all&png'):                  # a page, and a shot
            got = self.layout(self.LONG + ' // 111', self.LONG + ' // 222', query)
            self.assertFalse(got['wide'], query)
            row, = got['rows']                              # one row of two sides, as it was one line
            for side in row.values():
                self.assertEqual(side['number'], '1', query)
                self.assertEqual(side['numberLines'], 1, query)
                self.assertGreater(side['codeLines'], 1, query)
                self.assertTrue(side['codeInside'], query)  # its end in view

    def test_a_long_line_folds_at_its_spaces(self):
        for query in ('?all', '?all&png'):
            row, = self.layout(self.LONG + ' // 111', self.LONG + ' // 222', query)['rows']
            for side, comment in (('before', ' // 111'), ('after', ' // 222')):
                folds = row[side]['codeFolds']
                self.assertGreater(len(folds), 1, query)
                self.assertEqual(''.join(folds), self.LONG + comment, query)
                for fold in folds[:-1]:
                    self.assertTrue(fold.endswith(' '), (query, folds))

    def test_a_line_with_no_space_to_break_at_breaks_inside_it_and_stays_in_its_cell(self):
        solid = '#' + 'word_1' * 60 + ';'
        for query in ('?all', '?all&png'):
            got = self.layout(solid + '//1', solid + '//2', query)
            self.assertFalse(got['wide'], query)
            row, = got['rows']
            for side, comment in (('before', '//1'), ('after', '//2')):
                self.assertGreater(row[side]['codeLines'], 1, query)
                self.assertTrue(row[side]['codeInside'], query)
                self.assertEqual(''.join(row[side]['codeFolds']), solid + comment, query)

    def test_a_run_of_spaces_at_a_fold_stays_in_its_cell(self):
        """Spaces are never marked, so a count that changed shows only as the spaces themselves."""
        run = 'a' * 60 + ' ' * 40 + 'b'
        for query in ('?all', '?all&png'):
            row, = self.layout('#x := ' + run + '1;', '#x := ' + run + '2;', query)['rows']
            for side in row.values():
                self.assertTrue(side['codeInside'], (query, side))

    def test_a_number_of_four_or_five_digits_stays_on_one_line_in_its_cell(self):
        for lines in (1000, 10000):
            code = '\n'.join(['#x := 1;'] * (lines - 1) + [self.LONG])
            rows = self.layout(None, code)['rows']
            self.assertEqual([r['after']['number'] for r in rows], [str(k + 1) for k in range(lines)])
            for r in rows:
                self.assertEqual(r['after']['numberLines'], 1, r)
                self.assertTrue(r['after']['numberInside'], r)
            self.assertGreater(rows[-1]['after']['codeLines'], 1)

    def test_it_folds_in_the_cell(self):
        """What the browser tests above see, for a machine with no browser."""
        td = re.search(r'\.ldiff table\.scl td\{([^{}]*)\}', CSS).group(1)
        self.assertIn('white-space:break-spaces', td)
        self.assertIn('overflow-wrap:anywhere', td)
        self.assertIn('word-break:normal', td)                # not a host page's
        self.assertNotIn('@media screen{.ldiff table.scl', CSS)

    def test_the_whole_line_is_in_the_page(self):
        text = NewBlocks.SCL.replace('#speed := 1;', self.LONG)
        html = NewBlocks().html(None, text, 'F', draw_added_removed=True)
        self.assertIn(self.LONG, unescape(re.sub(r'<[^>]+>', '', html)))


def rung_text(rungs):
    """The rungs as lines: 'b c > w1' is the rung of contacts #b, #c that ends at wire#w1; 'w0: b > w1' starts at wire#w0;
    '-w0' takes wire#w0 on the way; '!r' is coil #r; '^m' is P_Trig of edge memory #m; '@guard' is a call of #guard, '@guard:w5'
    with its pin inp on wire#w5."""
    text = ''
    for line in rungs:
        start, _, line = line.rpartition(': ')
        body, _, end = line.partition(' > ')
        text += '        RUNG wire#%s\n' % (start or 'powerrail')
        for name in body.split():
            if name[0] == '@':
                box, _, pin = name[1:].partition(':')
                text += '            #%s(\n%s                out1 => #q\n            )\n' % (
                    box, '                inp := wire#%s,\n' % pin if pin else '')
                continue
            text += '            %s\n' % ('wire#' + name[1:] if name[0] == '-' else
                                          'Coil( #%s )' % name[1:] if name[0] == '!' else
                                          'P_Trig( #%s )' % name[1:] if name[0] == '^' else 'Contact( #%s )' % name)
        text += '        END_RUNG%s\n' % (' wire#' + end if end else '')
    return text


def ladder(rungs, declared=''):
    """A block around the text of its rungs, every operand declared."""
    names = sorted(set(re.findall(r'(?:Contact|Coil|P_Trig)\( #(\w+) \)', rungs)) | {'a', 'q', 'r'})
    boxes = sorted(set(re.findall(r'#(\w+)\(\n', rungs)) - {'inst'})
    return ('FUNCTION_BLOCK "K"\n    VAR\n        ' + declared + ''.join('        %s : _.Guard;\n' % b for b in boxes)
            + ''.join('        %s : Bool;\n' % n for n in names)
            + '    END_VAR\n    { S7_Language := "LAD" }\n    NETWORK\n' + rungs + '    END_NETWORK\nEND_FUNCTION_BLOCK\n')


P2 = [('inp1', 'w1'), ('inp2', 'w2')]
P3 = P2 + [('inp3', 'w3')]


def call(pins, *rungs):
    """A block with a call that has a pin per (pin, wire) of pins, then the rungs, see rung_text."""
    text = ('        RUNG wire#powerrail\n            Contact( #a )\n            #inst(\n'
            + ''.join('                %s := wire#%s,\n' % p for p in pins)
            + '                out1 => #q\n            )\n            Coil( #r )\n        END_RUNG\n')
    return ladder(text + rung_text(rungs), 'inst : _.Drive;\n')


def marks(before, after):
    """({status: what has it, before side}, {the same, after side}, reordered): the operands, 'box' for a call."""
    p, lb, la = pair(before, after)
    sides = []
    for lay in (lb, la):
        side = {}
        for e in lay.g.elements.values():
            if p.lad.status[e.eid] != 'same':
                name = e.instance.lstrip('#') if e.instance else e.instr if e.kind == 'box' else e.operand().lstrip('#')
                side.setdefault(p.lad.status[e.eid], []).append('box' if e.kind == 'box' and e.instance == '#inst' else name)
        sides.append({s: sorted(names) for s, names in side.items()})
    return sides[0], sides[1], p.lad.reordered


class SwappedPinWires(unittest.TestCase):
    """Two pins of a call read each other's wire and nothing else changed: every element of both wires is marked
    moved, on both sides, and nothing that stayed: not the box, not what feeds both, not the wires of the other pins."""

    def moved(self, before, after, *names):
        marked = {'moved': sorted(names)}
        self.assertEqual(marks(before, after), (marked, marked, False))
        lad = pair(before, after)[0].lad
        for e, o in lad.other.items():
            self.assertEqual((lad.other[o.eid].eid, lad.pair[e], lad.status[e]), (e, lad.pair[o.eid], lad.status[o.eid]))

    def test_an_equal_contact_on_a_wire_that_stayed_is_not_marked(self):
        self.moved(call(P3, 'c > w1', 'c > w2', 'b > w3'), call(P3, 'b > w1', 'c > w2', 'c > w3'), 'b', 'c')

    def test_a_wire_equal_to_one_of_the_two_that_stayed_is_not_marked(self):
        self.moved(call(P3, 'f g f > w1', 'f e > w2', 'f e > w3'), call(P3, 'f e > w1', 'f e > w2', 'f g f > w3'),
                   'e', 'f', 'f', 'f', 'g')

    def test_a_stem_that_is_the_whole_of_one_wire(self):
        """One contact of its own on one side, none on the other: what feeds both is no contact of theirs."""
        self.moved(call(P2, 's -w0 > w1', 'w0: c > w2'), call(P2, 's -w0 > w2', 'w0: c > w1'), 'c')

    def tapped(self, *rungs):
        """A call whose own rung starts with #systemReady, then wire#w8, from where a branch may start."""
        return call(P2, *rungs).replace('Contact( #a )\n', 'Contact( #systemReady )\n            wire#w8\n').replace(
            '        a : Bool;\n', '        systemReady : Bool;\n')

    def with_other_rung(self, first, *rungs):
        """A call with pins on w1 and w2, then a rung of its own that goes on past wire#w9 to a coil: first, the contact
        or box that stands before the tap, then contact #z and coil #x."""
        rung = ('        RUNG wire#powerrail\n            Contact( #k )\n' + first + '            wire#w9\n'
                '            Contact( #z )\n            Coil( #x )\n        END_RUNG\n')
        return call(P2, *rungs).replace('    END_NETWORK', rung + '    END_NETWORK').replace(
            '        a : Bool;\n', '        a : Bool;\n        k : Bool;\n        z : Bool;\n        x : Bool;\n        other : _.Drive;\n')

    def test_a_contact_before_a_tap_on_a_rung_that_goes_on_to_a_coil_did_not_move(self):
        self.moved(self.with_other_rung('', 'w9: l > w1', 'd > w2'), self.with_other_rung('', 'w9: l > w2', 'd > w1'), 'd', 'l')

    def test_a_box_and_a_contact_before_a_tap_on_another_rung_did_not_move(self):
        box = '            #other(\n                out1 => #q\n            )\n'
        self.moved(self.with_other_rung(box, 'w9: l > w1', 'd > w2'), self.with_other_rung(box, 'w9: l > w2', 'd > w1'), 'd', 'l')

    def test_a_coil_before_a_tap_on_a_rung_that_goes_on_did_not_move(self):
        self.moved(self.with_other_rung('            Coil( #y )\n', 'w9: l > w1', 'd > w2').replace(
            '        k : Bool;\n', '        k : Bool;\n        y : Bool;\n'),
                   self.with_other_rung('            Coil( #y )\n', 'w9: l > w2', 'd > w1').replace(
            '        k : Bool;\n', '        k : Bool;\n        y : Bool;\n'), 'd', 'l')

    def test_a_call_on_a_wire_moves_with_it(self):
        self.moved(call(P2, 'doorClosed @guard > w1', 'remoteStart > w2'), call(P2, 'doorClosed @guard > w2', 'remoteStart > w1'),
                   'doorClosed', 'guard', 'remoteStart')

    def test_an_edge_on_a_wire_moves_with_it(self):
        self.moved(call(P2, 'startButton ^m > w1', 'remoteStart > w2'), call(P2, 'startButton ^m > w2', 'remoteStart > w1'),
                   'P_Trig', 'remoteStart', 'startButton')

    def test_a_coil_on_a_wire_moves_with_it(self):
        self.moved(call(P2, 'b !y > w1', 'd > w2'), call(P2, 'b !y > w2', 'd > w1'), 'b', 'd', 'y')

    def test_a_box_alone_on_a_wire_moves_with_it(self):
        self.moved(call(P2, '@guard > w1', 'd > w2'), call(P2, '@guard > w2', 'd > w1'), 'd', 'guard')

    def test_what_feeds_a_pin_of_a_call_on_a_wire_moves_with_it(self):
        self.moved(call(P2, 'b @guard:w5 > w1', 'c > w5', 'd > w2'), call(P2, 'b @guard:w5 > w2', 'c > w5', 'd > w1'),
                   'b', 'c', 'd', 'guard')

    def test_what_feeds_a_pin_of_a_call_before_a_tap_did_not_move(self):
        tail = ['k @guard:w5 -w9 z !x', 'c > w5']
        self.moved(call(P2, 'w9: l > w1', 'd > w2', *tail), call(P2, 'w9: l > w2', 'd > w1', *tail), 'd', 'l')

    def test_a_call_in_a_chain_after_the_two_pins_does_not_hold_their_wires_back(self):
        """The call of the two pins feeds a pin of the next: what feeds its pins still moves."""
        def text(one, two):
            return call(P2, 'b > %s' % one, 'd > %s' % two).replace(
                '            Coil( #r )\n', '            wire#w7\n            #next(\n                inp := wire#w7,\n'
                                            '                out1 => #q\n            )\n').replace(
                '        a : Bool;\n', '        a : Bool;\n        next : _.Guard;\n')
        self.moved(text('w1', 'w2'), text('w2', 'w1'), 'b', 'd')

    def own_rung_to_a_next_call(self, *rungs):
        """A call of the two pins whose own rung ends at a pin of the next call, the coil behind that."""
        text = rung_text(rungs + ('a @next:w7 !r',)).replace(
            '#inst(\n', '#inst(\n                inp1 := wire#w1,\n                inp2 := wire#w2,\n')
        return ladder(text, 'inst : _.Drive;\n')

    def test_the_contact_before_a_tap_on_a_rung_that_ends_at_the_next_calls_pin_did_not_move(self):
        self.moved(self.own_rung_to_a_next_call('s -w8 @inst > w7', 'w8: l > w1', 'd > w2'),
                   self.own_rung_to_a_next_call('s -w8 @inst > w7', 'w8: l > w2', 'd > w1'), 'd', 'l')

    def test_a_box_before_a_tap_on_a_rung_that_ends_at_the_next_calls_pin_did_not_move(self):
        self.moved(self.own_rung_to_a_next_call('k @g -w8 @inst > w7', 'w8: l > w1', 'd > w2'),
                   self.own_rung_to_a_next_call('k @g -w8 @inst > w7', 'w8: l > w2', 'd > w1'), 'd', 'l')

    def test_a_call_on_a_wire_with_a_tap_after_it_moves_with_it(self):
        """The tap goes to a pin that stayed: the call and what stands before it feed that pin too, as #mainsOn."""
        self.moved(call(P3, 'b @guard -w9 c > w1', 'w9: e > w3', 'd > w2'), call(P3, 'b @guard -w9 c > w2', 'w9: e > w3', 'd > w1'),
                   'b', 'c', 'd', 'guard')

    def test_the_contact_before_a_tap_on_the_calls_own_rung_did_not_move(self):
        self.moved(self.tapped('w8: l > w1', 'd > w2'), self.tapped('w8: l > w2', 'd > w1'), 'd', 'l')

    def test_the_contact_before_a_pin_tapped_straight_off_the_calls_own_rung_did_not_move(self):
        """#systemReady stays; the tap is a wire with nothing of its own, so the box shows that inp2 reads it now."""
        one = self.tapped('d > w2').replace('inp1 := wire#w1', 'inp1 := wire#w8')
        two = one.replace('inp1 := wire#w8', 'inp1 := wire#w2').replace('inp2 := wire#w2', 'inp2 := wire#w8')
        self.moved(one, two, 'box', 'd')

    def test_both_wires_are_marked_and_the_box_is_not(self):
        self.moved(call(P2, 'b c > w1', 'd > w2', 'e > w2'), call(P2, 'd > w1', 'e > w1', 'b c > w2'), 'b', 'c', 'd', 'e')

    def test_the_same_contact_on_both_wires_is_marked_on_both(self):
        self.moved(call(P2, 'b c > w1', 'd > w1', 'b > w2'), call(P2, 'b > w1', 'b c > w2', 'd > w2'), 'b', 'b', 'c', 'd')

    def test_the_wires_of_the_pins_between_them_are_not_marked(self):
        pins = [('inp%d' % n, 'w%d' % n) for n in (1, 2, 3, 4, 6)]
        stay = ['k > w1', 'l > w3', 'm -w7 n > w4', 'w7: o > w4']
        self.moved(call(pins, *stay, 'b > w2', 'c > w2', 'd e > w6'), call(pins, *stay, 'd e > w2', 'b > w6', 'c > w6'),
                   'b', 'c', 'd', 'e')

    def test_wires_with_branches_inside_are_marked_whole(self):
        one, two = ['b -w8 c > %s', 'w8: d > %s'], ['e -w9 f > %s', 'w9: g h > %s']
        self.moved(call(P3, *[r % 'w1' for r in one], 'k > w3', *[r % 'w2' for r in two]),
                   call(P3, *[r % 'w1' for r in two], 'k > w3', *[r % 'w2' for r in one]),
                   'b', 'c', 'd', 'e', 'f', 'g', 'h')

    def test_a_stem_that_feeds_both_stayed(self):
        self.moved(call(P2, 's t -w0 b > w1', 'w0: d e > w2'), call(P2, 's t -w0 b > w2', 'w0: d e > w1'), 'b', 'd', 'e')

    def test_a_stem_with_one_contact_on_each_wire_is_a_swap(self):
        """What the two wires share is what feeds both, no contact of their own alike."""
        self.moved(call(P2, 's -w0 b > w1', 'w0: d > w2'), call(P2, 's -w0 b > w2', 'w0: d > w1'), 'b', 'd')

    def test_a_stem_that_also_feeds_a_pin_that_stayed_goes_with_its_wire(self):
        self.moved(call(P3, 's -w0 b > w1', 'w0: e > w3', 'd > w2'), call(P3, 's -w0 b > w2', 'w0: e > w3', 'd > w1'),
                   'b', 'd', 's')

    def test_a_wire_that_is_a_tap_of_a_rung_going_on_marks_the_box(self):
        """#s stays before its tap, so that wire has no element of its own: the box shows that inp2 reads it now."""
        swapped = [('inp1', 'w2'), ('inp2', 'w1')]
        self.assertEqual(marks(call(P2, 's -w1 !x', 'd > w2'), call(swapped, 's -w1 !x', 'd > w2')),
                         ({'moved': ['box', 'd']}, {'moved': ['box', 'd']}, False))

    def test_a_wire_whose_contact_also_feeds_a_call_that_stays_marks_the_box(self):
        """#b also feeds #other, whose rung goes on past a tap: it stays, and the box shows the swap (the coordinator,
        2026-11-04)."""
        swapped = [('inp1', 'w2'), ('inp2', 'w1'), ('inp3', 'w3')]
        rungs = ('k @other:w1 -w9 z !x', 'w9: l > w3', 'b > w1', 'd > w2')
        self.assertEqual(marks(call(P3, *rungs), call(swapped, *rungs)),
                         ({'moved': ['box', 'd']}, {'moved': ['box', 'd']}, False))

    def test_pins_of_two_calls_that_read_each_others_wire(self):
        one = ('            #%s(\n                inp1 := wire#%s,\n                out1 => #q\n            )\n')
        text = ('        RUNG wire#powerrail\n            Contact( #a )\n' + one % ('one', 'w1') + one % ('two', 'w2')
                + '        END_RUNG\n' + rung_text(['%s > w1', '%s > w2']))
        declared = 'one : _.Drive;\n        two : _.Drive;\n'
        self.moved(ladder(text % ('b', 'c'), declared), ladder(text % ('c', 'b'), declared), 'b', 'c')


class NotAPlainSwap(unittest.TestCase):
    """Everything but a plain swap of two wires is not told as one. Most of these keep the marks they had before;
    those that hid a change or marked what stayed are read anew (_reconnected): the fewest elements that leave
    every node a partner, with the wires they end whole beside another change."""

    def same(self, before, after, marked_b, marked_a=None):
        self.assertEqual(marks(before, after), (marked_b, marked_b if marked_a is None else marked_a, False))

    def test_a_contact_deleted_beside_an_equal_branch(self):
        plain = lambda *rungs: ladder(rung_text(rungs + ('w1: !q',)))
        self.same(plain('d > w1', 'c b > w1', 'b > w1'), plain('d > w1', 'b > w1', 'b > w1'), {'removed': ['c']}, {})

    def test_a_contact_deleted_and_one_added_beside_an_equal_branch(self):
        plain = lambda *rungs: ladder(rung_text(rungs + ('w1: !q',)))
        self.same(plain('b > w1', 'b c > w1'), plain('x b > w1', 'b > w1'), {'removed': ['c']}, {'added': ['x']})

    def test_a_contact_deleted_on_a_wire_with_an_equal_contact_on_the_next(self):
        self.same(call(P2, 'i b > w1', 'b > w2'), call(P2, 'b > w1', 'b > w2'), {'removed': ['i']}, {})

    def test_a_contact_deleted_before_two_equal_on_the_next_wire(self):
        self.same(call(P2, 'i b c > w1', 'b c > w2'), call(P2, 'b c > w1', 'b c > w2'), {'removed': ['i']}, {})

    def test_a_branch_added_equal_to_those_on_the_wires(self):
        self.same(call(P2, 'c > w1', 'c > w2'), call(P2, 'c > w1', 'c > w1', 'c > w2'), {}, {'added': ['c']})

    def test_a_contact_moved_along_a_rung_with_equal_contacts(self):
        self.same(ladder(rung_text(['d -w1 d -w2 d -w3 c !r', 'b > w1', 'd > w2', 'w1: c > w3'])),
                  ladder(rung_text(['c -w1 d -w2 d -w3 !r', 'b > w1', 'd d > w2', 'w1: c > w3'])), {'moved': ['c', 'c', 'd']})

    def test_a_coil_moved_past_a_contact(self):
        self.same(ladder(rung_text(['a !q s !r'])), ladder(rung_text(['a s !q !r'])), {'moved': ['q', 's']})

    def test_a_contact_moved_and_one_added_on_a_rung_with_no_call(self):
        self.same(ladder(rung_text(['a s t !r'])), ladder(rung_text(['s a n t !r'])),
                  {'moved': ['a', 's']}, {'added': ['n'], 'moved': ['a', 's']})

    # a place that moved, not a pin: the network without its pins is another
    def test_a_branch_taken_off_a_stem(self):
        self.same(call(P2, 's t -w8 x > w1', 'w8: y z > w2'), call(P2, 's t x > w1', 'y z > w2'), {'moved': ['y']})

    def test_a_branch_put_on_a_stem(self):
        self.same(call(P2, 's t x > w1', 'y z > w2'), call(P2, 's t -w8 x > w1', 'w8: y z > w2'), {'moved': ['y']})

    def test_a_tap_moved_past_a_contact(self):
        """#x stands before the tap now, or the tap after #x: both hold; the rung of #x reads otherwise."""
        self.same(call(P2, 's -w8 x > w1', 'w8: y > w2'), call(P2, 's x -w8 > w1', 'w8: y > w2'), {'moved': ['x']})

    def test_the_start_of_a_branch_moved_onto_a_contact(self):
        self.same(call(P3, 'd b > w1', 'b e > w2', 'd > w3'), call(P3, 'd -w8 b > w1', 'w8: b e > w2', 'd > w3'),
                  {'moved': ['b']})

    # two wires that differ by one contact: that contact moved, the smaller reading
    def test_one_contact_between_wires_otherwise_alike(self):
        self.same(call(P2, 'p q c > w1', 'p q > w2'), call(P2, 'p q > w1', 'p q c > w2'), {'moved': ['c']})

    def test_one_contact_each_between_wires_otherwise_alike(self):
        self.same(call(P2, 'p q b > w1', 'p q c > w2'), call(P2, 'p q c > w1', 'p q b > w2'), {'moved': ['b', 'c']})

    def test_an_edge_between_wires_otherwise_alike(self):
        self.same(call(P2, 'p q ^m > w1', 'p q > w2'), call(P2, 'p q > w1', 'p q ^m > w2'), {'moved': ['P_Trig']})

    def test_a_call_between_wires_otherwise_alike(self):
        self.same(call(P2, 'p q @guard > w1', 'p q > w2'), call(P2, 'p q > w1', 'p q @guard > w2'), {'moved': ['guard']})

    def test_one_contact_to_a_wire_of_one_contact(self):
        self.same(call(P2, 'c > w1', 'c e > w2'), call(P2, 'e c > w1', 'c > w2'), {'moved': ['e']})

    # not the two wires alone, or not exchanged whole
    def test_a_swap_and_a_type_setting_changed(self):
        """Told on the elements themselves: a .s7dcl writes no such setting, a SimaticML export of an OB does."""
        p, _, _ = pair(call(P2, 'x -w8 y z > w1', 'w8: u v > w1', 'd > w2'), call(P2, 'd > w1', 'x -w8 y z > w2', 'w8: u v > w2'))
        for rungs, setting in ((p.before.rungs, 'Int'), (p.after.rungs, 'DInt')):
            for rung in rungs:
                for item in rung.items:
                    if not isinstance(item, tuple) and item.operand() == '#z':
                        item.more = {'SrcType': setting}
        lad = NetDiff(Graph(p.before.rungs), Graph(p.after.rungs))
        marked = {e.operand(): s for e, s in ((lad.b.elements[k], s) for k, s in lad.status.items() if k in lad.b.elements)
                  if s != 'same'}
        self.assertEqual(marked['#z'], 'changed')

    def test_two_pins_that_hold_what_the_other_held_on_other_wires(self):
        """inp2 reads the third wire, equal to the first: no exchange of the two wires."""
        pins = [('inp1', 'w1'), ('inp2', 'w2'), ('inp3', 'w3'), ('inp4', 'w1')]
        other = [('inp1', 'w2'), ('inp2', 'w3'), ('inp3', 'w3'), ('inp4', 'w1')]
        self.same(call(pins, 'b > w1', 'd > w2', 'b > w3'), call(other, 'b > w1', 'd > w2', 'b > w3'), {'moved': ['box']})

    def test_one_contact_apart_with_a_stem_that_also_feeds_a_third_pin(self):
        """#c changed pins (inp1 to inp2) and the lone #s with it (its rung ends at w1 now, not w2); the stem #s goes with
        the wire of #c, as it also feeds inp3, which stayed (the maintainer's stem rule, as with a distinct #t: c, s, t).
        #e stayed: its rung reads the same, and inp3 reads s and e before and after."""
        self.same(call(P3, 's -w0 c > w1', 'w0: e > w3', 's > w2'), call(P3, 's -w0 c > w2', 'w0: e > w3', 's > w1'),
                  {'moved': ['c', 's', 's']})

    def test_two_contacts_exchanged_between_wires(self):
        """The two that changed wires, not #r, which stayed."""
        self.same(call(P2, 'p > w1', 'q r > w2'), call(P2, 'q > w1', 'p r > w2'), {'moved': ['p', 'q']})

    def test_wires_holding_the_same_contacts(self):
        """#c of the first wire goes parallel and #c of the second into series: two marks, as the code before _reconnected
        gave, and as true a reading as #b, #c. The rungs tie by the paired elements in the rungs before them,
        which read #c twice."""
        self.same(call(P2, 'b c > w1', 'b > w2', 'c > w2'), call(P2, 'b > w1', 'c > w1', 'b c > w2'), {'moved': ['c', 'c']})

    def test_two_swaps(self):
        pins = P3 + [('inp4', 'w4')]
        self.same(call(pins, 'b > w1', 'c > w2', 'd > w3', 'e > w4'), call(pins, 'c > w1', 'b > w2', 'e > w3', 'd > w4'),
                  {'moved': ['b', 'c', 'd', 'e']})

    def test_three_pins_round(self):
        self.same(call(P3, 'b > w1', 'c > w2', 'd > w3'), call(P3, 'd > w1', 'b > w2', 'c > w3'), {'moved': ['b', 'c', 'd']})

    def test_one_pin_to_another_wire(self):
        self.same(call(P2, 'b > w1', 'c > w2'), call([('inp1', 'w2'), ('inp2', 'w2')], 'b > w1', 'c > w2'), {'moved': ['box']})

    # a swap and something else
    def test_a_swap_and_a_contact_moved(self):
        self.same(call(P3, 'b > w1', 'c > w2', 'm x > w3', 'y > w3'), call(P3, 'c > w1', 'b > w2', 'm > w3', 'y x > w3'),
                  {'moved': ['b', 'c', 'x']})

    def test_a_swap_and_an_operand(self):
        self.same(call(P3, 'b c > w1', 'd > w2', 'e > w2', 'z > w3'), call(P3, 'd > w1', 'e > w1', 'b c > w2', 'zz > w3'),
                  {'changed': ['z'], 'moved': ['b', 'c', 'd', 'e']}, {'changed': ['zz'], 'moved': ['b', 'c', 'd', 'e']})

    def test_a_swap_and_an_operand_that_the_search_for_merged_nodes_tries_without(self):
        """With the changed contact taken out each try is a plain swap: no try is told as one. Equal contacts allow more
        readings than the swap; the marks show both wires. Which copies of #d and #e carry them is a tie of equal
        contacts, 13 marks either way: those that left their rung, with the wires they move whole."""
        pins = P3 + [('inp4', 'w4'), ('inp5', 'w5')]
        stay = ['b d c > w1', 'c e c > w1', 'd > w1', 'd > w2', 'e e > w2']
        moved = ['b', 'b', 'b', 'b', 'c', 'c', 'c', 'd', 'd', 'd', 'd', 'e', 'e']
        self.same(call(pins, *stay, 'e > w3', 'c d b > w3', 'c d b > w3', 'b b > w4', 'b b d > w5', 'e e b > w5', 'd c e > w5'),
                  call(pins, *stay, 'e > w5', 'c d b > w5', 'c d bz > w5', 'b b > w4', 'b b d > w3', 'e e b > w3', 'd c e > w3'),
                  {'removed': ['b'], 'moved': moved}, {'added': ['bz'], 'moved': moved})

    def test_a_swap_and_a_contact_added(self):
        self.same(call(P2, 'b -w8 c > w1', 'w8: d > w1', 'e f > w2'), call(P2, 'e f > w1', 'b -w8 c > w2', 'w8: d n > w2'),
                  {'moved': ['b', 'c', 'd', 'e', 'f']}, {'added': ['n'], 'moved': ['b', 'c', 'd', 'e', 'f']})

    def test_a_swap_and_a_contact_removed(self):
        self.same(call(P3, 'b c > w1', 'd > w1', 'b > w2', 'z > w3'), call(P3, 'b > w1', 'b > w2', 'd > w2', 'z > w3'),
                  {'moved': ['d'], 'removed': ['c']}, {'moved': ['d']})

    def test_a_swap_and_a_contact_added_with_the_same_contact_on_both(self):
        """#c and #d to the other wire, the two #b where they were: the fewest moved."""
        self.same(call(P2, 'b c > w1', 'd > w1', 'b > w2'), call(P2, 'b > w1', 'b c n > w2', 'd > w2'),
                  {'moved': ['c', 'd']}, {'added': ['n'], 'moved': ['c', 'd']})

    def test_a_swap_and_a_contact_moved_with_the_same_contact_on_a_third_wire(self):
        """#x went from the #b branch to the #y branch: marked, and no #b."""
        self.same(call(P3, 'b c > w1', 'b > w2', 'b x > w3', 'y > w3'), call(P3, 'b > w1', 'b c > w2', 'b > w3', 'y x > w3'),
                  {'moved': ['c', 'x']})

    def test_a_pin_renamed(self):
        self.same(call([('inp1', 'w1')], 'b > w1'), call([('start', 'w1')], 'b > w1'), {'changed': ['box']})

    def test_a_swap_and_a_pin_renamed(self):
        renamed = [('start', 'w1'), ('inp2', 'w2'), ('inp3', 'w3')]
        self.same(call(P3, 'b > w1', 'c d > w2', 'e > w2', 'k > w3'), call(renamed, 'c d > w1', 'e > w1', 'b > w2', 'k > w3'),
                  {'changed': ['box'], 'moved': ['b', 'c', 'd', 'e']})

    def writes(self, text, one, two):
        """A block of call(): its call writes wire#w8 and wire#w9, which end in coils #x and #y, by out1 and out2."""
        return (text.replace('                out1 => #q\n', '                out1 => wire#%s,\n                out2 => wire#%s\n' % (one, two))
                .replace('        q : Bool;\n', '        q : Bool;\n        x : Bool;\n        y : Bool;\n')
                .replace('    END_NETWORK', rung_text(['w8: !x', 'w9: !y']) + '    END_NETWORK'))

    def test_output_wires_that_swap(self):
        self.same(self.writes(call(P2, 'b > w1', 'c > w2'), 'w8', 'w9'), self.writes(call(P2, 'b > w1', 'c > w2'), 'w9', 'w8'),
                  {'moved': ['box']})

    def test_output_wires_that_swap_beside_a_swap(self):
        self.same(self.writes(call(P2, 'b > w1', 'c > w2'), 'w8', 'w9'), self.writes(call(P2, 'c > w1', 'b > w2'), 'w9', 'w8'),
                  {'moved': ['b', 'box', 'c']})


class ConnectionsBesideAnotherChange(unittest.TestCase):
    """A connection that changed beside another change in the network is marked too: before, any other change
    turned the reading of connections off, and only the drawings showed the rewiring."""

    def same(self, before, after, marked_b, marked_a=None):
        self.assertEqual(marks(before, after), (marked_b, marked_b if marked_a is None else marked_a, False))

    PIN_TO_W2 = [('inp1', 'w2'), ('inp2', 'w2'), ('inp3', 'w3')]

    def test_a_pin_to_another_wire_beside_an_operand(self):
        self.same(call(P3, 'b > w1', 'c > w2', 'z > w3'), call(self.PIN_TO_W2, 'b > w1', 'c > w2', 'zz > w3'),
                  {'changed': ['z'], 'moved': ['box']}, {'changed': ['zz'], 'moved': ['box']})

    def test_a_pin_to_another_wire_beside_a_contact_moved(self):
        self.same(call(P3, 'b > w1', 'c > w2', 'm x > w3', 'y > w3'),
                  call(self.PIN_TO_W2, 'b > w1', 'c > w2', 'm > w3', 'y x > w3'), {'moved': ['box', 'x']})

    def test_two_contacts_exchanged_beside_an_operand(self):
        self.same(call(P3, 'p > w1', 'q r > w2', 'z > w3'), call(P3, 'q > w1', 'p r > w2', 'zz > w3'),
                  {'changed': ['z'], 'moved': ['p', 'q']}, {'changed': ['zz'], 'moved': ['p', 'q']})

    def test_two_contacts_exchanged_beside_one_added_on_their_wire(self):
        """#r keeps its place on its rung: the two that changed wires are marked, not #r."""
        self.same(call(P2, 'p > w1', 'q r > w2'), call(P2, 'q n > w1', 'p r > w2'), {'moved': ['p', 'q']},
                  {'added': ['n'], 'moved': ['p', 'q']})

    def test_two_contacts_exchanged_beside_one_changed_on_their_wire(self):
        self.same(call(P2, 'p t > w1', 'q r > w2'), call(P2, 'q tz > w1', 'p r > w2'),
                  {'changed': ['t'], 'moved': ['p', 'q']}, {'changed': ['tz'], 'moved': ['p', 'q']})

    def test_two_contacts_exchanged_beside_one_removed_after_the_one_that_stayed(self):
        """#r keeps its place: not marked."""
        self.same(call(P2, 'p > w1', 'q r m > w2'), call(P2, 'q > w1', 'p r > w2'), {'moved': ['p', 'q'], 'removed': ['m']},
                  {'moved': ['p', 'q']})

    def test_two_contacts_exchanged_beside_one_added_after_the_one_that_stayed(self):
        self.same(call(P2, 'p > w1', 'q r > w2'), call(P2, 'q > w1', 'p r m > w2'), {'moved': ['p', 'q']},
                  {'added': ['m'], 'moved': ['p', 'q']})

    def test_a_stem_that_also_feeds_a_pin_that_stayed_goes_with_its_wire_beside_another_change(self):
        """As the same swap alone (SwappedPinWires, as the maintainer chose): one rewiring reads one way."""
        swapped = [('inp1', 'w2'), ('inp2', 'w1'), ('inp3', 'w3')]
        self.same(call(P3, 'g -w0 c > w1', 'w0: e > w3', 'd > w2', 'y !q'),
                  call(swapped, 'g -w0 c > w1', 'w0: e > w3', 'd > w2', 'yz !q'),
                  {'changed': ['y'], 'moved': ['c', 'd', 'g']}, {'changed': ['yz'], 'moved': ['c', 'd', 'g']})

    def test_a_try_of_merge_reads_the_type_setting_after_the_connections(self):
        """A try (merge=False) marks as without _reconnected: #r moved, then changed by its other setting."""
        p, _, _ = pair(call(P2, 'p > w1', 'q r > w2'), call(P2, 'q > w1', 'p r > w2'))
        for rungs, setting in ((p.before.rungs, 'Bool'), (p.after.rungs, 'Int')):
            for rung in rungs:
                for item in rung.items:
                    if not isinstance(item, tuple) and item.operand() == '#r':
                        item.more = {'type': setting}
        lad = NetDiff(Graph(p.before.rungs), Graph(p.after.rungs), merge=False)
        marked = sorted((lad.b.elements[k].operand(), s) for k, s in lad.status.items()
                        if k in lad.b.elements and s != 'same' and lad.b.elements[k].kind != 'box')
        self.assertEqual(marked, [('#r', 'changed'), ('#r', 'moved')])

    def test_a_swap_whose_wire_holds_a_changed_contact_is_marked_whole(self):
        """#b stands before the changed #c: it moves with its wire."""
        self.same(call(P2, 'b c d > w1', 'e f > w2'), call(P2, 'e f > w1', 'b cz d > w2'),
                  {'changed': ['c'], 'moved': ['b', 'd', 'e', 'f']}, {'changed': ['cz'], 'moved': ['b', 'd', 'e', 'f']})

    def test_equal_contacts_paired_otherwise_end(self):
        """Exchanging the partners of equal contacts moved the statuses the search counts: it ran without end."""
        self.same(call(P3, 'b c > w1', 'd > w2', 'b > w2', 'e c > w2', 'f b g > w3'),
                  call(P3, 'd > w1', 'b > w1', 'e c > w1', 'b c b > w2', 'f g > w3'),
                  {'moved': ['b', 'b', 'b', 'c', 'c', 'd', 'e']})


class TheBoxBesideAnotherChange(unittest.TestCase):
    """A swapped wire with nothing of its own marks the box beside another change as alone (SwappedPinWires): one rewiring
    reads one way. Each shape beside an operand changed and beside a contact added on
    a rung of its own."""

    SWAPPED = [('inp1', 'w2'), ('inp2', 'w1'), ('inp3', 'w3')]
    BESIDE = {'operand': (('y !t',), ('yz !t',), {'changed': ['y']}, {'changed': ['yz']}),
              'contact added': (('y !t',), ('y n !t',), {}, {'added': ['n']})}

    def beside(self, before, after, *marked):
        for name, (was, now, mark_b, mark_a) in self.BESIDE.items():
            with self.subTest(beside=name):
                got = marks(before(*was), after(*now))
                self.assertEqual(got, ({**mark_b, 'moved': sorted(marked)}, {**mark_a, 'moved': sorted(marked)}, False))

    def test_a_tap_of_a_rung_going_on(self):
        rungs = ('s -w1 !x', 'd > w2')
        self.beside(lambda *more: call(P2, *rungs, *more), lambda *more: call(self.SWAPPED[:2], *rungs, *more), 'box', 'd')

    def test_a_tap_between_contacts_of_a_rung_going_on(self):
        rungs = ('s t -w1 t2 !x', 'd > w2')
        self.beside(lambda *more: call(P2, *rungs, *more), lambda *more: call(self.SWAPPED[:2], *rungs, *more), 'box', 'd')

    def test_a_contact_that_also_feeds_a_call_that_stays(self):
        rungs = ('k @other:w1 -w9 z !x', 'w9: l > w3', 'b > w1', 'd > w2')
        self.beside(lambda *more: call(P3, *rungs, *more), lambda *more: call(self.SWAPPED, *rungs, *more), 'box', 'd')

    def test_a_tap_straight_off_the_calls_own_rung(self):
        def text(pins, *more):
            return SwappedPinWires().tapped('d > w2', *more).replace('inp1 := wire#w1', 'inp1 := wire#w8') if pins == 1 else \
                SwappedPinWires().tapped('d > w2', *more).replace('inp1 := wire#w1', 'inp1 := wire#w2').replace(
                    'inp2 := wire#w2', 'inp2 := wire#w8')
        self.beside(lambda *more: text(1, *more), lambda *more: text(2, *more), 'box', 'd')


class OneReadingBesideAnotherChange(unittest.TestCase):
    """A rewiring reads as alone beside another change on a rung of its own: the elements
    that left their rung settle a tie there too. A rung printed as two, or two as one, the halves next to each other, is
    the same logic and no change."""

    BESIDE = {'alone': ((), (), {}, {}),
              'operand': (('y !t',), ('yz !t',), {'changed': ['y']}, {'changed': ['yz']}),
              'contact added': (('y !t',), ('y n !t',), {}, {'added': ['n']}),
              'contact removed': (('y n !t',), ('y !t',), {'removed': ['n']}, {}),
              'coil changed': (('y !t',), ('y !tz',), {'changed': ['t']}, {'changed': ['tz']}),
              'rung added': ((), ('n !t',), {}, {'added': ['n', 't']}),
              'rung removed': (('n !t',), (), {'removed': ['n', 't']}, {}),
              'rung printed split': (('h j !q',), ('h > w77', 'w77: j !q'), {}, {}),
              'rungs printed joined': (('h > w77', 'w77: j !q'), ('h j !q',), {}, {}),
              'split, operand': (('h j !q',), ('h > w77', 'w77: jz !q'), {'changed': ['j']}, {'changed': ['jz']}),
              'split, larger half first': (('h j jj !q',), ('h j > w77', 'w77: jj !q'), {}, {}),
              'split, half of three first': (('h j jj jk !q',), ('h j jj > w77', 'w77: jk !q'), {}, {}),
              'joined, larger half first': (('h j > w77', 'w77: jj !q'), ('h j jj !q',), {}, {})}

    def reads(self, pins_b, rungs_b, pins_a, rungs_a, *moved):
        self.reads_in(lambda more, first: call(pins_b, *(more + rungs_b if first else rungs_b + more)),
                      lambda more, first: call(pins_a, *(more + rungs_a if first else rungs_a + more)), *moved)

    def reads_in(self, before, after, *moved):
        """before(more, first), after(more, first): the texts with the rungs of the other change, first or last."""
        for name, (was, now, mark_b, mark_a) in self.BESIDE.items():
            for first in (False, True) if was or now else (False,):
                with self.subTest(beside=name, first=first):
                    got = marks(before(tuple(was), first), after(tuple(now), first))
                    self.assertEqual(got, ({**mark_b, 'moved': sorted(moved)}, {**mark_a, 'moved': sorted(moved)}, False))

    def test_two_contacts_exchanged_between_a_branch_and_the_rail(self):
        """#a1 stays where it was and still feeds #xa and the branch: not marked, though taking it out alone would join
        the branch to the rail."""
        self.plain(['a1 -w5 !xa', 'w5: d -w6 !x', 'e > w6'], ['a1 -w5 !xa', 'w5: e -w6 !x', 'd > w6'], 'd', 'e')

    def test_a_stem_that_also_feeds_a_box_pin_goes_with_its_wire(self):
        """#v feeds the pin of #g, which stays, and through #m inp1: it goes with the wire, as the maintainer chose for a
        stem, alone and beside another change."""
        rungs = ('k @g:w5 !xa', 'w5: m > w1', 'c > w2', 'v > w5')
        self.reads(P2, rungs, [('inp1', 'w2'), ('inp2', 'w1')], rungs, 'c', 'm', 'v')

    def plain(self, before, after, *moved):
        self.reads_in(lambda more, first: ladder(rung_text(list(more) + before if first else before + list(more))),
                      lambda more, first: ladder(rung_text(list(more) + after if first else after + list(more))), *moved)

    def test_two_contacts_exchanged_between_two_coils(self):
        """With a rung of the other change first, as last."""
        self.plain(['b !x', 'c !y'], ['c !x', 'b !y'], 'b', 'c')

    def test_a_contact_moved_on_a_third_wire_beside_one_moved_between_wires(self):
        self.reads(P3, ('b c > w1', 'b > w2', 'b x > w3', 'v > w3'), P3, ('b > w1', 'b c > w2', 'b > w3', 'v x > w3'), 'c', 'x')

    def test_a_contact_to_the_rung_of_another_coil(self):
        """#b, not #a1 and #c, which stayed."""
        self.plain(['a1 !xa', 'b c !x'], ['b a1 !xa', 'c !x'], 'b')

    def test_a_contact_off_a_branch_onto_the_rung(self):
        self.plain(['a1 -w5 b c -w6 !xa', 'e f > w6'], ['e a1 -w5 b c -w6 !xa', 'f > w6'], 'e')

    def test_two_contacts_to_the_rungs_of_other_coils(self):
        self.plain(['a1 !xa', 'c d !xb', 'b !x'], ['b a1 !xa', 'd !xb', 'c !x'], 'b', 'c')

    def test_a_contact_onto_a_branch_reads_one_way(self):
        """#a1 onto the branch of #e: alone as beside a change."""
        self.plain(['a1 b -w5 !xa', 'e > w5'], ['b -w5 !xa', 'a1 e > w5'], 'a1')

    def test_two_contacts_exchanged_between_coil_rungs_that_both_change(self):
        """#a1 and #b #c changed rungs: they are marked, not the coils' other contacts."""
        self.plain(['a1 !xa', 'b c -w5 d !x', 'e > w5'], ['b c !xa', 'a1 -w5 d !x', 'e > w5'], 'a1', 'b', 'c')

    def test_contacts_exchanged_between_a_branch_and_the_rail_whatever_the_text(self):
        """The rule stands without the text of #a1's rung: another wire number, the branch written on its rung, its coil
        changed."""
        self.plain(['a1 -w5 !xa', 'w5: d -w6 !x', 'e > w6'], ['a1 -w4 !xa', 'w4: e -w6 !x', 'd > w6'], 'd', 'e')
        self.plain(['a1 -w5 d -w6 !x', 'w5: !xa', 'e > w6'], ['a1 -w5 e -w6 !x', 'w5: !xa', 'd > w6'], 'd', 'e')
        before, after = ['a1 -w5 !xa', 'w5: d -w6 !x', 'e > w6'], ['a1 -w5 !xb', 'w5: e -w6 !x', 'd > w6']
        for name, (was, now, mark_b, mark_a) in self.BESIDE.items():
            for first in (False, True):
                with self.subTest(beside=name, first=first):
                    got = marks(ladder(rung_text(list(was) + before if first else before + list(was))),
                                ladder(rung_text(list(now) + after if first else after + list(now))))
                    want = [{**mark, 'moved': ['d', 'e'], 'changed': sorted(mark.get('changed', []) + [coil])}
                            for mark, coil in ((mark_b, 'xa'), (mark_a, 'xb'))]
                    self.assertEqual(got, (*want, False))

    def test_a_contact_to_the_other_pins_branch_leaves_the_stem(self):
        """#m moves between the ORs of two pins; no wire moves whole, so #v, which feeds both, stays."""
        self.reads(P2, ('k @g:w5 !xa', 'w5: m > w1', 'b > w1', 'c > w2', 'v > w5'), P2,
                   ('k @g:w5 !xa', 'w5: m > w2', 'b > w1', 'c > w2', 'v > w5'), 'm')

    def test_a_contact_off_a_coil_rung_onto_a_swapped_wire(self):
        """#c left the rung of coil #x for the wire that inp2 reads now."""
        self.reads(P3, ('c d -w2 !x', 'e f > w3', 'b > w1'), [('inp1', 'w1'), ('inp2', 'w3'), ('inp3', 'w2')],
                   ('d -w2 !x', 'c e f > w3', 'b > w1'), 'c', 'd', 'e', 'f', 'x')

    def test_a_contact_onto_a_coil_rung_beside_a_swap(self):
        """#f, now on the rung of coil #x, and the box for the tap that inp2 reads now."""
        self.reads(P3, ('d e > w2', 'b -w1 c !x', 'f g > w3'), [('inp1', 'w2'), ('inp2', 'w1'), ('inp3', 'w3')],
                   ('d e > w2', 'f b -w1 c !x', 'g > w3'), 'box', 'd', 'e', 'f')

    def test_a_swap_beside_a_contact_removed_where_equal_contacts_take_other_partners(self):
        """The elements that left their rung are read before equal ones take other partners, one of them the contact
        removed: the reading kept an element with no partner and the search crashed (a generated case)."""
        pins = P3 + [('inp4', 'w4')]
        before = ('b > w1', 'b > w1', 'c > w1', 'd b e > w2', 'd > w3', 'd > w3', 'f > w3', 'e > w4')
        after = ('b > w1', 'b > w1', 'c > w1', 'd > w2', 'd > w2', 'f > w2', 'b e > w3', 'e > w4')
        moved = ['b', 'd', 'd', 'e', 'f']
        self.assertEqual(marks(call(pins, *before), call(pins, *after)),
                         ({'removed': ['d'], 'moved': moved}, {'moved': moved}, False))

    def test_two_contacts_exchanged_between_coil_rungs(self):
        self.reads(P2, ('b > w1', 'c > w2', 'd !xa', 'e !x'), P2, ('b > w1', 'c > w2', 'e !xa', 'd !x'), 'd', 'e')

    def test_two_contacts_exchanged_between_the_branches_of_an_or_on_a_pin(self):
        """#c5 and #c7, as on an OR that ends at a coil: they still feed inp2, so no wire moved whole and #c6 stays."""
        self.reads(P2, ('c6 c7 > w2', 'c5 > w2', 'b > w1'), P2, ('c6 c5 > w2', 'c7 > w2', 'b > w1'), 'c5', 'c7')
        self.reads(P2, ('c2 c3 c4 > w2', 'c5 > w2', 'b > w1'), P2, ('c2 c3 c5 > w2', 'c4 > w2', 'b > w1'), 'c4', 'c5')

    def test_a_contact_off_a_tap_onto_the_rung_of_a_call_that_reads_the_tap(self):
        """#c1 alone: taken out, its two ends meet in both versions, the links of each end going to the other's
        (#c1 off the tap of #c2 onto the rung of the call that reads the tap); the #c2 of the
        call's rung, equal to the other, stayed."""
        self.plain(['c1 -w5 c2 !x1', 'c2 @g:w5 !x2'], ['-w5 c2 !x1', 'c1 c2 @g:w5 !x2'], 'c1')

    def test_two_contacts_off_taps_onto_the_rungs_of_calls_that_read_them(self):
        """#c1 and #c4, the shape above twice: both start at the rail, which reaches other nodes too;
        #c6 stayed. The two halves in either order."""
        one = ['c1 -w5 c2 !x1', 'c3 @g:w5 !x2'], ['-w5 c2 !x1', 'c1 c3 @g:w5 !x2']
        two = ['c4 -w6 c5 !x3', 'c6 @h:w6 !x4'], ['-w6 c5 !x3', 'c4 c6 @h:w6 !x4']
        for (b1, a1), (b2, a2) in ((one, two), (two, one)):
            with self.subTest(first=b1[0]):
                self.plain(b1 + b2, a1 + a2, 'c1', 'c4')

    def test_coils_exchanged_beside_a_rung_printed_as_two_halves_apart(self):
        """#b and #c, as without the split: the halves hold the rung's elements alone, so they stand for it wherever
        they are printed."""
        for before, after in ((['p q r !s', 'b !x', 'c !y'], ['p q > w9', 'c !x', 'b !y', 'w9: r !s']),
                              (['p q r !s', 'b !x', 'c !y'], ['p q > w9', 'c !x', 'w9: r !s', 'b !y']),
                              (['p q r !s', 'b !x', 'c !y'], ['p q r !s', 'c !x', 'b !y']),
                              (['h j jj !q', 'b !x', 'c !y', 'k0 !k1'], ['h j > w77', 'c !x', 'b !y', 'k0 !k1', 'w77: jj !q']),
                              (['h j > w77', 'b !x', 'c !y', 'w77: jj !q'], ['h j jj !q', 'c !x', 'b !y'])):
            with self.subTest(after=after):
                self.assertEqual(marks(ladder(rung_text(before)), ladder(rung_text(after))),
                                 ({'moved': ['b', 'c']}, {'moved': ['b', 'c']}, False))

    def test_contacts_exchanged_in_the_or_of_a_pin_on_a_rung_printed_as_two(self):
        """#c5 and #c7, as without the split: #c6 feeds inp2 as before and what ends where it starts is #hh still,
        though its number in its rung changed."""
        whole, split = ('hh c6 c7 > w2', 'c5 > w2', 'b > w1'), ('hh > w9', 'w9: c6 c7 > w2', 'c5 > w2', 'b > w1')
        exchanged = ('hh c6 c5 > w2', 'c7 > w2', 'b > w1')
        exchanged_split = ('hh > w9', 'w9: c6 c5 > w2', 'c7 > w2', 'b > w1')
        for before, after in ((whole, exchanged_split), (split, exchanged), (split, exchanged_split)):
            with self.subTest(before=before, after=after):
                self.assertEqual(marks(call(P2, *before), call(P2, *after)),
                                 ({'moved': ['c5', 'c7']}, {'moved': ['c5', 'c7']}, False))

    def test_two_contacts_exchanged_between_a_pin_and_a_tap_beside_one_moved_onto_a_pin(self):
        """#c1, #c12 and #c13, as the text shows: #c12 stands before a tap that a call reads, but it moved, so the box
        does not stand in for it."""
        self.reads(P2, ('c1 > w1', 'c7 > w2', 'c12 -w6 c13 !x3', 'c14 @g6:w6 !x4'),
                   P2, ('c12 > w1', 'c7 c13 > w2', 'c1 -w6 !x3', 'c14 @g6:w6 !x4'), 'c1', 'c12', 'c13')

    def test_two_contacts_off_taps_beside_a_rung_printed_as_two(self):
        """#c1 and #c4 beside a rung printed as two whose first half stands before the shape: the rung pairs with that
        half in the order of the rungs, the nearer by place."""
        b = ['c1 -w5 c2 !x1', 'c3 @g:w5 !x2', 'c4 -w6 c5 !x3', 'c6 @h:w6 !x4']
        a = ['-w5 c2 !x1', 'c1 c3 @g:w5 !x2', '-w6 c5 !x3', 'c4 c6 @h:w6 !x4']
        whole, split = ['zh zj zjj !zq', 'zk0 !zk1'], ['zh zj > w87', 'zk0 !zk1', 'w87: zjj !zq']
        for before, after in ((whole + b, split + a), (whole[:1] + b + whole[1:], split[:1] + a + split[1:])):
            with self.subTest(after=after):
                self.plain(before, after, 'c1', 'c4')

    def test_a_contact_exchanged_with_a_run_of_the_stem(self):
        """#c5, #c6, #c8 and #c9: the run #c6 #c9 left the stem for inp2's OR, and #c5 took its place on the stem, so #c6
        feeds inp1 no more."""
        self.reads(P2, ('c5 > w2', 'c6 c9 -w5 c7 > w1', 'w5: c8 > w2'), P2, ('c6 c9 > w2', 'c5 -w5 c7 > w1', 'w5: c8 > w2'),
                   'c5', 'c6', 'c8', 'c9')

    def test_a_contact_off_the_head_of_one_stem_onto_the_head_of_another(self):
        """#c6 alone: it left the head of one stem for the head of another that feeds the same pins. The stems printed
        whole or as two rungs."""
        for before, after in ((('c6 -w5 c7 > w1', 'w5: c8 > w2', 'c9 -w6 c10 > w1', 'w6: c11 > w2'),
                               ('-w5 c7 > w1', 'w5: c8 > w2', 'c6 c9 -w6 c10 > w1', 'w6: c11 > w2')),
                              (('c6 > w5', 'w5: c7 > w1', 'w5: c8 > w2', 'c9 -w6 c10 > w1', 'w6: c11 > w2'),
                               ('-w5 c7 > w1', 'w5: c8 > w2', 'c6 c9 > w6', 'w6: c10 > w1', 'w6: c11 > w2'))):
            with self.subTest(before=before):
                self.reads(P2, before, P2, after, 'c6')

    def test_a_run_or_a_contact_off_the_head_of_one_stem_with_the_stems_printed_as_two(self):
        """The run #c6 #c7 off the head of one stem onto the head of another that feeds the same pins: #c6 and #c7, each
        stem printed whole or as two rungs, before and after alike or not. #c6 from gating only the inner stem of a
        nested stem to gating the whole nested stem, and back: #c6, the whole nested stem printed whole or as two rungs."""
        heads = (('c6 c7 -w5 c8 > w1', 'w5: c9 > w2'), ('c6 c7 > w5', 'w5: c8 > w1', 'w5: c9 > w2'))
        other = (('c10 -w6 c11 > w1', 'w6: c12 > w2'), ('c10 > w6', 'w6: c11 > w1', 'w6: c12 > w2'))
        onto = (('c6 c7 c10 -w6 c11 > w1', 'w6: c12 > w2'), ('c6 c7 c10 > w6', 'w6: c11 > w1', 'w6: c12 > w2'))
        for b in (0, 1):
            for a in (0, 1):
                with self.subTest(before=b, after=a):
                    self.reads(P2, heads[b] + other[b], P2, ('-w5 c8 > w1', 'w5: c9 > w2') + onto[a], 'c6', 'c7')
        inner = ('-w5 c7 > w1', 'w5: c8 > w2', 'w5: c6 c9 -w6 c10 > w1', 'w6: c11 > w2')
        for whole in (('c6 -w5 c7 > w1', 'w5: c8 > w2', 'w5: c9 -w6 c10 > w1', 'w6: c11 > w2'),
                      ('c6 > w5', 'w5: c7 > w1', 'w5: c8 > w2', 'w5: c9 > w6', 'w6: c10 > w1', 'w6: c11 > w2')):
            for before, after in ((inner, whole), (whole, inner)):
                with self.subTest(before=before, after=after):
                    self.reads(P2, before, P2, after, 'c6')

    def test_a_call_that_reads_the_other_contact_with_its_wires_renumbered(self):
        """The wires are renumbered and the call's pins read the same logic; only #g reads #c now in place of #b. A
        pin's wire name tells nothing."""
        self.reads(P2, ('b > w1', 'c > w2', 'k @g:w1 !xa'), [('inp1', 'w2'), ('inp2', 'w1')],
                   ('b > w2', 'c > w1', 'k @g:w1 !xa'), 'g')

    def test_two_pins_exchanged_beside_a_call_on_one_of_the_wires(self):
        """The wires' elements, as a plain swap marks them; #g reads #b before and after, so neither it nor the box."""
        rungs = ('b > w1', 'c > w2', 'k @g:w1 !xa')
        self.reads(P2, rungs, [('inp1', 'w2'), ('inp2', 'w1')], rungs, 'b', 'c')

    def test_two_calls_of_one_instance_that_exchange_their_wires(self):
        """As a plain swap of two calls' pins marks it: the wires' elements."""
        self.reads(P2, ('b > w1', 'c > w2', 'k @g:w1 !xa', 'm @g:w2 !xb'), P2,
                   ('b > w1', 'c > w2', 'k @g:w2 !xa', 'm @g:w1 !xb'), 'b', 'c')

    def test_the_pins_of_the_one_contact_apart_stem_shape_exchanged(self):
        """The same logic as the rung ends exchanged (NotAPlainSwap): #c, the lone #s and the stem #s with the wire of #c;
        #e stayed, inp3 reads s and e before and after."""
        rungs = ('s -w0 c > w1', 'w0: e > w3', 's > w2')
        self.reads(P3, rungs, [('inp1', 'w2'), ('inp2', 'w1'), ('inp3', 'w3')], rungs, 'c', 's', 's')

    def test_one_contact_apart_with_a_lone_rung_of_two(self):
        """#c and #u changed pins; the lone #s goes with #u's wire and the stem #s with the wire of #c, as #t would with a
        distinct #t (the maintainer's stem rule): as text and as pins exchanged, alone and beside."""
        self.reads(P3, ('s -w0 c > w1', 'w0: e > w3', 's u > w2'), P3, ('s -w0 c > w2', 'w0: e > w3', 's u > w1'),
                   'c', 's', 's', 'u')
        rungs = ('s -w0 c > w1', 'w0: e > w3', 's u > w2')
        self.reads(P3, rungs, [('inp1', 'w2'), ('inp2', 'w1'), ('inp3', 'w3')], rungs, 'c', 's', 's', 'u')


class ContactsOffTheStemAtTheRail(unittest.TestCase):
    """A contact or a run that left the stem at the rail for the branch of its tap reads as its movers alone, and beside
    a rung added or removed. Beside a change on a rung that starts at the rail in both versions (an operand, a contact
    added, a rung printed as two) it does not: the rail then reaches that rung, and taking out what left the stem no
    longer joins the rail to its other end."""

    def test_contacts_off_the_stem_at_the_rail_onto_its_branch(self):
        """Alone, the movers: with no other rung at the rail, taking out what left the stem joins the rail to its other
        end, where the branch goes on in both versions; #x1 stayed. #c1 off the stem beside #c3 from the branch onto the
        rung of #x1, #c4 there too, a contact added or removed on the branch; the run #c1 #c2 off the stem onto the end
        of the branch, #c4 on the rung of #x1 or not, #c3 staying."""
        for before, after, moved in (
                (['c1 -w5 !x1', 'w5: c2 c3 !x2'], ['-w5 c3 !x1', 'w5: c1 c2 !x2'], {'moved': ['c1', 'c3']}),
                (['c1 -w5 c4 !x1', 'w5: c2 c3 !x2'], ['-w5 c3 c4 !x1', 'w5: c1 c2 !x2'], {'moved': ['c1', 'c3']}),
                (['c1 c2 -w5 !x1', 'w5: c3 !x2'], ['-w5 !x1', 'w5: c3 c1 c2 !x2'], {'moved': ['c1', 'c2']}),
                (['c1 c2 -w5 c4 !x1', 'w5: c3 !x2'], ['-w5 c4 !x1', 'w5: c3 c1 c2 !x2'], {'moved': ['c1', 'c2']})):
            with self.subTest(after=after):
                self.assertEqual(marks(ladder(rung_text(before)), ladder(rung_text(after))), (moved, moved, False))
        self.assertEqual(marks(ladder(rung_text(['c1 -w5 !x1', 'w5: c2 c3 !x2'])),
                               ladder(rung_text(['-w5 c3 !x1', 'w5: c1 c9 c2 !x2']))),
                         ({'moved': ['c1', 'c3']}, {'moved': ['c1', 'c3'], 'added': ['c9']}, False))
        self.assertEqual(marks(ladder(rung_text(['c1 -w5 !x1', 'w5: c2 c9 c3 !x2'])),
                               ladder(rung_text(['-w5 c3 !x1', 'w5: c1 c2 !x2']))),
                         ({'moved': ['c1', 'c3'], 'removed': ['c9']}, {'moved': ['c1', 'c3']}, False))


class OneInstanceCalledTwice(unittest.TestCase):
    """One FB instance called by two rungs of a network, which TIA allows: equal boxes."""

    def test_one_call_removed_beside_contacts_exchanged(self):
        """The pairs of the boxes change in the search for the reading: the report crashed.
        #b and #c exchanged wires, and coil #xb is on the rung of #k now."""
        got = marks(call(P2, 'b > w1', 'c > w2', 'k @g:w1 !xa', 'm @g:w1 !xb'),
                    call(P2, 'c > w1', 'b > w2', 'k @g:w1 !xb', 'n !t'))
        self.assertEqual((got[0]['moved'], got[1]['moved']), (['b', 'c', 'xb'], ['b', 'c', 'xb']))

    def test_two_calls_removed(self):
        """Two exchanges of partners tried at once shared an element and left it with none: the report crashed.
        Two calls of #g and their rungs go, #m's and the one whose tap fed #d, which stands
        on the rail now."""
        rungs = ('v > w5', 'u > w2', 'b > w1')
        self.assertEqual(marks(call(P2, 'k @g:w5 !xa', 'm @g:w5 !xb', 'k @g:w5 -w6 !xa', 'w6: d > w2', *rungs),
                               call(P2, 'k @g:w5 !xa', 'd > w2', *rungs)),
                         ({'removed': ['g', 'g', 'k', 'm', 'xa', 'xb'], 'moved': ['d']}, {'moved': ['d']}, False))


class TheSearchForMergedNodes(unittest.TestCase):
    """A network with an element taken out is told like any other: it crashed on a list of rungs that still held it."""

    def test_a_contact_moved_and_one_deleted_with_no_call(self):
        self.assertEqual(marks(ladder(rung_text(['e > w1', 'c e > w1', 'w1: !q'])), ladder(rung_text(['e c > w1', 'w1: !q']))),
                         ({'moved': ['c'], 'removed': ['e']}, {'moved': ['c']}, False))

    def test_a_contact_deleted_on_a_wire_of_a_call(self):
        self.assertEqual(marks(call(P2, 'b > w1', 'b c > w2', 'c b c > w2'), call(P2, 'b > w1', 'b c > w2', 'c b > w2')),
                         ({'moved': ['b'], 'removed': ['c']}, {'moved': ['b']}, False))

    OR_THEN_AUTO = ['@b1 -w1 auto @b4', '@b2 > w1', '@b3 > w1']
    RUNGS_OF_THEIR_OWN = ['@b1', '@b2', '@b3', 'auto @b4']

    def test_what_stood_after_an_or_moved_to_a_rung_of_its_own(self):
        """A box of the OR taken out joins the rail and the end of the rungs: they are never one node, so the box does
        not tell it all (a real commit with ENOs of three Moves)."""
        moved = {'moved': ['auto', 'b4']}
        self.assertEqual(marks(ladder(rung_text(self.OR_THEN_AUTO)), ladder(rung_text(self.RUNGS_OF_THEIR_OWN))),
                         (moved, moved, False))

    def test_what_stood_after_an_or_moved_back_behind_it(self):
        moved = {'moved': ['auto', 'b4']}
        self.assertEqual(marks(ladder(rung_text(self.RUNGS_OF_THEIR_OWN)), ladder(rung_text(self.OR_THEN_AUTO))),
                         (moved, moved, False))

    def test_a_run_as_long_as_the_or_moved_to_a_rung_of_its_own(self):
        """Three elements of one run against three branches: a tie, and #b1 kept its place, so the run is marked. It moves
        only whole, so the search tries each run as one."""
        before, after = ['@b1 -w1 auto x !y', '@b2 > w1', '@b3 > w1'], ['@b1', '@b2', '@b3', 'auto x !y']
        moved = {'moved': ['auto', 'x', 'y']}
        for b, a in ((before, after), (after, before)):
            self.assertEqual(marks(ladder(rung_text(b)), ladder(rung_text(a))), (moved, moved, False))

    def test_what_stood_after_an_or_of_two_contacts_moved_to_a_rung_of_its_own(self):
        moved = {'moved': ['auto', 'y']}
        self.assertEqual(marks(ladder(rung_text(['p1 -w1 auto !y', 'p2 > w1'])), ladder(rung_text(['p1', 'p2', 'auto !y']))),
                         (moved, moved, False))


if __name__ == '__main__':
    unittest.main()
