"""Instructions drawn as TIA's LAD help draws them (ProgKOP2MenUS: the page of each instruction, named in the
test). The forms are the ones real exports hold, the names made up. From the repo root:
python -m unittest discover -s TiaChangeReports/tests -t .
"""
import re
import unittest

from TiaChangeReports import render_lad
from TiaChangeReports.compare import compare_blocks
from TiaChangeReports.page import render
from TiaChangeReports.render_lad import Layout
from TiaChangeReports.s7dcl import Element, parse_block
from TiaChangeReports.source import BlockSource
from TiaChangeReports.verify import check

from . import test_change_reports as cr

BLOCK = '''FUNCTION_BLOCK "Sample"
    VAR
        a : Bool;
        m : Bool;
        n : Bool;
        i : Int;
        d : DInt;
        r : Real;
        lo : Int;
        hi : Int;
        q : Bool;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
%s
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''


def source(element, name='Sample'):
    return BlockSource(name, BLOCK % element, None, name + '.s7dcl')


def element_view(element):
    """The view of the last element on the rung, read from the export's text."""
    b = parse_block(source(element))
    net = b.networks[0]
    lay = Layout(net.rungs, b.interface, None, net.label)
    return lay, lay.views[net.rungs[0].items[-1].eid]


def texts(svg):
    return [(float(x), float(y), s) for x, y, s in
            re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)</text>', svg)]


def drawn(view, y=100):
    """The texts of an element, as (x, y, text); one without a text would be an empty string here."""
    return texts(''.join(view.draw(0, y)))


def strings(view):
    return [s for _, _, s in drawn(view)]


def type_cells(view):
    """(left, right) of the type cells of a box drawn at x 0."""
    return [(float(x), float(x) + float(w)) for x, w in
            re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="[\d.]+" fill="%s" stroke' % render_lad.C_BOXHEAD,
                       ''.join(view.draw(0, 100)))]


def pane(before, after, k=-1):
    """(texts, marks as (x, y, width, height)) of one pane of the one changed network of two versions of an element."""
    return pane_of(source(before), source(after), k)


def pane_of(before, after, k=-1):
    """As pane, of two versions of a block."""
    d = compare_blocks(before, after)
    (p,) = d.nets
    svg = re.findall(r'<div class="pane">.*?</svg>', render([d], 'b', 'a'), re.S)[k]
    marks = [tuple(float(v) for v in m) for m in
             re.findall(r'<rect class="hl [^"]*" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg)]
    return texts(svg), marks, p


def marked(marks, found, s):
    """Whether a diff mark lies under the one text s."""
    ((x, y),) = [(x, y) for x, y, t in found if t == s]
    return any(mx <= x <= mx + w and my <= y <= my + h for mx, my, w, h in marks)


def xml_element(part, rung, operands, templates=()):
    """A network of one part as a SimaticML export writes it. Operands: 21 #start, 22 #stop, 23 #big, 24 #latch."""
    n = cr.NegatedPins('test_taken_away')
    inner = ''.join('<TemplateValue Name="%s" Type="Type">%s</TemplateValue>' % t for t in templates)
    text = n.net('<Part Name="%s" UId="25">%s</Part>' % (part, inner),
                 ['<Powerrail /><NameCon UId="25" Name="%s" />' % rung] + [n.op(uid, 25, pin) for pin, uid in operands], 'LAD')
    b = parse_block(cr._xml_src(text))
    net = b.networks[0]
    lay = Layout(net.rungs, b.interface, None, net.label)
    return lay.views[net.rungs[0].items[-1].eid]


def xml_edge(*wires):
    """A PBox of a SimaticML export, its pins in the order of the wires: (pin, operand uid), the rung's pins without one
    fed from the rail or open. Operands: 21 #start, 22 #stop, 23 #big, 24 #latch."""
    n = cr.NegatedPins('test_taken_away')
    pins = [p for p, _ in wires]
    rail = ['<Powerrail /><NameCon UId="25" Name="in" />'] if 'in' not in pins else []
    return cr._xml_src(n.net('<Part Name="PBox" UId="25" />', rail + [n.op(uid, 25, pin) for pin, uid in wires], 'LAD'))


def view_of(src):
    b = parse_block(src)
    net = b.networks[0]
    lay = Layout(net.rungs, b.interface, None, net.label)
    (v,) = [v for v in lay.views.values() if v.el.instr == 'P_Trig']
    return v


class Inverter(unittest.TestCase):
    """--|NOT|-- (10867188619.htm): NOT between the two bars, clear of them."""

    @staticmethod
    def geometry(v):
        """(left bar, right bar, left of the text, right of the text) of the inverter drawn at x 0."""
        svg = ''.join(v.draw(0, 100))
        bars = sorted(float(a) for a, b in re.findall(r'<line x1="([\d.]+)" y1="[\d.]+" x2="([\d.]+)" y2="[\d.]+"[^>]*stroke-width="1.6"', svg))
        x, size, text = re.search(r'<text x="([\d.]+)"[^>]*font-size="(\d+)"[^>]*>([^<]*)</text>', svg).groups()
        half = render_lad.tw(text, int(size), True) / 2
        return bars[0], bars[-1], float(x) - half, float(x) + half

    def test_the_text_is_clear_of_the_bars(self):
        _, v = element_view('            Not()')
        left, right, start, end = self.geometry(v)
        self.assertGreaterEqual(start - left, 2)
        self.assertGreaterEqual(right - end, 2)

    def test_from_a_simaticml_export(self):
        n = cr.NegatedPins('test_taken_away')
        text = n.net('<Part Name="Not" UId="25" />', ['<Powerrail /><NameCon UId="25" Name="in" />'], 'LAD')
        b = parse_block(cr._xml_src(text))
        v = Layout(b.networks[0].rungs, b.interface, None, b.networks[0].label).views[b.networks[0].rungs[0].items[-1].eid]
        left, right, start, end = self.geometry(v)
        self.assertGreaterEqual(start - left, 2)
        self.assertGreaterEqual(right - end, 2)

    def test_a_mark_on_it_covers_the_text(self):
        _, v = element_view('            Not()')
        ((_, x, _, w, _),) = v.marks(0, 100, 'changed', {'#instr'})
        _, _, start, end = self.geometry(v)
        self.assertLess(x, start)
        self.assertGreater(x + w, end)

    def test_a_contact_keeps_its_width(self):
        _, v = element_view('            Contact( #q )')
        svg = ''.join(v.draw(0, 100))
        bars = sorted(float(a) for a in re.findall(r'<line x1="([\d.]+)" y1="[\d.]+" x2="[\d.]+" y2="[\d.]+"[^>]*stroke-width="1.6"', svg))
        self.assertEqual(bars[-1] - bars[0], 12)


class EdgeBoxes(unittest.TestCase):
    """P_TRIG, N_TRIG (10867193099.htm, 10867192459.htm): CLK and Q on the rung, the edge memory below the box."""

    def test_clk_and_q_are_the_rungs_pins_and_nothing_else_is_named(self):
        for instr, title in (('P_Trig', 'P_TRIG'), ('N_Trig', 'N_TRIG')):
            _, v = element_view('            %s( #m )' % instr)
            self.assertEqual(sorted(strings(v)), sorted([title, 'CLK', 'Q', '#m']), instr)

    def test_the_edge_memory_is_below_the_box(self):
        lay, v = element_view('            P_Trig( #m )')
        found = {s: y for _, y, s in drawn(v)}
        box = re.search(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)"', ''.join(v.draw(0, 100)))
        bottom = float(box.group(1)) + float(box.group(2))
        self.assertGreater(found['#m'] - 8, bottom)              # the top of its letters clear of the box
        self.assertGreaterEqual(100 + v.below, found['#m'])      # and inside the row
        self.assertEqual(check(lay), [])

    def test_a_long_edge_memory_stays_inside_the_row(self):
        _, v = element_view('            P_Trig( #%s )' % '_'.join(['a_long_name'] * 8))
        self.assertGreater(len(v.under), 1)
        self.assertGreaterEqual(100 + v.below, max(y for _, y, _ in drawn(v)))

    def test_a_changed_edge_memory_is_marked_there_and_the_head_is_not(self):
        found, marks, p = pane('            P_Trig( #m )', '            P_Trig( #n )')
        self.assertEqual(p.state, 'changed')
        self.assertTrue(marked(marks, found, '#n'))
        self.assertFalse(marked(marks, found, 'P_TRIG'))

    def test_from_a_simaticml_export(self):
        v = xml_element('PBox', 'in', [('bit', 22)])
        self.assertEqual(sorted(strings(v)), sorted(['P_TRIG', 'CLK', 'Q', '#stop']))

    def test_the_edge_memory_is_found_by_its_name_in_either_wire_order(self):
        for other in ('in', 'out'):
            for wires in (((other, 21), ('bit', 22)), (('bit', 22), (other, 21))):
                v = view_of(xml_edge(*wires))
                self.assertEqual([s for s, _, _ in v.under], ['#stop'], wires)
                self.assertIn('#start', strings(v), wires)              # at a pin of its own, above the box's bottom
                self.assertEqual(sorted(n for n, _ in v.lefts + v.rights if n == 'BIT'), [], wires)
                found = {s: y for _, y, s in drawn(v)}
                self.assertLess(found['#start'], found['#stop'], wires)

    def test_a_changed_operand_on_the_rungs_pin_is_not_marked_as_the_edge_memory(self):
        for wires in ((('in', 21), ('bit', 22)), (('bit', 22), ('in', 21))):
            def version(uid):
                return xml_edge(*[(p, uid if p == 'in' else u) for p, u in wires])
            found, marks, _ = pane_of(version(21), version(23))
            self.assertTrue(marked(marks, found, '#big'), wires)
            self.assertFalse(marked(marks, found, '#stop'), wires)
            at = {s: y for _, y, s in found}
            self.assertLess(at['#big'], at['#stop'], wires)         # at its pin, the edge memory below the box

    def test_a_changed_edge_memory_beside_an_operand_on_the_rungs_pin_is_marked_below(self):
        for wires in (lambda b: (('in', 21), ('bit', b)), lambda b: (('bit', b), ('in', 21))):
            found, marks, _ = pane_of(xml_edge(*wires(22)), xml_edge(*wires(23)))
            self.assertTrue(marked(marks, found, '#big'))
            self.assertFalse(marked(marks, found, '#start'))
            at = {s: y for _, y, s in found}
            self.assertGreater(at['#big'], at['#start'])            # below the box, the other operand at its pin

    def test_the_names_of_the_edge_memory(self):
        for params in ('#m', 'bit := #m', 'operand := #m'):
            _, v = element_view('            P_Trig( %s )' % params)
            self.assertEqual([s for s, _, _ in v.under], ['#m'], params)
            self.assertEqual([n for n, _ in v.lefts], ['CLK'], params)

    def test_a_bit_fed_by_logic_keeps_its_wire(self):
        el = Element('e', 'P_Trig', None, [('bit', ':=', 'wire#w1')], {})
        v = render_lad.View(el, parse_block(source('')).interface)
        self.assertEqual(v.under, [])
        self.assertEqual(list(v.wirepins.values()), [('bit', 'w1')])

    def test_a_parameter_of_another_name_is_a_pin_and_stays_drawn(self):
        _, v = element_view('            P_Trig( other := #m )')
        self.assertEqual(v.under, [])
        self.assertEqual(sorted(strings(v)), sorted(['P_TRIG', 'CLK', 'OTHER', '#m', 'Q']))


class RangeBoxes(unittest.TestCase):
    """IN_RANGE, OUT_RANGE (10152307467.htm, 10152308235.htm): the rung runs through the box, no EN / ENO, pins MIN, VAL,
    MAX, the type under the title."""

    ELEMENT = '''            { S7_Templates := "[SrcType := Int]" }
            %s(
                min := #lo,
                in := #i,
                max := #hi
            )'''

    def test_title_and_pins(self):
        for instr, title in (('InRange', 'IN_RANGE'), ('OutRange', 'OUT_RANGE')):
            _, v = element_view(self.ELEMENT % instr)
            self.assertEqual(sorted(strings(v)), sorted([title, 'Int', 'MIN', 'VAL', 'MAX', '#lo', '#i', '#hi']), instr)

    def test_val_is_next_to_its_operand_between_min_and_max(self):
        _, v = element_view(self.ELEMENT % 'InRange')
        found = {s: y for _, y, s in drawn(v)}
        self.assertLess(found['MIN'], found['VAL'])
        self.assertLess(found['VAL'], found['MAX'])
        self.assertEqual(found['VAL'], found['#i'])

    def test_a_changed_operand_at_val_is_marked(self):
        found, marks, _ = pane(self.ELEMENT % 'InRange', (self.ELEMENT % 'InRange').replace('in := #i', 'in := #hi'))
        ((vx, vy),) = [(x, y) for x, y, s in found if s == 'VAL']
        self.assertTrue(any(mx + w <= vx and my <= vy <= my + h for mx, my, w, h in marks))   # its operand, left of the pin


class TypeCells(unittest.TestCase):
    """CONV (11262686347.htm), ROUND (41306940811.htm), NORM_X (10152494859.htm): 'Src to Dest', a cell for each type."""

    @staticmethod
    def conv(instr='Convert', types='SrcType := Int, DestType := DInt'):
        return '''            { S7_Templates := "[%s]" }
            %s(
                in := #i,
                out => #d
            )''' % (types, instr)

    def test_conv_is_titled_conv_and_reads_src_to_dest(self):
        _, v = element_view(self.conv())
        self.assertEqual(strings(v)[:4], ['CONV', 'Int', 'to', 'DInt'])

    def test_the_title_and_the_form_of_others(self):
        for instr, title in (('Round', 'ROUND'), ('Normalize', 'NORM_X')):
            _, v = element_view(self.conv(instr, 'SrcType := Real, DestType := Int'))
            self.assertEqual(strings(v)[:4], [title, 'Real', 'to', 'Int'], instr)

    def test_the_source_type_comes_first_whatever_the_order_in_the_export(self):
        _, v = element_view(self.conv(types='DestType := DInt, SrcType := Int'))
        self.assertEqual(strings(v)[1:4], ['Int', 'to', 'DInt'])

    def test_each_type_has_its_own_cell_and_to_has_none(self):
        _, v = element_view(self.conv())
        cells = type_cells(v)
        at = {s: x for x, _, s in drawn(v)}
        self.assertEqual(len(cells), 2)
        self.assertTrue(cells[0][0] < at['Int'] < cells[0][1])
        self.assertTrue(cells[1][0] < at['DInt'] < cells[1][1])
        self.assertTrue(cells[0][1] < at['to'] < cells[1][0])

    def test_a_box_is_wide_enough_for_long_type_names(self):
        _, v = element_view(self.conv(types='SrcType := Date_And_Time, DestType := LTime_Of_Day'))
        (first, _), (_, last) = type_cells(v)
        self.assertGreaterEqual(first, v.lw)
        self.assertLessEqual(last, v.lw + v.bw)

    def test_another_type_marks_the_head(self):
        found, marks, _ = pane(self.conv(), self.conv(types='SrcType := Int, DestType := Real'))
        self.assertTrue(marked(marks, found, 'Real'))
        self.assertFalse(marked(marks, found, '#i'))

    def test_a_convert_of_a_simaticml_export(self):
        v = xml_element('Convert', 'en', [('in', 21), ('out', 22)], (('SrcType', 'Int'), ('DestType', 'DInt')))
        self.assertEqual(strings(v)[:4], ['CONV', 'Int', 'to', 'DInt'])
        self.assertEqual(sorted(strings(v)[4:]), sorted(['EN', 'IN', '#start', 'ENO', 'OUT', '#stop']))

    def test_another_template_beside_the_two_types_stays_drawn(self):
        for other in ('A', 'B'):
            _, v = element_view(self.conv(types='SrcType := Int, DestType := DInt, Other := %s' % other))
            self.assertEqual(strings(v)[:2], ['CONV', 'Int, DInt, %s' % other])
            self.assertNotIn('to', strings(v))

    def test_a_change_of_that_template_is_drawn_and_marked(self):
        a, b = (self.conv(types='SrcType := Int, DestType := DInt, Other := %s' % o) for o in 'AB')
        for k, text in ((0, 'Int, DInt, A'), (1, 'Int, DInt, B')):
            found, marks, _ = pane(a, b, k)
            self.assertTrue(marked(marks, found, text), text)

    def test_a_switch_relation_does_not_count_as_another_template(self):
        el = Element('e', 'Convert', None, [], {'SrcType': 'Int', 'DestType': 'DInt', 'CASE0': '=='})
        v = render_lad.View(el, parse_block(source('')).interface)
        self.assertEqual(strings(v)[:4], ['CONV', 'Int', 'to', 'DInt'])

    def test_one_type_alone_stays_as_it_is(self):
        _, v = element_view(self.conv(types='SrcType := Int'))
        self.assertEqual(strings(v)[:2], ['CONV', 'Int'])
        self.assertNotIn('to', strings(v))

    def test_a_box_of_one_type_has_no_to(self):
        _, v = element_view('''            { S7_Templates := "[SrcType := Int]" }
            Add(
                in1 := #i,
                in2 := #i,
                out => #i
            )''')
        self.assertEqual(strings(v)[:2], ['ADD', 'Int'])
        self.assertNotIn('to', strings(v))

    def test_expt_joins_its_types_with_the_power(self):
        """EXPT (10152322571.htm): IN1 of DestType, IN2 of SrcType, 'REAL ** INT'; IN1 is converted against DestType."""
        _, v = element_view('''            { S7_Templates := "[DestType := Real, SrcType := Int]" }
            Expt(
                in1 := #r,
                in2 := #i,
                out => #r
            )''')
        self.assertEqual(strings(v)[1:4], ['Real', '**', 'Int'])
        self.assertEqual(v.conv, set())


class Titles(unittest.TestCase):
    """Titles other than the instruction's name in capitals: ROR, ROL (10748281611.htm, 10748282379.htm), MOVE_BLK,
    UMOVE_BLK (10214305931.htm, 10214308491.htm), FILL_BLK, UFILL_BLK (10208210571.htm, 10152345867.htm), SCALE_X
    (10152492299.htm), GET_ERROR, GET_ERR_ID (15972277899.htm, 15972278667.htm), ?= (99834219019.htm). The names are the element library's, no
    real export holds them yet."""

    def title(self, instr):
        return render_lad.View(Element('e', instr, None, [], {}), parse_block(source('')).interface).title

    def test_the_title_from_the_help(self):
        for instr, title in (('Ror', 'ROR'), ('Rol', 'ROL'), ('MoveBlockI', 'MOVE_BLK'), ('MoveBlockU', 'UMOVE_BLK'),
                             ('FillBlockI', 'FILL_BLK'), ('FillBlockU', 'UFILL_BLK'), ('Scale', 'SCALE_X'),
                             ('GetError', 'GET_ERROR'), ('GetErrorID', 'GET_ERR_ID'), ('AssignAttempt', '?=')):
            self.assertEqual(self.title(instr), title, instr)

    def test_the_legacy_scale_keeps_its_own_title(self):
        self.assertEqual(self.title('SCALE'), 'SCALE')


class ReturnCoils(unittest.TestCase):
    """--(RET) (11586178955.htm): RET in the coil, the return value above: FALSE in its drawing, RLO in the drawing of the
    S7-300 page (20291480331.htm) and the safety page (InstrFAILenUS 16876036107.htm)."""

    def test_the_text_in_the_coil_and_the_value_above(self):
        for instr, value in (('Return()', 'RLO'), ('ReturnTrue()', 'TRUE'), ('ReturnFalse()', 'FALSE'), ('ReturnCoil( #q )', '#q')):
            _, v = element_view('            ' + instr)
            found = {s: y for _, y, s in drawn(v)}
            self.assertEqual(sorted(found), sorted(['RET', value]), instr)
            self.assertLess(found[value], found['RET'], instr)
            self.assertGreaterEqual(found[value] - 10, 100 - v.above, instr)

    def test_an_operand_is_drawn_whatever_the_return_coil(self):
        for instr in ('Return', 'ReturnTrue', 'ReturnFalse'):
            _, v = element_view('            %s( #q )' % instr)
            found = {s: y for _, y, s in drawn(v)}
            self.assertEqual(sorted(found), sorted(['RET', '#q']), instr)
            self.assertLess(found['#q'], found['RET'], instr)

    def test_a_changed_operand_of_a_return_coil_is_marked_on_it(self):
        for instr in ('Return', 'ReturnTrue', 'ReturnFalse'):
            a, b = '            %s( #q )' % instr, '            %s( #m )' % instr
            for k, text in ((0, '#q'), (1, '#m')):
                found, marks, _ = pane(a, b, k)
                self.assertTrue(marked(marks, found, text), (instr, text))
                self.assertFalse(marked(marks, found, 'RET'), (instr, text))

    def test_true_to_false_is_marked_above_the_coil(self):
        for k, value in ((0, 'TRUE'), (1, 'FALSE')):
            found, marks, p = pane('            ReturnTrue()', '            ReturnFalse()', k)
            self.assertEqual(p.state, 'changed')
            self.assertTrue(marked(marks, found, value), value)

    def test_a_return_value_added_is_marked(self):
        found, marks, _ = pane('            Return()', '            ReturnTrue()')
        self.assertTrue(marked(marks, found, 'TRUE'))
        self.assertTrue(marked(marks, found, 'RET'))

    def test_a_contact_before_it_stays_unmarked(self):
        found, marks, _ = pane('            ReturnTrue()', '            ReturnFalse()')
        self.assertFalse(marked(marks, found, '#a'))


if __name__ == '__main__':
    unittest.main()
