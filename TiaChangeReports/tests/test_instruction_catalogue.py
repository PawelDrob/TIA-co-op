"""The instruction catalogue: an instruction draws as TIA's screen shows it, the same from both export formats; what the
catalogue does not hold keeps its raw names, and nothing is guessed for it. Shapes as TIA V20 Update 7 exported them,
the operands made up. From the repo root: python -m unittest discover -s TiaChangeReports/tests -t .
"""
import re
import unittest
from itertools import dropwhile

from TiaChangeReports import instructions
from TiaChangeReports.compare import compare_blocks
from TiaChangeReports.page import render
from TiaChangeReports.render_lad import Layout
from TiaChangeReports.s7dcl import parse_block
from TiaChangeReports.simaticml import address, scl_text, stl_text
from TiaChangeReports.source import BlockSource
from TiaChangeReports.verify import check

import xml.etree.ElementTree as ET

from . import test_change_reports as cr

SD = '''FUNCTION_BLOCK "Sample"
    VAR
        a : Bool;
        b : Bool;
        c : Bool;
        v : Variant;
        i : Int;
        o : Int;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
%s
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''

IO = chr(0x21cc)
A, B, C, D = 21, 22, 23, 24       # the fixture's operands: #start, #stop, #big, #latch
PART = 25


def sd_source(body):
    return BlockSource('Sample', SD % body, None, 'Sample.s7dcl')


def inp(uid, pin):
    return '<IdentCon UId="%d" /><NameCon UId="%d" Name="%s" />' % (uid, PART, pin)


def out(uid, pin):
    """An output as TIA writes it: the wire starts at the pin."""
    return '<NameCon UId="%d" Name="%s" /><IdentCon UId="%d" />' % (PART, pin, uid)


def rail(pin):
    return '<Powerrail /><NameCon UId="%d" Name="%s" />' % (PART, pin)


def xml_source(part, wires, templates=(), extra=''):
    n = cr.NegatedPins('test_taken_away')
    inner = ''.join('<TemplateValue Name="%s" Type="Type">%s</TemplateValue>' % t for t in templates)
    text = n.net(extra + '<Part Name="%s" UId="%d">%s</Part>' % (part, PART, inner), wires, 'LAD')
    return cr._xml_src(text)


def view(src, k=-1):
    """(the view of the element, its layout) of the first network."""
    b = parse_block(src)
    net = b.networks[0]
    lay = Layout(net.rungs, b.interface, None, net.label)
    items = [i for r in net.rungs for i in r.items if not isinstance(i, tuple)]
    return lay.views[items[k].eid], lay


def box(v):
    """(title, type line, left pins, right pins) of a box."""
    return (v.title, ' '.join(v.subpair) if v.subpair else v.sub, [v._label(r, n) for r, (n, _) in enumerate(v.lefts)],
            [n for n, _ in v.rights])


def texts(v):
    return re.findall(r'<text [^>]*>([^<]*)</text>', ''.join(v.draw(0, 100)))


def box_source(head, params, feeds=1, pragma='', instance=None):
    """The box's rung, after a rung per wire#f<k> it reads, as its .s7dcl; instance: the type of #inst, a box no name tells is one."""
    body = ''.join('Contact( #b )\nEND_RUNG wire#f%d\nRUNG wire#powerrail\n' % k for k in range(feeds))
    src = sd_source(body + 'Contact( #a )\n' + pragma + head + '(\n' + ',\n'.join(params) + '\n)')
    return BlockSource('Sample', src.s7dcl.replace('a : Bool;', 'inst : %s;\n        a : Bool;' % instance, 1), None, 'Sample.s7dcl') if instance else src


def box_pins(src, title):
    """(left pins, right pins) of the box."""
    b = parse_block(src)
    lay = Layout(b.networks[0].rungs, b.interface, None, b.networks[0].label)
    return box(next(v for v in lay.views.values() if getattr(v, 'title', None) == title))[2:]


class PinsFedByLogic(unittest.TestCase):
    """A pin fed by logic stands in the order of the box's .s7dcl export, in both formats. SimaticML's wires do not tell: they keep
    the order only of the pins with an operand, so the catalogue holds that order for the boxes it lists."""

    RUNG_FEED, FIRST_FEED, OUT_COIL = 26, 27, 40
    INT_TEMPLATE = (('value_type', 'Int'),)
    INT_LINE = '{ S7_Templates := "value_type := Int" }\n'

    def xml(self, part, rung, fed, operands, templates=(), logic_out=None):
        """part's pin `rung` on a contact from the rail, each of `fed` on a contact of its own, the operands on the rest."""
        contacts = [self.RUNG_FEED] + [self.FIRST_FEED + k for k in range(len(fed))]
        extra = ''.join('<Part Name="Contact" UId="%d" />' % u for u in contacts)
        wires = ['<Powerrail />' + ''.join('<NameCon UId="%d" Name="in" />' % u for u in contacts)]
        wires += [cr.NegatedPins.op(A, u, 'operand') for u in contacts]
        wires += [cr.NegatedPins.flow(self.RUNG_FEED, 'out', PART, rung)]
        wires += [cr.NegatedPins.flow(u, 'out', PART, pin) for u, pin in zip(contacts[1:], fed)]
        wires += [inp(B, pin) if d == ':=' else out(C, pin) for pin, d in operands]
        if logic_out:
            extra += '<Part Name="Coil" UId="%d" />' % self.OUT_COIL
            wires += [cr.NegatedPins.flow(PART, logic_out, self.OUT_COIL, 'in'), cr.NegatedPins.op(D, self.OUT_COIL, 'operand')]
        return xml_source(part, wires, templates, extra)

    def test_ctu_reset_fed_by_logic(self):
        want = (['CU', 'R', 'PV'], ['Q', 'CV'])
        self.assertEqual(box_pins(self.xml('CTU', 'CU', ['R'], [('PV', ':='), ('CV', '=>')], self.INT_TEMPLATE), 'CTU'), want)
        self.assertEqual(box_pins(box_source('#inst.CTU', ['r := wire#f0', 'pv := #i', 'cv => #o'], pragma=self.INT_LINE), 'CTU'), want)

    def test_ctd_load_fed_by_logic(self):
        want = (['CD', 'LD', 'PV'], ['Q', 'CV'])
        self.assertEqual(box_pins(self.xml('CTD', 'CD', ['LD'], [('PV', ':='), ('CV', '=>')], self.INT_TEMPLATE), 'CTD'), want)
        self.assertEqual(box_pins(box_source('#inst.CTD', ['ld := wire#f0', 'pv := #i', 'cv => #o'], pragma=self.INT_LINE), 'CTD'), want)

    def test_ctud_two_pins_fed_by_logic_in_their_order_not_the_alphabet(self):
        want = ['CU', 'CD', 'R', 'LD', 'PV']
        self.assertEqual(box_pins(self.xml('CTUD', 'CU', ['LD', 'R'], [('CD', ':='), ('PV', ':='), ('QD', '=>'), ('CV', '=>')], self.INT_TEMPLATE), 'CTUD')[0], want)
        self.assertEqual(box_pins(box_source('#inst.CTUD', ['ld := wire#f0', 'r := wire#f1', 'cd := #c', 'pv := #i', 'qd => #c', 'cv => #o'], feeds=2, pragma=self.INT_LINE), 'CTUD')[0], want)

    def test_ctud_an_output_that_feeds_logic_keeps_its_place(self):
        src = self.xml('CTUD', 'CU', [], [('CD', ':='), ('R', ':='), ('LD', ':='), ('PV', ':='), ('CV', '=>')], self.INT_TEMPLATE, logic_out='QD')
        self.assertEqual(box_pins(src, 'CTUD')[1], ['QU', 'QD', 'CV'])

    def test_sel_its_condition_fed_by_logic(self):
        want = ['EN', 'G', 'IN0', 'IN1']
        self.assertEqual(box_pins(self.xml('SEL', 'en', ['G'], [('IN0', ':='), ('IN1', ':='), ('OUT', '=>')]), 'SEL')[0], want)
        self.assertEqual(box_pins(box_source('SEL', ['g := wire#f0', 'in0 := #i', 'in1 := #i', 'out => #o']), 'SEL')[0], want)

    def test_dcat_and_mcat_their_first_pin_fed_by_logic(self):
        self.assertEqual(box_pins(self.xml('DCAT', 'en', ['CMD'], [('O_FB', ':='), ('C_FB', ':='), ('Q', '=>'), ('OA', '=>'), ('CA', '=>')]), 'DCAT'),
                         (['EN', 'CMD', 'O_FB', 'C_FB'], ['ENO', 'Q', 'OA', 'CA']))
        self.assertEqual(box_pins(self.xml('MCAT', 'en', ['O_CMD'], [('C_CMD', ':='), ('S_CMD', ':='), ('O_FB', ':='), ('C_FB', ':='), ('OO', '=>'), ('CO', '=>'), ('OA', '=>'), ('CA', '=>'), ('Q', '=>')]), 'MCAT'),
                         (['EN', 'O_CMD', 'C_CMD', 'S_CMD', 'O_FB', 'C_FB'], ['ENO', 'OO', 'CO', 'OA', 'CA', 'Q']))
        self.assertEqual(box_pins(box_source('#inst.DCAT', ['CMD := wire#f0', 'O_FB := #a', 'C_FB := #b', 'Q => #c', 'OA => #c', 'CA => #c'], instance='DCAT'), 'DCAT'),
                         (['EN', 'CMD', 'O_FB', 'C_FB'], ['ENO', 'Q', 'OA', 'CA']))
        self.assertEqual(box_pins(box_source('#inst.MCAT', ['O_CMD := wire#f0', 'C_CMD := #a', 'S_CMD := #b', 'O_FB := #a', 'C_FB := #b', 'OO => #c', 'CO => #c', 'OA => #c', 'CA => #c', 'Q => #c'], instance='MCAT'), 'MCAT'),
                         (['EN', 'O_CMD', 'C_CMD', 'S_CMD', 'O_FB', 'C_FB'], ['ENO', 'OO', 'CO', 'OA', 'CA', 'Q']))

    def test_bo_w_a_low_bit_fed_by_logic(self):
        self.assertEqual(box_pins(self.xml('BO_W', 'en', ['IN0'], [('IN1', ':='), ('IN2', ':='), ('OUT', '=>')]), 'BO_W')[0], ['EN', 'IN0', 'IN1', 'IN2'])
        self.assertEqual(box_pins(box_source('BO_W', ['IN0 := wire#f0', 'IN1 := #a', 'IN2 := #b', 'OUT => #o']), 'BO_W')[0], ['EN', 'IN0', 'IN1', 'IN2'])

    def test_w_bo_an_output_that_feeds_logic_keeps_its_place(self):
        src = self.xml('W_BO', 'en', [], [('IN', ':='), ('OUT1', '=>')], logic_out='OUT0')
        self.assertEqual(box_pins(src, 'W_BO')[1], ['ENO', 'OUT0', 'OUT1'])

    def test_with_operands_only_it_draws_as_before(self):
        self.assertEqual(box_pins(self.xml('CTU', 'CU', [], [('R', ':='), ('PV', ':='), ('CV', '=>')], self.INT_TEMPLATE), 'CTU'), (['CU', 'R', 'PV'], ['Q', 'CV']))


class RungPinNotListed(unittest.TestCase):
    """A rung pin the catalogue does not list stands first on its side, wherever the export writes it, with an operand or a wire. The
    report's own choice: no shot of TIA shows such a pin. EN and ENO in a .s7dcl are forged here: the format guide has them never written in text."""

    # the box, the pins given, inputs then outputs, and the .s7dcl's head and instance type; not all the pins of BO_W and W_BO
    BOXES = (('SEL', 'G IN0 IN1', 'OUT', 'SEL', None),
             ('DCAT', 'CMD O_FB C_FB', 'Q OA CA', '#inst.DCAT', 'DCAT'),
             ('MCAT', 'O_CMD C_CMD S_CMD O_FB C_FB', 'OO CO OA CA Q', '#inst.MCAT', 'MCAT'),
             ('BO_W', 'IN0 IN1 IN2', 'OUT', 'BO_W', None),
             ('W_BO', 'IN', 'OUT0 OUT1', 'W_BO', None),
             ('LIMIT', 'MN IN MX', 'OUT', 'Limit', None),
             ('Add', 'IN1 IN2', 'OUT', 'Add', None))        # no list at all

    def assertRungFirst(self, drawn, rung, others):
        """Every row of the rung's pin, then the others in their order; how many rows the rung's pin has is not this test's."""
        self.assertEqual(list(dropwhile(lambda n: n == rung, drawn)), others, drawn)
        self.assertEqual(drawn[0], rung, drawn)

    def test_an_operand_on_en_written_last(self):
        for part, ins, outs, head, instance in self.BOXES:
            ins, outs = ins.split(), outs.split()
            with self.subTest(part, format='SimaticML'):
                wires = [inp(B, p) for p in ins] + [out(C, p) for p in outs] + [inp(A, 'en')]
                self.assertRungFirst(box_pins(xml_source(part, wires), part.upper())[0], 'EN', ins)
            with self.subTest(part, format='.s7dcl'):
                params = ['%s := #b' % p.lower() for p in ins] + ['%s => #c' % p.lower() for p in outs] + ['en := #a']
                self.assertRungFirst(box_pins(box_source(head, params, feeds=0, instance=instance), part.upper())[0], 'EN', ins)

    def test_an_operand_on_eno_written_last(self):
        for part, ins, outs, head, instance in self.BOXES:
            ins, outs = ins.split(), outs.split()
            with self.subTest(part, format='SimaticML'):
                wires = [rail('en')] + [inp(B, p) for p in ins] + [out(C, p) for p in outs] + [out(C, 'eno')]
                self.assertRungFirst(box_pins(xml_source(part, wires), part.upper())[1], 'ENO', outs)
            with self.subTest(part, format='.s7dcl'):
                params = ['%s := #b' % p.lower() for p in ins] + ['%s => #c' % p.lower() for p in outs] + ['eno => #c']
                self.assertRungFirst(box_pins(box_source(head, params, feeds=0, instance=instance), part.upper())[1], 'ENO', outs)

    def test_a_rung_pin_other_than_en_eno_written_last(self):
        self.assertRungFirst(box_pins(xml_source('TON', [rail('IN'), inp(B, 'PT'), out(C, 'ET'), out(C, 'Q')]), 'TON')[1], 'Q', ['ET'])
        self.assertRungFirst(box_pins(box_source('#inst.TON', ['pt := #i', 'et => #o', 'q => #c'], feeds=0), 'TON')[1], 'Q', ['ET'])

    def test_a_wire_on_en(self):
        src = box_source('Limit', ['min := #i', 'in := #i', 'max := #i', 'en := wire#f0', 'out => #o'])
        self.assertRungFirst(box_pins(src, 'LIMIT')[0], 'EN', ['MN', 'IN', 'MX'])

    def test_no_entry_puts_a_rung_pin_after_another_pin(self):
        for name, spec in instructions.CATALOGUE.items():
            for end, side in enumerate(('in', 'out')):
                rung = spec.rung[end]
                if rung:
                    others = [p.tia for p in spec.pins if p.side == side and p.tia != rung] + ['a pin it does not list']
                    with self.subTest(name, pin=rung):
                        self.assertLess(spec.order(rung), min(spec.order(n) for n in others))


class TypeChecks(unittest.TestCase):
    """A type check is no bit check: TIA writes its name in the contact, one operand above, one below."""

    CHECKS = (('EQ_Type', 'EQ_TypeContact'), ('NE_Type', 'NE_TypeContact'), ('EQ_ElemType', 'EQ_ElemTypeContact'),
              ('NE_ElemType', 'NE_ElemTypeContact'), ('EQ_TypeOfDB', 'EQ_TypeOfDBContact'), ('NE_TypeOfDB', 'NE_TypeOfDBContact'))

    def test_from_a_s7dcl(self):
        for title, sd in self.CHECKS:
            v, lay = view(sd_source('%s(\n in1 := #v,\n in2 := #i\n)' % sd))
            self.assertEqual(v.el.kind, 'contact')
            self.assertEqual(texts(v), ['#v', title, '#i'])
            self.assertEqual(check(lay), [])

    def test_from_a_simaticml_export(self):
        for title, _ in self.CHECKS:
            v, _ = view(xml_source(title, [rail('pre'), inp(A, 'in1'), inp(B, 'in2')],
                                   (('in1_type', 'Variant'), ('in2_type', 'Variant'))))
            self.assertEqual(v.el.kind, 'contact')
            self.assertEqual(texts(v), ['#start', title, '#stop'])

    def test_the_bars_clear_the_name(self):
        v, _ = view(sd_source('EQ_ElemTypeContact(\n in1 := #v,\n in2 := #i\n)'))
        svg = ''.join(v.draw(0, 100))
        bars = sorted(float(x) for x in re.findall(r'<line x1="([\d.]+)"[^>]*stroke-width="1.6"', svg))
        self.assertGreater(bars[-1] - bars[0], 70)

    def test_one_check_changed_to_another_shows(self):
        d = compare_blocks(sd_source('EQ_TypeContact(\n in1 := #v,\n in2 := #i\n)'),
                           sd_source('NE_TypeContact(\n in1 := #v,\n in2 := #i\n)'))
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')
        html = render([d], 'b', 'a')
        self.assertIn('>EQ_Type<', html)
        self.assertIn('>NE_Type<', html)
        self.assertIn('class="hl', html)

    def test_a_type_constant_of_a_simaticml_export_is_its_name(self):
        extra = '<Access Scope="SystemType" UId="26"><DataType>IEC_TIMER</DataType></Access>'
        v, _ = view(xml_source('EQ_TypeOfDB', [rail('pre'), inp(A, 'in1'), inp(26, 'in2')], extra=extra))
        self.assertEqual(texts(v), ['#start', 'EQ_TypeOfDB', 'IEC_TIMER'])


class NamedContacts(unittest.TestCase):
    """OK, NOT_OK, IS_NULL, NOT_NULL, IS_ARRAY: a contact with the name in it, the operand above; no EN / ENO."""

    def test_both_formats(self):
        for title, sd, xml in (('OK', 'OK', 'OK'), ('NOT_OK', 'NOK', 'NOK'), ('IS_NULL', 'IS_NULL', 'IS_NULL'),
                               ('NOT_NULL', 'NOT_NULL', 'NOT_NULL'), ('IS_ARRAY', 'IS_ARRAY', 'IS_ARRAY')):
            self.assertEqual(texts(view(sd_source('%s( #v )' % sd))[0]), ['#v', title])
            self.assertEqual(texts(view(xml_source(xml, [rail('pre'), inp(A, 'operand')]))[0]), ['#start', title])

    def test_a_contact_the_catalogue_does_not_hold_keeps_its_name(self):
        v, _ = view(sd_source('NewCheckContact( #v )'))
        self.assertEqual(texts(v), ['#v', 'NewCheckContact'])

    def test_the_plain_contacts_write_no_name(self):
        self.assertEqual(texts(view(sd_source('Contact( #a )'))[0]), ['#a'])
        self.assertEqual(texts(view(sd_source('I_Contact( #a )'))[0]), ['#a'])


class CoilForms(unittest.TestCase):
    """The coil forms of a SimaticML export: the coil, as a .s7dcl draws it."""

    def test_iec_timer_coils(self):
        for xml, sd, kind in (('CoilTP', 'TP_Coil', 'TP'), ('CoilTON', 'TON_Coil', 'TON'), ('CoilTOF', 'TOF_Coil', 'TOF'),
                              ('CoilTONR', 'TONR_Coil', 'TONR')):
            x, _ = view(xml_source(xml, [rail('in'), inp(A, 'operand'), inp(B, 'value')], (('time_type', 'Time'),)))
            s, _ = view(sd_source('{ S7_Templates := "time_type := Time" }\n%s(\n timer => #start,\n pt := #stop\n)' % sd))
            self.assertEqual(x.el.kind, 'coil')
            self.assertEqual(texts(x), [kind, 'Time', '#start', '#stop'])
            self.assertEqual(texts(s), texts(x))

    def test_s5_coils_have_their_letters(self):
        for xml, letters in (('SpCoil', 'SP'), ('SeCoil', 'SE'), ('SdCoil', 'SD'), ('SsCoil', 'SS'), ('SfCoil', 'SF')):
            v, _ = view(xml_source(xml, [rail('in'), inp(A, 'operand'), inp(B, 'value')]))
            self.assertEqual(texts(v), [letters, '#start', '#stop'])

    def test_jump_and_return(self):
        extra = '<Access Scope="Label" UId="26"><Label Name="target" /></Access>'
        self.assertEqual(texts(view(xml_source('Jump', [rail('in'), inp(26, 'label')], extra=extra))[0]), ['JMP', 'target'])
        self.assertEqual(texts(view(xml_source('JumpNot', [rail('in'), inp(26, 'label')], extra=extra))[0]), ['JMPN', 'target'])
        self.assertEqual(texts(view(xml_source('ReturnValue', [rail('in'), inp(A, 'operand')]))[0]), ['RET', '#start'])


class Addresses(unittest.TestCase):
    def test_timer_and_counter(self):
        self.assertEqual(address(ET.fromstring('<Address Area="Timer" Type="Timer" BitOffset="11" />')), '%T11')
        self.assertEqual(address(ET.fromstring('<Address Area="Counter" Type="Counter" BitOffset="3" />')), '%C3')

    def test_input_output_memory(self):
        self.assertEqual(address(ET.fromstring('<Address Area="Input" Type="Bool" BitOffset="9" />')), '%I1.1')
        self.assertEqual(address(ET.fromstring('<Address Area="Memory" Type="Word" BitOffset="16" />')), '%MW2')

    def test_another_is_written_with_all_it_holds(self):
        a, b = ('<Address Area="DB" Type="Word" BlockNumber="%s" BitOffset="16" />' % n for n in '12')
        self.assertNotEqual(address(ET.fromstring(a)), address(ET.fromstring(b)))
        self.assertIn('BlockNumber=1', address(ET.fromstring(a)))


class S5(unittest.TestCase):
    """S_PULSE ...: the timer above, S, TV, R; Q, BI, BCD. S_CU ...: the counter above, CU or CD, S, PV, R; Q, CV, CV_BCD. No
    EN / ENO. Both exports write other names; TIA's screen wins."""

    EXTRA = '<Access Scope="Address" UId="26"><Address Area="Timer" Type="Timer" BitOffset="1" /></Access>'

    def test_timers(self):
        for sd, title in (('Sp', 'S_PULSE'), ('Se', 'S_PEXT'), ('Sd', 'S_ODT'), ('Ss', 'S_ODTS'), ('Sf', 'S_OFFDT')):
            want = (title, '', ['S', 'TV', 'R'], ['Q', 'BI', 'BCD'])
            s, lay = view(sd_source('Contact( #a )\n%s(\n Top := %%T1,\n TV := #i,\n R := #b,\n RT => #o,\n RTBCD => #o\n)\nCoil( #c )' % sd), 1)
            self.assertEqual(box(s), want)
            self.assertEqual(s.inst, '%T1')
            self.assertEqual(check(lay), [])
            x, _ = view(xml_source(sd, [rail('s'), inp(A, 'tv'), inp(B, 'r'), out(C, 'rt'), out(D, 'rtbcd'), inp(26, 'timer')], extra=self.EXTRA))
            self.assertEqual(box(x), want)
            self.assertEqual(x.inst, '%T1')

    def test_counters(self):
        extra = self.EXTRA.replace('Timer', 'Counter')
        for sd, title, rung, ins in (('Cu', 'S_CU', 'cu', ['S', 'PV', 'R']), ('Cd', 'S_CD', 'cd', ['S', 'PV', 'R'])):
            want = (title, '', [rung.upper()] + ins, ['Q', 'CV', 'CV_BCD'])
            s, _ = view(sd_source('%s(\n Top := %%C1,\n S := #b,\n PV := #i,\n R := #c,\n CV => #o,\n CVBCD => #o\n)' % sd))
            self.assertEqual(box(s), want)
            x, _ = view(xml_source(sd, [rail(rung), inp(A, 's'), inp(B, 'pv'), inp(C, 'r'), out(D, 'cv'), out(D, 'cvbcd'), inp(26, 'counter')], extra=extra))
            self.assertEqual(box(x), want)
            self.assertEqual(x.inst, '%C1')
            self.assertEqual(x.el.instr, sd)

    def test_up_down(self):
        s, _ = view(sd_source('Cud(\n Top := %C1,\n CD := #a,\n S := #b,\n PV := #i,\n R := #c,\n CV => #o,\n CVBCD => #o\n)'))
        self.assertEqual(box(s), ('S_CUD', '', ['CU', 'CD', 'S', 'PV', 'R'], ['Q', 'CV', 'CV_BCD']))

    def test_another_timer_is_marked_above_the_box(self):
        body = 'Sp(\n Top := %%T%d,\n TV := #i,\n R := #b,\n RT => #o,\n RTBCD => #o\n)'
        d = compare_blocks(sd_source(body % 1), sd_source(body % 2))
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')
        svg = re.findall(r'<div class="pane">.*?</svg>', render([d], 'b', 'a'), re.S)[-1]
        self.assertIn('>%T2<', svg)
        self.assertIn('class="hl', svg)


class Boxes(unittest.TestCase):
    """Title, type line, pins with their case, side and order, as TIA's screen: the same from both formats."""

    def both(self, want, sd, part, wires, templates=(), sd_pragma=''):
        s, _ = view(sd_source(sd_pragma + sd))
        x, _ = view(xml_source(part, [rail('en')] + wires, templates))
        self.assertEqual(box(s), want, 's7dcl')
        self.assertEqual(box(x), want, 'SimaticML')

    def test_deserialize(self):
        self.both(('Deserialize', '', ['EN', 'SRC_ARRAY', IO + 'POS'], ['ENO', 'Ret_Val', 'DEST_VARIABLE']),
                  'Deserialize(\n srcArray := #a,\n ret_val => #o,\n dstVariable => #o,\n pos := #i\n)', 'Deserialize',
                  [inp(A, 'SRC_ARRAY'), out(B, 'DEST_VARIABLE'), inp(C, 'POS'), out(D, 'Ret_Val')])

    def test_serialize(self):
        self.both(('Serialize', '', ['EN', 'SRC_VARIABLE', IO + 'POS'], ['ENO', 'Ret_Val', 'DEST_ARRAY']),
                  'Serialize(\n srcVariable := #a,\n ret_val => #o,\n dstArray => #o,\n pos := #i\n)', 'Serialize',
                  [inp(A, 'SRC_VARIABLE'), out(B, 'DEST_ARRAY'), inp(C, 'POS'), out(D, 'Ret_Val')])

    def test_move_blk_variant(self):
        self.both(('MOVE_BLK_VARIANT', '', ['EN', 'SRC', 'COUNT', 'SRC_INDEX', 'DEST_INDEX'], ['ENO', 'Ret_Val', 'DEST']),
                  'MoveBlockVariant(\n src := #a,\n count := #i,\n srcIndex := #i,\n dstIndex := #i,\n ret_val => #o,\n dst => #o\n)',
                  'MOVE_BLK_VARIANT', [inp(A, 'SRC'), inp(B, 'COUNT'), inp(C, 'SRC_INDEX'), inp(D, 'DEST_INDEX'), out(A, 'DEST'), out(B, 'Ret_Val')])

    def test_array_db_in_lower_case(self):
        self.both(('ReadFromArrayDB', '', ['EN', 'db', 'index'], ['ENO', 'Ret_Val', 'value']),
                  'ReadFromArrayDB(\n db := #a,\n index := #i,\n ret_val => #o,\n value => #o\n)', 'ReadFromArrayDB',
                  [inp(A, 'db'), inp(B, 'index'), out(C, 'value'), out(D, 'Ret_Val')])
        self.both(('ReadFromArrayDBL', '', ['EN', 'req', 'db', 'index', IO + 'value'], ['ENO', 'busy', 'done', 'error']),
                  'ReadFromArrayDBL(\n req := #a,\n db := #b,\n index := #i,\n busy => #c,\n done => #c,\n error => #o,\n value := #o\n)',
                  'ReadFromArrayDBL', [inp(A, 'req'), inp(B, 'db'), inp(C, 'index'), inp(D, 'value'), out(A, 'busy'), out(B, 'done'), out(C, 'error')])

    def test_legacy_blocks_move_and_fill(self):
        self.both(('BLKMOV', 'Variant', ['EN', 'SRCBLK'], ['ENO', 'RET_VAL', 'DSTBLK']),
                  'S_BlockMove(\n srcBlock := #a,\n ret_val => #o,\n dstBlock => #o\n)', 'BLKMOV',
                  [inp(A, 'SRCBLK'), out(B, 'RET_VAL'), out(C, 'DSTBLK')], (('blk_type', 'Variant'),))
        self.both(('FILL', 'Variant', ['EN', 'BVAL'], ['ENO', 'RET_VAL', 'BLK']),
                  'S_Fill(\n BVAL := #a,\n RET_VAL => #o,\n BLK => #o\n)', 'FILL',
                  [inp(A, 'BVAL'), out(B, 'RET_VAL'), out(C, 'BLK')], (('ptr_type', 'Variant'),))

    def test_legacy_scale_has_ret_val_above_out(self):
        self.both(('SCALE', '', ['EN', 'IN', 'HI_LIM', 'LO_LIM', 'BIPOLAR'], ['ENO', 'RET_VAL', 'OUT']),
                  'S_Scale(\n in := #a,\n hiLim := #i,\n loLim := #i,\n bipolar := #b,\n ret_val => #o,\n out => #o\n)', 'SCALE',
                  [inp(A, 'IN'), inp(B, 'HI_LIM'), inp(C, 'LO_LIM'), inp(D, 'BIPOLAR'), out(A, 'OUT'), out(B, 'RET_VAL')])

    def test_inc_is_in_out(self):
        self.both(('INC', 'Int', ['EN', IO + 'IN/OUT'], ['ENO']), 'Inc( #o )', 'Inc', [inp(A, 'operand')],
                  (('DestType', 'Int'),), '{ S7_Templates := "DestType := Int" }\n')

    def test_limit(self):
        self.both(('LIMIT', 'Int', ['EN', 'MN', 'IN', 'MX'], ['ENO', 'OUT']), 'Limit(\n min := #i,\n in := #i,\n max := #i,\n out => #o\n)',
                  'LIMIT', [inp(A, 'MN'), inp(B, 'IN'), inp(C, 'MX'), out(D, 'OUT')], (('value_type', 'Int'),),
                  '{ S7_Templates := "value_type := Int" }\n')

    def test_runtime_and_get_err_id(self):
        self.both(('RUNTIME', '', ['EN', IO + 'MEM'], ['ENO', 'Ret_Val']), 'Runtime(\n ret_val => #o,\n mem := #o\n)', 'Runtime',
                  [inp(A, 'mem'), out(B, 'ret_val')])
        self.both(('GET_ERR_ID', '', ['EN'], ['ENO', 'ID']), 'GetErrorID(error => #o)', 'GetErrorID', [out(A, 'id')])

    def test_type_lines(self):
        self.both(('DECO', 'UInt to Word', ['EN', 'IN'], ['ENO', 'OUT']), 'DECO(\n in := #i,\n out => #o\n)', 'DECO',
                  [inp(A, 'IN'), out(B, 'OUT')], (('value_type', 'UInt'), ('return_type', 'Word')),
                  '{ S7_Templates := "return_type := Word" }\n')
        self.both(('SCATTER_BLK', 'Byte count: UInt', ['EN', 'IN', 'COUNT_IN'], ['ENO', 'OUT']),
                  'ScatterBlock(\n in := #a,\n countIn := #i,\n out => #o\n)', 'SCATTER_BLK',
                  [inp(A, 'IN'), inp(B, 'COUNT_IN'), out(C, 'OUT')], (('dest_type', 'Bool'), ('src_type', 'Byte'), ('count_type', 'UInt')),
                  '{ S7_Templates := "[src_type := Byte, count_type := UInt]" }\n')
        self.both(('?=', 'Variant', ['EN', 'IN'], ['ENO', 'OUT']), 'AssignAttempt(\n in := #v,\n out => #o\n)', '?=',
                  [inp(A, 'IN'), out(B, 'OUT')], (('src_type', 'Variant'),), '{ S7_Templates := "src_type := Variant" }\n')
        self.both(('SCALE_X', 'Real to Int', ['EN', 'MIN', 'VALUE', 'MAX'], ['ENO', 'OUT']),
                  'Scale(\n min := #i,\n value := #i,\n max := #i,\n out => #o\n)', 'Scale_X',
                  [inp(A, 'min'), inp(B, 'value'), inp(C, 'max'), out(D, 'out')], (('SrcType', 'Real'), ('DestType', 'Int')),
                  '{ S7_Templates := "[SrcType := Real, DestType := Int]" }\n')

    def test_a_type_the_box_does_not_draw_stays_out(self):
        x, _ = view(xml_source('VariantGet', [rail('en'), inp(A, 'src'), out(B, 'dst')], (('src_type', 'Variant'), ('dst_type', 'Variant'))))
        self.assertEqual(box(x), ('VariantGet', '', ['EN', 'SRC'], ['ENO', 'DST']))

    def test_the_pins_of_ctud_outputs_on_the_right(self):
        x, _ = view(xml_source('CTUD', ['<Powerrail /><NameCon UId="25" Name="CU" />', inp(A, 'CD'), inp(B, 'R'), inp(C, 'LD'), inp(D, 'PV'),
                                        out(A, 'QD'), out(B, 'CV')], (('value_type', 'Int'),)))
        self.assertEqual(box(x), ('CTUD', 'Int', ['CU', 'CD', 'R', 'LD', 'PV'], ['QU', 'QD', 'CV']))

    def test_rs_has_one_pin_r(self):
        x, _ = view(xml_source('Rs', ['<Powerrail /><NameCon UId="25" Name="r" />', inp(A, 's1'), inp(B, 'operand')]))
        self.assertEqual(box(x)[2:], (['R', 'S1'], ['Q']))
        self.assertEqual(x.inst, '#stop')


class TypeSettingsTiaDoesNotDraw(unittest.TestCase):
    """A box has no line for them on TIA's screen. Nothing differs: TIA's look. They differ: the head writes what, on both sides."""

    def panes(self, before, after):
        d = compare_blocks(before, after)
        (p,) = d.nets
        svgs = re.findall(r'<div class="pane">.*?</svg>', render([d], 'b', 'a'), re.S)
        return p, [re.findall(r'<text [^>]*>([^<]*)</text>', s) for s in svgs], svgs

    def test_a_s7dcl_box_with_no_line(self):
        body = '{ S7_Templates := "laddr_type := %s" }\nDPRD_DAT(\n LADDR := #a\n)'
        p, (b, a), svgs = self.panes(sd_source(body % 'HW_IO'), sd_source(body % 'HW_ANY'))
        self.assertEqual(p.state, 'changed')
        self.assertIn('laddr_type: HW_IO', b)
        self.assertIn('laddr_type: HW_ANY', a)
        self.assertIn('class="hl', svgs[0])
        self.assertIn('class="hl', svgs[1])

    def test_nothing_differs_nothing_is_written(self):
        body = '{ S7_Templates := "laddr_type := HW_IO" }\nDPRD_DAT(\n LADDR := #a,\n RET_VAL => #%s\n)'
        _, (b, a), _ = self.panes(sd_source(body % 'o'), sd_source(body % 'i'))
        self.assertFalse([t for t in b + a if 'laddr_type' in t or 'HW_IO' in t])

    def test_a_template_beside_the_line_of_a_box(self):
        body = '{ S7_Templates := "[ptr_type := Variant, laddr_type := %s]" }\nRD_REC(\n LADDR := #a\n)'
        p, (b, a), _ = self.panes(sd_source(body % 'HW_IO'), sd_source(body % 'HW_ANY'))
        self.assertEqual(p.state, 'changed')
        self.assertEqual(b[:3], ['RD_REC', 'Variant', 'laddr_type: HW_IO'])
        self.assertEqual(a[:3], ['RD_REC', 'Variant', 'laddr_type: HW_ANY'])

    def test_one_side_holds_it(self):
        body = 'DPRD_DAT(\n LADDR := #a\n)'
        p, (b, a), _ = self.panes(sd_source(body), sd_source('{ S7_Templates := "laddr_type := HW_IO" }\n' + body))
        self.assertEqual(p.state, 'changed')
        self.assertIn('laddr_type: HW_IO', a)
        self.assertFalse([t for t in b if 'laddr_type' in t])

    def test_from_simaticml_reads_as_a_change_not_as_a_note(self):
        def src(value):
            return xml_source('DPRD_DAT', [rail('en'), inp(A, 'LADDR')], (('ptr_type', 'Variant'), ('laddr_type', value)))
        p, (b, a), _ = self.panes(src('HW_IO'), src('HW_ANY'))
        self.assertEqual(p.state, 'changed')
        self.assertIn('laddr_type: HW_IO', b)
        self.assertIn('laddr_type: HW_ANY', a)
        self.assertFalse([t for t in a if 'ptr_type' in t])

    def test_a_format_that_does_not_write_them_is_no_difference(self):
        x = xml_source('DPRD_DAT', [rail('en'), inp(A, 'LADDR')], (('ptr_type', 'Variant'), ('laddr_type', 'HW_IO')))
        v, _ = view(x)
        s, _ = view(sd_source('DPRD_DAT(\n LADDR := #a\n)'))
        from TiaChangeReports.diff import changed_params
        self.assertNotIn('templates', changed_params(v.el, s.el))

    def test_a_contact_writes_it_below(self):
        def src(value):
            return xml_source('IS_NULL', [rail('pre'), inp(A, 'operand')], (('var_type', value),))
        p, (b, a), _ = self.panes(src('Variant'), src('DB_ANY'))
        self.assertEqual(p.state, 'changed')
        self.assertIn('var_type: Variant', b)
        self.assertIn('var_type: DB_ANY', a)

    def test_the_drawing_holds(self):
        body = '{ S7_Templates := "laddr_type := %s" }\nDPRD_DAT(\n LADDR := #a\n)'
        before, after = parse_block(sd_source(body % 'HW_IO')), parse_block(sd_source(body % 'HW_ANY'))
        x, y = (bl.networks[0].rungs[0].items[0] for bl in (before, after))
        lay = Layout(before.networks[0].rungs, before.interface, None, '', 'same', {x.eid: y})
        self.assertEqual(check(lay), [])

    def test_a_relation_without_a_type_is_drawn(self):
        v, _ = view(sd_source('{ S7_Relation := "NE" }\nS_COMP(\n in1 := #a,\n in2 := #b,\n out => #o\n)'))
        self.assertIn('NE', texts(v))


class SMove(unittest.TestCase):
    """Real .s7dcl exports write S_Move, without a template; one with its template and a SimaticML export S_MOVE."""

    def test_the_older_name(self):
        v, _ = view(sd_source('S_Move(\n in := #a,\n out => #o\n)'))
        self.assertEqual(box(v), ('S_MOVE', '', ['EN', 'IN'], ['ENO', 'OUT']))

    def test_with_its_types(self):
        s, _ = view(sd_source('{ S7_Templates := "[src_type := String, dest_type := String]" }\nS_Move(\n in := #a,\n out => #o\n)'))
        x, _ = view(xml_source('S_MOVE', [rail('en'), inp(A, 'IN'), out(B, 'OUT')], (('src_type', 'String'), ('dest_type', 'String'))))
        self.assertEqual(box(s)[:2], ('S_MOVE', 'String to String'))
        self.assertEqual(box(x)[:2], ('S_MOVE', 'String to String'))


class NotInTheCatalogue(unittest.TestCase):
    """The general box, as ever: the name and the pins in capitals, EN and ENO; its sides from what its export says."""

    def test_a_s7dcl_box(self):
        v, lay = view(sd_source('NewBox(\n Mixed_In := #a,\n Mixed_Out => #o\n)'))
        self.assertEqual(box(v), ('NEWBOX', '', ['EN', 'MIXED_IN'], ['ENO', 'MIXED_OUT']))
        self.assertEqual(check(lay), [])

    def test_a_simaticml_box(self):
        v, _ = view(xml_source('NewBox', [rail('en'), inp(A, 'Mixed_In'), out(B, 'Mixed_Out')]))
        self.assertEqual(box(v), ('NEWBOX', '', ['EN', 'MIXED_IN'], ['ENO', 'MIXED_OUT']))

    def test_an_output_is_where_its_wire_starts_whatever_its_name(self):
        v, _ = view(xml_source('NewBox', [rail('en'), out(A, 'in_name'), inp(B, 'out')]))
        self.assertEqual(box(v), ('NEWBOX', '', ['EN', 'OUT'], ['ENO', 'IN_NAME']))

    def test_generate_eno_changed_reads_as_a_change(self):
        """ENO is drawn gray and marked, as on any box."""
        off = '{ S7_GenerateENO := FALSE }\n'
        body = 'NewBox(\n in := #a,\n out => #o\n)'
        d = compare_blocks(sd_source(body), sd_source(off + body))
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')
        svg = re.findall(r'<div class="pane">.*?</svg>', render([d], 'b', 'a'), re.S)[-1]
        self.assertIn('>ENO<', svg)
        ((x, y),) = [(float(a), float(b)) for a, b in re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>ENO</text>', svg)]
        marks = [tuple(float(v) for v in m) for m in re.findall(r'<rect class="hl [^"]*" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg)]
        self.assertTrue(any(mx <= x - 3 <= mx + w and my <= y <= my + h for mx, my, w, h in marks), (x, y, marks))

    def test_on_a_box_without_a_name_for_eno_the_head_is_marked(self):
        """IN_RANGE has no ENO to write: the head tells it."""
        body = 'InRange(\n min := #i,\n in := #i,\n max := #i\n)'
        d = compare_blocks(sd_source(body), sd_source('{ S7_GenerateENO := FALSE }\n' + body))
        svg = re.findall(r'<div class="pane">.*?</svg>', render([d], 'b', 'a'), re.S)[-1]
        marks = [float(w) for w in re.findall(r'<rect class="hl [^"]*" x="[\d.]+" y="[\d.]+" width="([\d.]+)"', svg)]
        self.assertTrue(marks and max(marks) > 50, marks)


class ExtendedBoxes(unittest.TestCase):
    """Boxes of the extended instructions: names and case from the exports, the type line from the help's drawings of TIA."""

    def both(self, want, sd, part, wires, templates=(), pragma=''):
        s, _ = view(sd_source(pragma + sd))
        x, _ = view(xml_source(part, [rail('en')] + wires, templates))
        self.assertEqual(box(s), want, 's7dcl')
        self.assertEqual(box(x), want, 'SimaticML')

    def test_mixed_case_title_and_pins(self):
        self.both(('GetSymbolName', '', ['EN', 'variable', 'size'], ['ENO', 'OUT']),
                  'GetSymbolName(\n variable := #a,\n size := #i,\n out => #o\n)', 'GetSymbolName',
                  [inp(A, 'variable'), inp(B, 'size'), out(C, 'OUT')])

    def test_the_documents_name_is_not_the_title(self):
        self.both(('STRG_VAL', 'String TO USInt', ['EN', 'IN', 'FORMAT', 'P'], ['ENO', 'OUT']),
                  'StringToValue(\n in := #a,\n format := #i,\n p := #i,\n out => #o\n)', 'STRG_VAL',
                  [inp(A, 'IN'), inp(B, 'FORMAT'), inp(C, 'P'), out(D, 'OUT')], (('src_type', 'String'), ('dest_type', 'USInt')),
                  '{ S7_Templates := "[src_type := String, dest_type := USInt]" }\n')

    def test_two_types_with_their_word(self):
        for title, part_types, line in (('T_CONV', (('src_type', 'Time'), ('dest_type', 'DInt')), 'Time TO DInt'),
                                        ('T_ADD', (('date_type', 'Time'), ('time_type', 'Time')), 'Time PLUS Time'),
                                        ('T_SUB', (('date_type', 'Time'), ('time_type', 'Time')), 'Time MINUS Time'),
                                        ('T_DIFF', (('date_type', 'DTL'), ('time_type', 'Time')), 'DTL TO Time')):
            t = '[%s]' % ', '.join('%s := %s' % x for x in part_types)
            s, _ = view(sd_source('{ S7_Templates := "%s" }\n%s(\n in1 := #a,\n out => #o\n)' % (t, title)))
            x, _ = view(xml_source(title, [rail('en'), inp(A, 'IN1'), out(B, 'OUT')], part_types))
            self.assertEqual(box(s)[1], line)
            self.assertEqual(box(x)[1], line)

    def test_a_relation_in_a_cell_of_its_own(self):
        pragma = '{\n S7_Templates := "date_type := Date";\n S7_Relation := "%s"\n}\n'
        body = 'T_COMP(\n in1 := #a,\n in2 := #b,\n out => #o\n)'
        s, _ = view(sd_source(pragma % 'EQ' + body))
        self.assertEqual((s.sub, s.second), ('Date', 'EQ'))
        n = cr.NegatedPins('test_taken_away')
        text = n.net('<Part Name="T_COMP" UId="25"><TemplateValue Name="relation" Type="Operation">EQ</TemplateValue>'
                     '<TemplateValue Name="date_type" Type="Type">Date</TemplateValue></Part>',
                     [rail('en'), inp(A, 'IN1'), inp(B, 'IN2'), out(C, 'OUT')], 'LAD')
        x, _ = view(cr._xml_src(text))
        self.assertEqual((x.sub, x.second), ('Date', 'EQ'))
        self.assertEqual(texts(s)[:3], ['T_COMP', 'Date', 'EQ'])

    def test_another_relation_of_a_s7dcl_shows(self):
        pragma = '{\n S7_Templates := "date_type := Date";\n S7_Relation := "%s"\n}\n'
        body = 'T_COMP(\n in1 := #a,\n in2 := #b,\n out => #o\n)'
        d = compare_blocks(sd_source(pragma % 'EQ' + body), sd_source(pragma % 'NE' + body))
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')
        self.assertIn('>NE<', render([d], 'b', 'a'))

    def test_a_template_tia_does_not_draw_stays_out_but_a_change_of_it_shows(self):
        x, _ = view(xml_source('UPDAT_PI', [rail('en'), inp(A, 'PART'), out(B, 'RET_VAL'), out(C, 'FLADDR')], (('value_type', 'PIP'),)))
        self.assertEqual(box(x), ('UPDAT_PI', '', ['EN', 'PART'], ['ENO', 'RET_VAL', 'FLADDR']))
        s, _ = view(sd_source('{ S7_Templates := "[src_type := String, dest_type := String]" }\nS_MOVE(\n in := #a,\n out => #o\n)'))
        self.assertEqual(box(s)[1], 'String to String')
        d = compare_blocks(sd_source('{ S7_Templates := "src_type := String" }\nS_MOVE(\n in := #a,\n out => #o\n)'),
                           sd_source('{ S7_Templates := "src_type := WString" }\nS_MOVE(\n in := #a,\n out => #o\n)'))
        (p,) = d.nets
        self.assertEqual(p.state, 'changed')
        self.assertIn('class="hl', render([d], 'b', 'a'))

    def test_a_type_line_is_a_fact_per_box_not_a_rule_from_its_templates(self):
        templates = (('ptr_type', 'Variant'), ('laddr_type', 'HW_IO'))
        self.assertEqual(box(view(xml_source('RD_REC', [rail('en'), inp(A, 'LADDR')], templates))[0])[1], 'Variant')
        self.assertEqual(box(view(xml_source('WR_REC', [rail('en'), inp(A, 'LADDR')], templates))[0])[1], '')
        self.assertEqual(box(view(sd_source('RD_REC(\n LADDR := #a\n)'))[0])[1], 'Variant')
        self.assertEqual(box(view(sd_source('WR_REC(\n LADDR := #a\n)'))[0])[1], '')

    def test_in_out_marks_of_extended_boxes(self):
        x, _ = view(xml_source('JOIN', [rail('en'), inp(A, 'DstArray'), inp(B, 'Position')]))
        self.assertEqual(box(x)[2], ['EN', IO + 'DstArray', IO + 'Position'])
        s, _ = view(sd_source('PE_Start_RSP(\n Activate := #a\n)'))
        self.assertEqual(box(s)[2], ['EN', IO + 'Activate'])

    def test_p_of_strg_val_is_no_in_out_though_the_help_says_so(self):
        s, _ = view(sd_source('StringToValue(\n p := #i\n)'))
        self.assertEqual(box(s)[2], ['EN', 'P'])

    def test_no_line_on_the_screen_whatever_the_template(self):
        for name in ('SYNC_PI', 'SYNC_PO', 'UPDAT_PI', 'UPDAT_PO'):
            x, _ = view(xml_source(name, [rail('en'), inp(A, 'PART')], (('value_type', 'PIP'),)))
            self.assertEqual(box(x)[1], '', name)

    def test_the_last_extended_boxes_a_screen_settled_have_no_line(self):
        for name in ('RCVREC', 'PRVREC', 'GEO_LOG', 'LOG_GEO', 'RD_LGADR', 'GADR_LGC', 'LGC_GADR', 'RecipeExport', 'RecipeImport'):
            x, _ = view(xml_source(name, [rail('en')], (('value_type', 'Variant'),)))
            self.assertEqual(box(x)[1], '', name)

    def test_record_and_recipe_db_are_in_outs_as_on_the_screen(self):
        for name, ins, io in (('RCVREC', 'MODE', 'RECORD'), ('PRVREC', 'MODE', 'RECORD'), ('RecipeExport', 'REQ', 'RECIPE_DB'), ('RecipeImport', 'REQ', 'RECIPE_DB')):
            s, _ = view(sd_source('%s(\n %s := #i,\n %s := #v\n)' % (name, ins, io)))
            self.assertEqual(box(s)[2], ['EN', ins, IO + io], name)

    def test_a_type_the_export_leaves_out(self):
        self.both(('READ_DBL', 'Variant', ['EN', 'REQ', 'SRCBLK'], ['ENO', 'RET_VAL', 'BUSY', 'DSTBLK']),
                  'READ_DBL(\n REQ := #a,\n SRCBLK := #v,\n RET_VAL => #o,\n BUSY => #c,\n DSTBLK => #v\n)', 'READ_DBL',
                  [inp(A, 'REQ'), inp(B, 'SRCBLK'), out(C, 'RET_VAL'), out(D, 'BUSY'), out(A, 'DSTBLK')],
                  (('src_type', 'Variant'), ('dest_type', 'Variant')))


class CommunicationBoxes(unittest.TestCase):
    """The boxes of Communication that export as a part: title and pins as TIA writes them, in-outs marked, a type line only where
    a screen shows it. Screens of TIA V20 Update 7; pins from the instance's sections in its SimaticML."""

    def both(self, want, sd, part, wires, templates=()):
        a, _ = view(sd_source(sd))
        b, _ = view(xml_source(part, wires, templates))
        self.assertEqual(box(a), want)
        self.assertEqual(box(b), want)

    def test_get_and_put_as_on_the_screen(self):
        # the type line, also from a .s7dcl that holds no template; the wires of SimaticML pair ADDR_1 with RD_1, TIA has the four addresses first
        templates = (('remote_type', 'Remote'), ('local_type', 'Variant'))
        self.both(('GET', 'Remote - Variant', ['EN', 'REQ', IO + 'ADDR_1', IO + 'ADDR_2', IO + 'RD_1', IO + 'RD_2'], ['ENO', 'NDR']),
                  'GET(\n REQ := #a,\n NDR => #b,\n ADDR_1 := #i,\n ADDR_2 := #i,\n RD_1 := #v,\n RD_2 := #v\n)', 'GET',
                  [rail('en'), inp(A, 'REQ'), inp(B, 'ADDR_1'), inp(C, 'RD_1'), inp(B, 'ADDR_2'), inp(C, 'RD_2'), out(D, 'NDR')], templates)
        self.both(('PUT', 'Remote - Variant', ['EN', 'REQ', IO + 'ADDR_1', IO + 'SD_1'], ['ENO', 'DONE']),
                  'PUT(\n REQ := #a,\n DONE => #b,\n ADDR_1 := #i,\n SD_1 := #v\n)', 'PUT',
                  [rail('en'), inp(A, 'REQ'), inp(B, 'ADDR_1'), inp(C, 'SD_1'), out(D, 'DONE')], templates)

    def test_the_in_out_of_an_fc_of_the_optional_packages_keeps_its_case(self):
        self.both(('EnS_EEm_Calc', '', ['EN', IO + 'machineConfiguration'], ['ENO', 'error']),
                  'EnS_EEm_Calc(\n machineConfiguration := #i,\n error => #b\n)', 'EnS_EEm_Calc',
                  [rail('en'), inp(A, 'machineConfiguration'), out(B, 'error')])

    def test_title_and_pins_mixed_case(self):
        self.both(('OPC_UA_Disconnect', '', ['EN', 'REQ', 'ConnectionHdl'], ['ENO', 'Done', 'Busy', 'Error', 'Status']),
                  'OPC_UA_Disconnect(\n REQ := #a,\n ConnectionHdl := #i,\n Done => #b,\n Busy => #c,\n Error => #a,\n Status => #o\n)',
                  'OPC_UA_Disconnect',
                  [rail('en'), inp(A, 'REQ'), inp(B, 'ConnectionHdl'), out(C, 'Done'), out(D, 'Busy'), out(A, 'Error'), out(B, 'Status')])

    def test_in_outs_after_the_inputs_whatever_the_order_of_the_export(self):
        self.both(('TCONSettings', '', ['EN', 'REQ', 'MODE', IO + 'ID', IO + 'OPTION'], ['ENO', 'DONE']),
                  'TCONSettings(\n REQ := #a,\n MODE := #i,\n DONE => #b,\n ID := #i,\n OPTION := #v\n)', 'TCONSettings',
                  [rail('en'), inp(A, 'ID'), inp(A, 'OPTION'), inp(B, 'REQ'), inp(C, 'MODE'), out(D, 'DONE')])

    def test_a_pin_the_inventory_did_not_wire_is_still_a_fact(self):
        v, _ = view(sd_source('TSEND(\n REQ := #a,\n ADDR := #v\n)'))
        self.assertEqual(box(v)[2], ['EN', 'REQ', IO + 'ADDR'])

    def test_an_input_the_help_calls_an_in_out_stays_an_input(self):
        v, _ = view(sd_source('OPC_UA_Connect(\n ServerEndpointUrl := #v,\n SessionConnectInfo := #v\n)'))
        self.assertEqual(box(v)[2], ['EN', 'ServerEndpointUrl', 'SessionConnectInfo'])

    def test_the_template_tia_does_not_draw(self):
        self.both(('WWW', '', ['EN', 'CTRL_DB'], ['ENO', 'RET_VAL']), 'WWW(\n CTRL_DB := #i,\n RET_VAL => #o\n)', 'WWW',
                  [rail('en'), inp(A, 'CTRL_DB'), out(B, 'RET_VAL')], (('value_type', 'DB_WWW'),))

    def test_the_opc_ua_boxes_have_no_line_on_the_screen(self):
        x, _ = view(xml_source('OPC_UA_Disconnect', [rail('en'), inp(A, 'REQ')], (('value_type', 'UDInt'),)))
        self.assertEqual(box(x)[1], '')

    def test_the_line_the_screen_shows_though_the_s7dcl_holds_no_template(self):
        self.both(('BSEND', 'Variant', ['EN', 'REQ', 'ID', 'R_ID', IO + 'SD_1', IO + 'LEN'], ['ENO', 'DONE']),
                  'BSEND(\n REQ := #a,\n ID := #i,\n R_ID := #i,\n DONE => #b,\n SD_1 := #v,\n LEN := #i\n)', 'BSEND',
                  [rail('en'), inp(A, 'REQ'), inp(B, 'ID'), inp(C, 'R_ID'), inp(D, 'SD_1'), inp(A, 'LEN'), out(B, 'DONE')],
                  (('ptr_type', 'Variant'), ('id_type', 'CONN_PRG'), ('r_id_type', 'CONN_R_ID')))

    def test_no_line_on_the_screen_whatever_the_template(self):
        self.both(('TRCV', '', ['EN', 'EN_R', 'LEN'], ['ENO', 'NDR']), 'TRCV(\n EN_R := #a,\n LEN := #i,\n NDR => #b\n)', 'TRCV',
                  [rail('en'), inp(A, 'EN_R'), inp(B, 'LEN'), out(C, 'NDR')], (('value_type', 'UDInt'),))

    def test_the_in_out_of_an_fc_from_the_screen(self):
        for name in ('USS_Read_Param', 'USS_Read_Param_31'):
            self.both((name, '', ['EN', 'REQ', IO + 'USS_DB'], ['ENO', 'DONE', 'VALUE']),
                      name + '(\n REQ := #a,\n USS_DB := #i,\n DONE => #b,\n VALUE => #v\n)', name,
                      [rail('en'), inp(A, 'USS_DB'), inp(B, 'REQ'), out(C, 'DONE'), out(D, 'VALUE')],
                      (('byte_type', 'USInt'), ('word_type', 'UInt'), ('any_type', 'Variant'), ('ussbase_type', 'P2P_USS_BASE')))

    def test_write_param_has_value_on_the_left(self):
        v, _ = view(sd_source('USS_Write_Param(\n REQ := #a,\n VALUE := #v,\n USS_DB := #i,\n DONE => #b\n)'))
        self.assertEqual(box(v)[2:], (['EN', 'REQ', 'VALUE', IO + 'USS_DB'], ['ENO', 'DONE']))

    def test_an_fc_has_no_sections_its_wires_tell(self):
        self.both(('S_USST', '', ['EN', 'DBPA', 'SYPA', 'SLPA'], ['ENO']), 'S_USST(\n DBPA := #i,\n SYPA := #i,\n SLPA := #i\n)', 'S_USST',
                  [rail('en'), inp(A, 'DBPA'), inp(B, 'SYPA'), inp(C, 'SLPA')], (('dbno_type', 'UInt'),))


class FBoxes(unittest.TestCase):
    """F-LAD on TIA's screen. A box of the safety library draws as any: EN on the rail, ENO at the top, whatever the help's drawings have. What it shares with a standard box
    is the standard box's entry. An F-box's .s7dcl names only its cards in the pragma, not its type."""

    CARDS = '{ f_user_card := "1"; f_image_card := "0" }\n'

    def fb(self, typ, body):
        sd = 'FUNCTION_BLOCK "Sample"\n { S7_Safety := "TRUE" }\n VAR\n inst : %s;\n a : Bool;\n i : Int;\n END_VAR\n { S7_Language := "LAD" }\n NETWORK\n RUNG wire#powerrail\n%s\n END_RUNG\n END_NETWORK\nEND_FUNCTION_BLOCK\n'
        return BlockSource('Sample', sd % (typ, body), None, 'Sample.s7dcl')

    def test_title_in_tia_s_case(self):
        v, _ = view(self.fb('EV1oo2DI', self.CARDS + '#inst.EV1oo2DI(\n IN1 := #a,\n Q => #a\n)'))
        self.assertEqual(box(v), ('EV1oo2DI', '', ['EN', 'IN1'], ['ENO', 'Q']))

    def test_in_outs_below_the_inputs_whatever_the_order_of_the_export(self):
        x, _ = view(xml_source('F_FB_MP', [rail('en'), inp(A, 'MP_STAT'), inp(B, 'QBAD'), out(C, 'ACK_REI')]))
        self.assertEqual(box(x)[2:], (['EN', 'QBAD', IO + 'MP_STAT'], ['ENO', 'ACK_REI']))

    def test_the_rng_pins_by_mp_as_tia_not_as_the_wires(self):
        x, _ = view(xml_source('F_FB_RNG_4', [rail('en'), inp(A, 'MP1_DATA'), inp(B, 'MP2_DATA'), inp(C, 'MP1_RNG'), inp(D, 'MP1_STAT')]))
        self.assertEqual(box(x)[2], ['EN', 'MP1_DATA', 'MP1_RNG', 'MP2_DATA', IO + 'MP1_STAT'])

    def test_the_type_a_s7dcl_of_an_f_box_leaves_out(self):
        v, _ = view(sd_source('{ f_user_card := "1"; f_image_card := "0"; f_imageplus_card := "0" }\nSHR(\n IN := #i,\n N := #i,\n OUT => #o\n)'))
        self.assertEqual(box(v), ('SHR', 'Word', ['EN', 'IN', 'N'], ['ENO', 'OUT']))
        for name, typ in (('TON', 'Time'), ('CTU', 'Int'), ('CTD', 'Int'), ('CTUD', 'Int')):
            v, _ = view(self.fb(name, 'Contact( #a )\n' + self.CARDS + '#inst.%s(\n pv := #i\n)' % name))
            self.assertEqual(box(v)[:2], (name, typ))

    def test_a_type_the_pragma_does_name_wins(self):
        v, _ = view(self.fb('TON', 'Contact( #a )\n{ f_user_card := "1"; time_type := "LTime" }\n#inst.TON(\n pt := #i\n)'))
        self.assertEqual(box(v)[1], 'LTime')

    def test_a_type_in_s7_templates_beside_the_cards_wins(self):
        for typ, name, template, value in (('TON', 'TON', 'time_type', 'LTime'), ('CTU', 'CTU', 'value_type', 'DInt')):
            v, _ = view(self.fb(typ, 'Contact( #a )\n{ S7_Templates := "%s := %s"; f_user_card := "1"; f_image_card := "0" }\n#inst.%s(\n pv := #i\n)' % (template, value, name)))
            self.assertEqual(box(v)[1], value)
            self.assertEqual(v.el.templates, {template: value})
        v, _ = view(sd_source('{ S7_Templates := "value_type := DWord"; f_user_card := "1" }\nSHR(\n IN := #i\n)'))
        self.assertEqual(box(v)[1], 'DWord')

    def test_a_type_change_beside_the_cards_reads_as_a_change(self):
        pragma = 'Contact( #a )\n{ S7_Templates := "time_type := %s"; f_user_card := "1" }\n#inst.TON(\n pt := #i\n)'
        d = compare_blocks(self.fb('TON', pragma % 'LTime'), self.fb('TON', pragma % 'Time'))
        self.assertEqual(len(d.nets), 1)
        before, _ = view(self.fb('TON', pragma % 'LTime'))
        after, _ = view(self.fb('TON', pragma % 'Time'))
        self.assertEqual((box(before)[1], box(after)[1]), ('LTime', 'Time'))

    def test_only_an_instance_of_the_box_s_own_type_is_filled(self):
        for typ in ('IEC_LTIMER', 'IEC_TIMER', 'TON_LTIME', '"MyTimer"'):
            v, _ = view(self.fb(typ, 'Contact( #a )\n' + self.CARDS + '#inst.TON(\n pt := #i\n)'))
            self.assertEqual(box(v)[1], '', typ)
        v, _ = view(self.fb('Array[0..1] of TON', 'Contact( #a )\n' + self.CARDS + '#inst[0].TON(\n pt := #i\n)'))
        self.assertEqual(box(v)[1], 'Time')

    def test_an_instance_in_a_db_of_its_own_is_not_filled(self):
        v, _ = view(self.fb('TON', 'Contact( #a )\n' + self.CARDS + '"TimerDb".TON(\n pt := #i\n)'))
        self.assertEqual(box(v)[1], '')

    def test_a_standard_box_without_a_template_gets_no_type(self):
        v, _ = view(self.fb('TON', 'Contact( #a )\n#inst.TON(\n pt := #i\n)'))
        self.assertEqual(box(v)[1], '')

    def test_the_type_is_a_template_so_both_formats_compare_alike(self):
        a = self.fb('CTU', 'Contact( #a )\n' + self.CARDS + '#inst.CTU(\n r := #a\n)')
        self.assertEqual(parse_block(a).networks[0].rungs[0].items[-1].templates, {'value_type': 'Int'})

    def test_scale_keeps_the_names_of_the_sections(self):
        v, _ = view(self.fb('SCALE', self.CARDS + '#inst.SCALE(\n in := #i,\n hiLim := #i,\n loLim := #i,\n out => #i,\n out_hi => #a\n)'))
        self.assertEqual(box(v)[2:], (['EN', 'IN', 'HI_LIM', 'LO_LIM'], ['ENO', 'OUT', 'OUT_HI']))

    def test_bo_w_and_w_bo_have_two_types_a_s7dcl_leaves_out(self):
        v, _ = view(sd_source(self.CARDS + 'BO_W(\n IN0 := #a,\n IN15 := #a,\n OUT => #o\n)'))
        self.assertEqual(box(v), ('BO_W', 'Bool to Word', ['EN', 'IN0', 'IN15'], ['ENO', 'OUT']))
        v, _ = view(sd_source(self.CARDS + 'W_BO(\n IN := #o,\n OUT0 => #a,\n OUT15 => #a\n)'))
        self.assertEqual(box(v), ('W_BO', 'Word to Bool', ['EN', 'IN'], ['ENO', 'OUT0', 'OUT15']))
        x, _ = view(xml_source('BO_W', [rail('en'), inp(A, 'IN0'), out(B, 'OUT')], (('src_type', 'Bool'), ('dest_type', 'Word'))))
        self.assertEqual(box(x), ('BO_W', 'Bool to Word', ['EN', 'IN0'], ['ENO', 'OUT']))

    def test_scale_draws_int_scale_d_none(self):
        body = '#inst.%s(\n in := #i,\n out_hi => #a\n)'
        v, _ = view(self.fb('SCALE', self.CARDS + body % 'SCALE'))
        self.assertEqual(box(v)[1], 'Int')
        v, _ = view(self.fb('SCALE_D', self.CARDS + body % 'SCALE_D'))
        self.assertEqual(box(v)[1], '')

    def test_the_f_scale_is_not_the_legacy_scale(self):
        inst = '<Instance Scope="LocalVariable" UId="30"><Component Name="inst" /></Instance>'
        n = cr.NegatedPins('test_taken_away')
        text = n.net('<Part Name="SCALE" UId="%d">%s<TemplateValue Name="value_type" Type="Type">Int</TemplateValue></Part>' % (PART, inst),
                     [rail('en'), inp(A, 'IN'), inp(B, 'HI_LIM'), out(C, 'OUT_HI')], 'LAD')
        v, _ = view(cr._xml_src(text))
        self.assertEqual(v.el.instr, 'SCALE')
        self.assertEqual(box(v), ('SCALE', 'Int', ['EN', 'IN', 'HI_LIM'], ['ENO', 'OUT_HI']))
        x, _ = view(xml_source('SCALE', [rail('en'), inp(A, 'IN'), out(B, 'RET_VAL')]))
        self.assertEqual(x.el.instr, 'S_Scale')

    def test_ack_op_marks_in(self):
        v, _ = view(self.fb('ACK_OP', self.CARDS + '#inst.ACK_OP(\n ACK_ID := #i,\n OUT => #i,\n IN := #i\n)'))
        self.assertEqual(box(v)[2:], (['EN', 'ACK_ID', IO + 'IN'], ['ENO', 'OUT']))


class CallsOfSystemBlocks(unittest.TestCase):
    """A library instruction can export as a call of a block no project export holds. Its in-outs are facts of the catalogue, for an
    instance of that type: written without quotes, where a block of the project has them. The rest of the call stays as it was."""

    SD_CALL = """FUNCTION_BLOCK "Sample"
    VAR
        inst : %s;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            #inst(
                Setpoint := #inst.x,
                Mode := #inst.y,
                State => #inst.z
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
"""
    CALL = ('<Call UId="%d"><CallInfo Name="PID_Compact" BlockType="FB"><Instance Scope="LocalVariable" UId="30"><Component Name="inst" />'
            '</Instance><Parameter Name="Setpoint" Section="Input" Type="Real" /><Parameter Name="Mode" Section="InOut" Type="Int" />'
            '<Parameter Name="State" Section="Output" Type="Int" /></CallInfo></Call>' % PART)
    WIRES = [rail('en'), inp(A, 'Setpoint'), inp(B, 'Mode'), out(C, 'State')]

    def s7dcl(self, typ):
        v, _ = view(BlockSource('Sample', self.SD_CALL % typ, None, 'Sample.s7dcl'))
        return v

    def simaticml(self, typ):
        n = cr.NegatedPins('test_taken_away')
        member = '<Section Name="Static"><Member Name="inst" Datatype="%s" /></Section>' % typ
        text = n.net(self.CALL, self.WIRES, 'LAD').replace('<Section Name="Constant" />', member + '<Section Name="Constant" />', 1)
        self.assertIn(member, text)
        v, _ = view(cr._xml_src(text))
        return v

    def test_the_in_out_of_a_system_block(self):
        for v in (self.s7dcl('PID_Compact'), self.simaticml('PID_Compact')):
            self.assertEqual(box(v), ('"PID_Compact"', '', ['EN', 'Setpoint', IO + 'Mode'], ['ENO', 'State']))

    def test_the_in_outs_of_the_calls_that_got_their_pins_later(self):
        from TiaChangeReports.instructions_communication import CALL_IN_OUTS
        self.assertEqual(CALL_IN_OUTS['FTP_CMD'], ('ARG',))
        self.assertEqual(CALL_IN_OUTS['SinaPara'], ('Parameter',))
        self.assertEqual(CALL_IN_OUTS['AdvancedCmd'], ('CMDREF', 'HW_CONNECT', 'IDENT_DATA'))
        self.assertEqual(CALL_IN_OUTS['Ident_Profile'], ('hw_connect', 'cmdref', 'txref', 'rxref'))
        self.assertEqual(len(CALL_IN_OUTS['EnS_EEm_Report']), 4)

    class Dbs:
        """A snapshot's documents: two DBs of one system block, one of a block of the project."""
        OF = {'db1': 'PID_Compact', 'db2': 'PID_Compact', 'db3': '"MyFb"', 'db4': 'Other_Block'}

        def __call__(self, name):
            return None

        def instance_of(self, name):
            return self.OF.get(name.strip('"').lower())

        def db(self, name):
            return None

    def call_of(self, db, callees=None):
        """The view of a call with a DB of its own, in each format."""
        n = cr.NegatedPins('test_taken_away')
        call = self.CALL.replace('<Instance Scope="LocalVariable" UId="30"><Component Name="inst" />', '<Instance Scope="GlobalVariable" UId="30"><Component Name="%s" />' % db)
        sd = self.SD_CALL.replace('#inst(', '"%s"(' % db) % 'PID_Compact'
        self.assertIn('"%s"(' % db, sd)
        out = []
        for src in (BlockSource('Sample', sd, None, 'Sample.s7dcl'), cr._xml_src(n.net(call, self.WIRES, 'LAD'))):
            blk = parse_block(src)
            net = blk.networks[0]
            lay = Layout(net.rungs, blk.interface, callees, net.label)
            out.append(lay.views[next(i for r in net.rungs for i in r.items if not isinstance(i, tuple) and i.instr == 'CALL').eid])
        return out

    def test_a_db_of_its_own_stands_above_the_block_it_is_the_instance_of(self):
        for v in self.call_of('Db1', self.Dbs()):
            self.assertEqual(v.title, '"PID_Compact"')
            self.assertEqual(v.instlines, ['"Db1"'])
            self.assertEqual(box(v)[2:], (['EN', 'Setpoint', IO + 'Mode'], ['ENO', 'State']))

    def test_a_db_of_a_block_of_the_project(self):
        for v in self.call_of('Db3', self.Dbs()):
            self.assertEqual((v.title, v.instlines), ('"MyFb"', ['"Db3"']))

    def test_with_no_document_of_the_db_its_name_stays_the_title(self):
        for v in self.call_of('Db1') + self.call_of('Unknown', self.Dbs()):
            self.assertEqual(v.instlines, [])
            self.assertIn(v.title, ('"Db1"', '"Unknown"'))

    class OtherBlock(Dbs):
        """The other version of the snapshot: Db1 is the instance of another block now."""
        OF = {'db1': 'Other_Block', 'db3': '"OtherFb"'}

    def layouts(self, db, callees):
        n = cr.NegatedPins('test_taken_away')
        call = self.CALL.replace('<Instance Scope="LocalVariable" UId="30"><Component Name="inst" />', '<Instance Scope="GlobalVariable" UId="30"><Component Name="%s" />' % db)
        sd = self.SD_CALL.replace('#inst(', '"%s"(' % db) % 'PID_Compact'
        out = []
        for src in (BlockSource('Sample', sd, None, 'Sample.s7dcl'), cr._xml_src(n.net(call, self.WIRES, 'LAD'))):
            blk = parse_block(src)
            net = blk.networks[0]
            out.append((Layout(net.rungs, blk.interface, callees, net.label), next(i for r in net.rungs for i in r.items if not isinstance(i, tuple) and i.instr == 'CALL')))
        return out

    def marked(self, before, after):
        """What the after version marks, per format: the layers of its marks, 'box' the head, 'under' the DB above."""
        out = []
        for (la, ea), (lb, eb) in zip(before, after):
            st = 'changed' if ea.call != eb.call else 'same'
            out.append(sorted(m[2] for m in lb.marks({eb.eid: st}, {eb.eid: ea}, 'added', la)))
        return out

    def test_a_db_keeping_its_name_with_its_block_swapped_marks_the_head_not_the_db(self):
        for db in ('Db1', 'Db3'):
            for m in self.marked(self.layouts(db, self.Dbs()), self.layouts(db, self.OtherBlock())):
                self.assertEqual(m, ['box'])

    def test_another_db_of_the_same_block_marks_the_db_not_the_head(self):
        for m in self.marked(self.layouts('Db1', self.Dbs()), self.layouts('Db2', self.Dbs())):
            self.assertEqual(m, ['under'])

    def test_a_db_of_another_block_marks_both(self):
        for m in self.marked(self.layouts('Db1', self.Dbs()), self.layouts('Db4', self.Dbs())):
            self.assertEqual(m, ['box', 'under'])

    def test_a_db_gone_from_the_snapshot_marks_the_head_it_named(self):
        for m in self.marked(self.layouts('Db1', self.Dbs()), self.layouts('Unknown', self.Dbs())):
            self.assertEqual(m, ['box'])

    def test_the_same_db_of_the_same_block_marks_nothing(self):
        for m in self.marked(self.layouts('Db1', self.Dbs()), self.layouts('Db1', self.Dbs())):
            self.assertEqual(m, [])

    def test_a_block_of_the_project_of_that_name_is_no_system_block(self):
        self.assertEqual(box(self.s7dcl('"PID_Compact"'))[2], ['EN', 'Setpoint', 'Mode'])
        self.assertEqual(box(self.simaticml('&quot;PID_Compact&quot;'))[2], ['EN', 'Setpoint', 'Mode'])

    def test_a_system_block_not_in_the_catalogue_stays_as_it_is(self):
        self.assertEqual(box(self.s7dcl('Other_Block'))[2], ['EN', 'Setpoint', 'Mode'])

    def test_a_marked_pin_keeps_its_row_for_the_marks_of_a_change(self):
        for v in (self.s7dcl('PID_Compact'), self.simaticml('PID_Compact')):
            side, row = v.pinrow['mode']
            self.assertEqual((side, v._label(row, v.lefts[row][0])), ('L', IO + 'Mode'))


class SclText(unittest.TestCase):
    NS = 'xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v4"'

    def read(self, inner, lang=None):
        return scl_text(ET.fromstring('<StructuredText %s>%s</StructuredText>' % (self.NS, inner)), lang)

    def test_the_type_of_a_type_check(self):
        self.assertEqual(self.read('<Token Text="=" /><Blank Num="1" /><Access Scope="SystemType"><DataType>Int</DataType></Access>'), '= Int')

    def test_goto_and_its_label(self):
        label = '<Access Scope="Label"><Label Name="target">%s</Label></Access>'
        self.assertEqual(self.read('<Token Text="GOTO" /><Blank Num="1" />' + label % '' + '<Token Text=";" />'), 'GOTO target;')
        self.assertEqual(self.read(label % '<Token Text=":" />'), 'target:')

    def test_a_comment_in_a_line(self):
        c = '<LineComment Inserted="true" NoClosingBracket="false"><Text> note </Text></LineComment>'
        self.assertEqual(self.read(c), '(* note *)')

    def test_a_comment_inside_a_calls_instance(self):
        instance = '<Instance Scope="GlobalVariable"><Component Name="Db" /><LineComment Inserted="true"><Text> note </Text></LineComment></Instance>'
        self.assertEqual(self.read('<Access Scope="Call"><CallInfo Name="Fb" BlockType="FB">%s</CallInfo></Access>' % instance), '"Db" (* note *)')
        self.assertEqual(self.read('<Access Scope="Call"><Instruction Name="TON">%s</Instruction></Access>' % instance), 'TON (* note *)')

    def test_a_line_comment_in_every_form_the_exports_write(self):
        for attrs in ('', ' Inserted="false"', ' Inserted="false" NoClosingBracket="false"'):
            self.assertEqual(self.read('<LineComment%s><Text> note</Text></LineComment>' % attrs), '// note')

    def test_a_multilingual_comment(self):
        c = '<Comment Inserted="true"><MultiLanguageText Lang="de-DE"> Text </MultiLanguageText>' \
            '<MultiLanguageText Lang="en-US"> note </MultiLanguageText></Comment>'
        self.assertEqual(self.read(c), '(/* note */)')
        self.assertEqual(self.read(c, 'de-DE'), '(/* Text */)')

    def test_another_comment_text_is_another_body(self):
        self.assertNotEqual(self.read('<Comment><MultiLanguageText Lang="en-US">a</MultiLanguageText></Comment>'),
                            self.read('<Comment><MultiLanguageText Lang="en-US">b</MultiLanguageText></Comment>'))

    def test_tia_writes_a_parameter_port_in_quotes(self):
        call = '<Parameter Name="%s" UId="39"><Token Text=":=" /></Parameter>'
        self.assertEqual(self.read(call % 'PORT'), '"PORT":=')
        self.assertEqual(self.read(call % 'BAUD'), 'BAUD:=')

    def test_an_address(self):
        self.assertEqual(self.read('<Access Scope="Address"><Address Area="Timer" Type="Timer" BitOffset="11" /></Access>'), '%T11')

    def test_an_informative_address_in_a_symbol_stays_out(self):
        acc = '<Access Scope="GlobalVariable"><Symbol><Component Name="DB"><BooleanAttribute Name="HasQuotes">true</BooleanAttribute></Component>' \
              '<Token Text="." /><Component Name="x" /><Address Area="None" Type="Bool" BlockNumber="58" BitOffset="64" Informative="true" /></Symbol></Access>'
        self.assertEqual(self.read(acc), '"DB".x')

    def test_a_s7dcl_writes_the_same_comment(self):
        sd = '''FUNCTION_BLOCK "Sample"
    { S7_Language := "SCL" }
    NETWORK
        { S7_MLC := "MLC_a" } #x := 1;
    END_NETWORK
END_FUNCTION_BLOCK
'''
        res = 'MultiLingualTexts:\n  - id: MLC_a\n    en-US: " note "\n'
        body = parse_block(BlockSource('Sample', sd, res, 'Sample.s7dcl')).networks[0].body
        self.assertEqual(body.strip(), '(/* note */) #x := 1;')


class StlText(unittest.TestCase):
    NS = 'xmlns="http://www.siemens.com/automation/Openness/SW/NetworkSource/StatementList/v5"'
    LOCAL = '<Access Scope="LocalVariable"><Symbol><Component Name="%s" /></Symbol></Access>'

    def read(self, inner):
        return stl_text(ET.fromstring('<StatementList %s>%s</StatementList>' % (self.NS, inner)))

    def test_a_statement_a_line(self):
        self.assertEqual(self.read('<StlStatement><StlToken Text="A" />%s</StlStatement><StlStatement><StlToken Text="Assign" />%s</StlStatement>'
                                   % (self.LOCAL % 'in', self.LOCAL % 'out')), 'A #in\nAssign #out')

    def test_comment_and_empty_lines(self):
        self.assertEqual(self.read('<StlStatement><LineComment Inserted="false"><Text> note</Text></LineComment><StlToken Text="COMMENT" /></StlStatement>'
                                   '<StlStatement><StlToken Text="EMPTY_LINE" /></StlStatement>'), '// note\n')

    def test_a_call_with_its_parameters(self):
        call = '<StlStatement><StlToken Text="CALL" /><Access Scope="Call"><Instruction Name="Move"><Parameter Name="in">%s</Parameter></Instruction></Access></StlStatement>'
        self.assertEqual(self.read(call % (self.LOCAL % 'x')), 'CALL Move\n    in #x')

    def test_an_operand_keeps_its_structure(self):
        def operand(comps):
            return '<StlStatement><StlToken Text="A" /><Access Scope="LocalVariable"><Symbol>%s</Symbol></Access></StlStatement>' % comps
        indexed = operand('<Component Name="a"><Access Scope="LiteralConstant"><Constant><ConstantValue>1</ConstantValue></Constant></Access></Component>')
        plain = operand('<Component Name="a1" />')
        member = operand('<Component Name="a" /><Component Name="b" />')
        joined = operand('<Component Name="ab" />')
        self.assertEqual(self.read(indexed), 'A #a[1]')
        self.assertEqual(self.read(plain), 'A #a1')
        self.assertEqual(self.read(member), 'A #a.b')
        self.assertEqual(self.read(joined), 'A #ab')

    def test_a_global_operand_with_an_index_operand(self):
        st = '<StlStatement><StlToken Text="A" /><Access Scope="GlobalVariable"><Symbol><Component Name="DB" /><Component Name="fg" AccessModifier="Array">' \
             '<Access Scope="LocalVariable"><Symbol><Component Name="i" /></Symbol></Access></Component><Component Name="run" /></Symbol></Access></StlStatement>'
        self.assertEqual(self.read(st), 'A "DB".fg[#i].run')

    def test_a_network_of_a_block_reads_it(self):
        n = cr.NegatedPins('test_taken_away')
        text = re.sub(r'<FlgNet .*?</FlgNet>', lambda m: '<StatementList %s><StlStatement><StlToken Text="L" />%s</StlStatement></StatementList>' % (self.NS, self.LOCAL % 'in'),
                      n.net('', [], 'STL'), count=1, flags=re.S)
        self.assertEqual(parse_block(cr._xml_src(text)).networks[0].body, 'L #in')

    NOTE = '<LineComment Inserted="false"><Text>some comment</Text></LineComment>'

    def statement(self, token, access):
        return '<StlStatement><StlToken Text="%s" />%s</StlStatement>' % (token, access)

    def noted(self, name, note=NOTE):
        return (self.LOCAL % name).replace('</Access>', note + '</Access>')

    def test_a_comment_inside_an_operand(self):
        self.assertEqual(self.read(self.statement('A', self.noted('in'))), 'A #in //some comment')

    def test_a_comment_inside_a_literal_operand(self):
        literal = '<Access Scope="LiteralConstant"><Constant><ConstantValue>5</ConstantValue></Constant>%s</Access>' % self.NOTE
        self.assertEqual(self.read(self.statement('L', literal)), 'L 5 //some comment')

    def test_a_comment_inside_an_index_operand(self):
        access = '<Access Scope="LocalVariable"><Symbol><Component Name="a">%s</Component></Symbol></Access>' % self.noted('i')
        self.assertEqual(self.read(self.statement('A', access)), 'A #a[#i] //some comment')

    def test_a_comment_inside_a_parameter_operand(self):
        call = '<Access Scope="Call"><Instruction Name="Move"><Parameter Name="in">%s</Parameter></Instruction></Access>' % self.noted('x')
        self.assertEqual(self.read(self.statement('CALL', call)), 'CALL Move\n    in #x //some comment')

    def test_a_comment_inserted_in_an_operand(self):
        note = '<LineComment Inserted="true"><Text> note </Text></LineComment>'
        self.assertEqual(self.read(self.statement('A', self.noted('in', note))), 'A #in (* note *)')

    def test_a_multilingual_comment_inside_an_operand(self):
        note = '<Comment Inserted="true"><MultiLanguageText Lang="en-US"> note </MultiLanguageText></Comment>'
        self.assertEqual(self.read(self.statement('A', self.noted('in', note))), 'A #in (/* note */)')

    INSTANCE = '<Component Name="Db" />'
    NOTED_INSTANCES = (INSTANCE + NOTE, '<Component Name="Db">%s</Component>' % NOTE)     # in the Instance, in its Component

    def call_of_instance(self, instance, parameters=''):
        return self.statement('CALL', '<Access Scope="Call"><CallInfo Name="Fb" BlockType="FB"><Instance Scope="GlobalVariable">%s</Instance>%s</CallInfo></Access>' % (instance, parameters))

    def call_of_instruction(self, instance, parameters=''):
        return self.statement('CALL', '<Access Scope="Call"><Instruction Name="TON"><Instance Scope="GlobalVariable">%s</Instance>%s</Instruction></Access>' % (instance, parameters))

    def test_a_comment_inside_a_calls_instance(self):
        for noted in self.NOTED_INSTANCES:
            self.assertEqual(self.read(self.call_of_instance(noted)), 'CALL "Db" //some comment')
            self.assertEqual(self.read(self.call_of_instruction(noted)), 'CALL TON //some comment')

    def test_a_comment_inside_a_calls_instance_stands_on_the_line_of_the_call(self):
        parameter = '<Parameter Name="in">%s</Parameter>' % (self.LOCAL % 'x')
        for noted in self.NOTED_INSTANCES:
            self.assertEqual(self.read(self.call_of_instance(noted, parameter)), 'CALL "Db" //some comment\n    in #x')
            self.assertEqual(self.read(self.call_of_instruction(noted, parameter)), 'CALL TON //some comment\n    in #x')

    def compared(self, before, after):
        n = cr.NegatedPins('test_taken_away')

        def block(statements):
            net = '<StatementList %s>%s</StatementList>' % (self.NS, statements)
            return cr._xml_src(re.sub(r'<FlgNet .*?</FlgNet>', lambda m: net, n.net('', [], 'STL'), count=1, flags=re.S))
        return compare_blocks(block(before), block(after))

    def test_the_report_shows_a_comment_added_inside_an_instance(self):
        """Alone it read as the tag and no text."""
        for call in (self.call_of_instance, self.call_of_instruction):
            for noted in self.NOTED_INSTANCES:
                d = self.compared(call(self.INSTANCE), call(noted))
                p = d.nets[0]
                self.assertEqual((d.state, p.state, p.not_shown), ('changed', 'changed', False))
                self.assertIn('//some comment', p.after.body)
                self.assertIn('//some comment', cr._text(render([d], 'b', 'a')))

    def test_the_report_shows_a_comment_added_inside_an_instance_beside_another_changed_line(self):
        """With another line changed it was on no page, and no tag told of it."""
        before, after = self.statement('A', self.LOCAL % 'in'), self.statement('A', self.LOCAL % 'other')
        for call in (self.call_of_instance, self.call_of_instruction):
            for noted in self.NOTED_INSTANCES:
                d = self.compared(before + call(self.INSTANCE), after + call(noted))
                self.assertEqual((d.state, d.nets[0].not_shown), ('changed', False))
                page = cr._text(render([d], 'b', 'a'))
                self.assertIn('A #other', page)
                self.assertIn('//some comment', page)

    def test_the_report_shows_a_comment_added_inside_an_operand(self):
        """As TIA exported it: the line differs and holds the text; the network is not told as not shown."""
        d = self.compared(self.statement('A', self.LOCAL % 'someInput'), self.statement('A', self.noted('someInput')))
        p = d.nets[0]
        self.assertEqual((d.state, p.state, p.not_shown), ('changed', 'changed', False))
        self.assertEqual((p.before.body, p.after.body), ('A #someInput', 'A #someInput //some comment'))
        self.assertIn('A #someInput //some comment', cr._text(render([d], 'b', 'a')))


if __name__ == '__main__':
    unittest.main()
