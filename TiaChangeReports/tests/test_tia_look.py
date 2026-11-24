"""The drawing as TIA draws it at 100%, checked against TIA screenshots; the cases of those networks (a
call box, R_TRIG, compare contacts, SR, TON, a branch from the node where another one ends) are in fixtures\\plant, an
example machine of our own. From the repo root: python -m unittest discover -s TiaChangeReports/tests -t .
"""
import os
import re
import tempfile
import unittest

from TiaChangeReports.compare import Callees
from TiaChangeReports.render_lad import (C_CMT, C_CST, C_DEF, C_VAL, END_H, END_IN, END_W, LINE, STUB, X0, Layout,
                                         display_operand, operand_lines)
from TiaChangeReports.s7dcl import parse_block
from TiaChangeReports.source import BlockSource, FolderSnapshot, from_file
from TiaChangeReports.tests.test_change_reports import FIXTURE_SD, _fixture, _xml_src
from TiaChangeReports.verify import check

V1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'plant', 'v1')

CALLEE = '''{
    S7_BlockComment := "Drives one motor.";
    S7_BlockNumber := "7"
}
FUNCTION_BLOCK "Drive"
    VAR_INPUT
        start : Bool;
        speed : Int;
        fast : Bool;
        ramp : Time := T#2s;
        cfg : _.Cfg_UDT;
    END_VAR
    VAR_OUTPUT
        busy : _.Long_UDT;
        state : Int;
    END_VAR
    VAR_IN_OUT
        cmd : Int;
        data : Int;
    END_VAR
END_FUNCTION_BLOCK
'''
CALLER = '''FUNCTION_BLOCK "Caller"
    VAR
        { S7_MLC := "MLC_i" }
        inst2 : _.Drive;
        inst : _.Drive;
        a : Bool;
        b : Bool;
        c : Int;
        d : Int;
        q : Bool;
        tq : Bool;
        t : TON_TIME;
        "Type" : Int;
        "x+y" : Int;
    END_VAR
    VAR CONSTANT
        "NULL" : Int := 0;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            #inst(
                speed := 5,
                start := wire#w1,
                fast :=  ,
                ramp :=  ,
                cfg :=  ,
                cmd := #c,
                data := #d,
                busy => "Some_DB".A_very_long_operand_name.that_wraps[#c].over_three_lines.DriveCmd,
                state => #d
            )
        END_RUNG
        RUNG wire#powerrail
            Contact( #b )
        END_RUNG wire#w1
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            { S7_Templates := "time_type := Time" }
            #t.TON(
                pt := t#1100ms,
                et =>
            )
            Coil( #tq )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            #inst2(
                cmd := #c,
                data := #d
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''
CALLER_RES = '''MultiLingualTexts:
  - id: MLC_i
    en-US: second drive
'''


def _write(root, files):
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)


def _layouts(with_callee=True):
    with tempfile.TemporaryDirectory() as d:
        _write(d, {'Caller.s7dcl': CALLER, 'Caller.s7res': CALLER_RES, 'Drive.s7dcl': CALLEE})
        callees = Callees(FolderSnapshot(d)) if with_callee else None
        b = parse_block(BlockSource('Caller', CALLER, CALLER_RES, 'Caller'))
        lays = [Layout(n.rungs, b.interface, callees) for n in b.networks]
        if callees:
            callees('Drive')                                   # load while the folder exists
        return lays


def _view(lay, instr='CALL'):
    return next(v for v in lay.views.values() if v.el.instr == instr)


def _texts(lines):
    return [s for s, _, _ in lines]


class CallBox(unittest.TestCase):
    """A call box: pin sides and rows from the called interface, defaults, head and comments."""

    def test_in_outs_on_the_left_below_the_inputs(self):
        v = _view(_layouts()[0])
        self.assertEqual([n for n, _ in v.lefts], ['EN', 'start', 'speed', 'fast', 'ramp', 'cfg', 'cmd', 'data'])
        self.assertEqual([n for n, _ in v.rights], ['ENO', 'busy', 'state'])
        self.assertEqual(v.inouts, {6, 7})
        self.assertEqual(_texts(v.lefts[6][1]), ['#c'])

    def test_right_side_rows_independent_of_the_left(self):
        v = _view(_layouts()[0])
        busy = len(v.rights[1][1])
        self.assertGreaterEqual(busy, 2)
        self.assertEqual(v.rowy_r[1], busy * LINE + 5)          # operand fits between ENO and the pin
        self.assertEqual(v.rowy_r[2], v.rowy_r[1] + 18)
        self.assertGreater(v.rowy[1], v.rowy_r[1])              # 'start' moved down to its logic, outputs not

    def test_unassigned_inputs_show_their_default_in_gray(self):
        v = _view(_layouts()[0])
        rows = dict(v.lefts)
        self.assertEqual(rows['fast'], [('false', C_DEF, False)])
        self.assertEqual(rows['ramp'], [('T#2s', C_DEF, False)])
        self.assertEqual(rows['cfg'], [('...', C_DEF, False)])

    def test_header_number_title_and_block_comment(self):
        v = _view(_layouts()[0])
        self.assertEqual(v.title, '"Drive"')
        self.assertEqual(v.number, '%FB7')
        self.assertEqual(_texts(v.cmtlines), ['Drives one motor.'])
        self.assertEqual(v.instlines, ['#inst'])

    def test_instance_comment_before_the_block_comment(self):
        v = _view(_layouts()[2])
        self.assertEqual(_texts(v.cmtlines), ['second drive'])

    def test_without_the_called_block(self):
        v = _view(_layouts(False)[0])
        self.assertEqual(v.title, '"Drive"')
        self.assertEqual(v.number, '')
        self.assertEqual(v.cmtlines, [])
        self.assertEqual(v.inouts, set())
        self.assertEqual(rows_of(v), ['EN', 'speed', 'start', 'fast', 'ramp', 'cfg', 'cmd', 'data'])

    def test_drawn_and_read_back(self):
        lays = _layouts()
        for lay in lays:
            self.assertEqual(check(lay), [])
        svg = lays[0].svg()
        self.assertIn('>%FB7</text>', svg)
        self.assertIn('>⇌cmd</text>', svg)
        self.assertNotIn('>⇌cmd</text>', svg.replace('>⇌cmd</text>', '', 1))   # once: left side only


def rows_of(v):
    return [n for n, _ in v.lefts]


class Operands(unittest.TestCase):
    def setUp(self):
        self.itf = parse_block(BlockSource('Caller', CALLER, CALLER_RES, 'Caller')).interface

    def test_literals_blue(self):
        self.assertEqual(operand_lines('TRUE', self.itf, 200), [('TRUE', C_CST, False)])
        self.assertEqual(operand_lines('t#1100ms', self.itf, 200), [('t#1100ms', C_CST, False)])

    def test_constant_value_teal_name_blue_unquoted(self):
        self.assertEqual(operand_lines('#"NULL"', self.itf, 200), [('0', C_VAL, False), ('#NULL', C_CST, False)])

    def test_quotes_only_where_tia_shows_them(self):
        self.assertEqual(display_operand('#ioFillData.Config."Type"'), '#ioFillData.Config.Type')
        self.assertEqual(display_operand('#"LT"'), '#LT')
        self.assertEqual(display_operand('#"instFiller+P1"'), '#"instFiller+P1"')
        self.assertEqual(display_operand('"BayData".Bay[3]."to"'), '"BayData".Bay[3].to')
        self.assertEqual(display_operand('"HmiAlarmBuffer"'), '"HmiAlarmBuffer"')
        self.assertEqual(display_operand('#a[#"Type", 2]'), '#a[#Type, 2]')

    def test_long_operands_break_like_tia(self):
        from TiaChangeReports.render_lad import CELL, wrap
        self.assertEqual(wrap('#statService[2].SuppressAlarmOutput', CELL - 20),
                         ['#statService[2].SuppressAlarm', 'Output'])                    # at a word in the name
        self.assertEqual(wrap('"LineData".Station[11].ModeNow.Maintenance', CELL - 20),
                         ['"LineData".Station[11].ModeNow.', 'Maintenance'])

    def test_timer_elapsed_time_unassigned(self):
        v = _view(_layouts()[1], 'TON')
        self.assertEqual(dict(v.rights)['ET'], [('T#0ms', C_DEF, False)])


class AgainstTia(unittest.TestCase):
    """The cases of the TIA screenshots in the fixture project's own networks, the project as the snapshot (UDTs in
    library/types and plc/types)."""

    @classmethod
    def setUpClass(cls):
        cls.callees = Callees(FolderSnapshot(V1))
        base = os.path.join(V1, 'plc', 'blocks')
        cls.pfd = parse_block(from_file(os.path.join(base, 'Bottling', 'PrepareFillData.s7dcl')))
        cls.bay = parse_block(from_file(os.path.join(base, 'Lines', 'Bay4.s7dcl')))

    def lay(self, blk, nw):
        n = next(n for n in blk.networks if n.index == nw)
        return Layout(n.rungs, blk.interface, self.callees)

    def test_network_numbers_as_in_tia(self):
        titles = {n.index: n.title for n in self.pfd.networks}
        self.assertEqual(titles[2], 'Detect head down')
        self.assertEqual(titles[3], 'Set/Reset "AtNeck"')
        self.assertEqual(titles[4], 'Settle delay')

    def test_filler_call_nw1(self):
        lay = self.lay(self.bay, 1)
        v = next(v for v in lay.views.values() if v.el.instr == 'CALL' and 'Filler' in v.title)
        filler = list(self.callees('Filler').root.children.values())
        ins = [m.name for m in filler if m.section == 'INPUT']
        ios = [m.name for m in filler if m.section == 'IN_OUT']
        self.assertEqual(rows_of(v), ['EN'] + ins + ios)
        self.assertEqual([n for n, _ in v.rights], ['ENO', 'oValve', 'oPump', 'oPhase'])
        self.assertEqual((v.number, v.title), ('%FB742', '"Filler"'))
        self.assertEqual(' '.join(_texts(v.cmtlines)), 'Fills one container.')
        self.assertEqual(dict(v.lefts)['iRinse'], [('false', C_DEF, False)])
        self.assertEqual(dict(v.lefts)['iAutoMode'], [('TRUE', C_CST, False)])
        self.assertEqual(check(lay), [])

    def test_r_trig_q_below_eno_nw2(self):
        lay = self.lay(self.pfd, 2)
        v = next(v for v in lay.views.values() if v.el.instr == 'R_TRIG')
        self.assertEqual([n for n, _ in v.lefts], ['EN', 'CLK'])
        self.assertEqual([n for n, _ in v.rights], ['ENO', 'Q'])
        self.assertEqual(v.rowy_r[1], 18)                      # Q right under ENO, CLK on the logic's row
        self.assertGreater(v.rowy[1], v.rowy_r[1])
        self.assertEqual(check(lay), [])

    def test_compare_contacts_nw2(self):
        # the UDT of ioFillData is not in the input: no comment above Config.Type (the fallback)
        lay = self.lay(self.pfd, 2)
        cmp = [v for v in lay.views.values() if v.el.kind == 'compare']
        self.assertEqual(_texts(cmp[0].top), ['#ioFillData.Config.Type'])
        self.assertEqual(cmp[0].bot, [('2', C_VAL, False), ('Syrup', C_CMT, True), ('#R_SYRUP', C_CST, False)])

    def test_filler_nw4_fine_beside_the_oil_branch(self):
        # the PH_FINE branch (from the node where the OIL branch ends) sits level with that branch, not below it
        filler = os.path.join(V1, 'library', 'types', 'Bottling', 'Filler.released', 'Filler.s7dcl')
        lay = self.lay(parse_block(from_file(filler)), 4)
        row = {}
        for k, i in enumerate(lay.info):
            for p in i['placed']:
                if not isinstance(p[0], str) and p[0].kind == 'compare':
                    row.setdefault(dict((n, v) for n, _, v in p[0].params)['in2'], lay.ys[k])
        self.assertLess(abs(row['#PH_FINE'] - row['#OIL']), 20)
        self.assertEqual(check(lay), [])

    def test_sr_and_ton_nw3_nw4(self):
        sr = _view(self.lay(self.pfd, 3), 'S_SR')
        self.assertEqual((sr.title, sr.instlines), ('SR', ['#ioHw.AtNeck']))
        self.assertEqual([n for n, _ in sr.lefts], ['S', 'R1'])
        ton = _view(self.lay(self.pfd, 4), 'TON')
        self.assertEqual((ton.title, ton.sub), ('TON', 'Time'))
        self.assertEqual(dict(ton.rights)['ET'], [('T#0ms', C_DEF, False)])


ENDS = '''FUNCTION_BLOCK "Ends"
    VAR
        a : Bool;
        b : Bool;
        q : Bool;
        r : Bool;
        n : Int;
        m : Int;
        instTrig : R_TRIG;
        instTp : TP_TIME;
        t : Time;
        et : Time;
    END_VAR
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            Coil( #q )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            R_Coil( #r )
            Coil( #q )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            wire#w1
            Coil( #q )
        END_RUNG
        RUNG wire#w1
            S_Coil( #r )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            Move(
                in := #n,
                out1 => #m
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            wire#w1
            Coil( #q )
        END_RUNG
        RUNG wire#w1
            Move(
                in := #n,
                out1 => #m
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            JumpList(
                k := #n,
                dst0 => lblA,
                dst1 => lblB
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            {
                S7_Templates := "SrcType := Int";
                CASE0 := "==";
            }
            Switch(
                k := #n,
                case0 := #m,
                else => lblC,
                dst0 => lblA
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            JumpCoil( lblA )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            I_JumpCoil( lblB )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            ReturnCoil( #b )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        Label(lblA)
        RUNG wire#powerrail
            Coil( #q )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            wire#w1
            S_Coil( #q )
        END_RUNG
        RUNG wire#w1
            R_Coil( #r )
        END_RUNG
        RUNG wire#powerrail
            Contact( #b )
            Coil( #r )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            #instTrig.R_TRIG(
                clk := #a,
                q => #q
            )
        END_RUNG
    END_NETWORK
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire#powerrail
            Contact( #a )
            { S7_Templates := "time_type := Time" }
            #instTp.TP(
                pt := #t,
                et => #et
            )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
'''


def _ends_block():
    """ENDS read from .s7dcl."""
    return parse_block(BlockSource('Ends', ENDS, '', 'Ends.s7dcl'))


CONTROL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'zzLadControl.xml')


def _empty_network():
    """The SimaticML fixture with its first network emptied, as TIA exports a network with nothing in it."""
    text = _fixture()
    i, j = text.index('<NetworkSource><FlgNet'), text.index('</FlgNet></NetworkSource>') + 25
    return text[:i] + '<NetworkSource />' + text[j:]


def _wires_at(svg, y):
    """(x1, x2) of every black line drawn along y."""
    out = []
    for m in re.finditer(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" stroke="#1a1a1a"', svg):
        x1, y1, x2, y2 = map(float, m.groups())
        if abs(y1 - y) < .06 and abs(y2 - y) < .06:
            out.append((min(x1, x2), max(x1, x2)))
    return out


def _bars(svg):
    """(right edge, wire y) of every end mark drawn."""
    return [(float(x) + float(w), float(y) + float(h) / 2) for x, y, w, h in
            re.findall(r'<rect class="end" x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"', svg)]


class RungEndsLikeTia(unittest.TestCase):
    """A rung's end as TIA draws it (TIA's screen at 100%: zzBenEnds, zzBenContacts, zzLadControl, zzLadConvert,
    zzLadBitLogic, zzLadTimer): a rung that runs to the network's end stops END_IN short of its last cell and closes
    with a bar END_H tall and END_W wide, its right edge where the wire ends; an open ENO below the top rung ends STUB
    past its box with the same bar; a box without ENO ends at its box, with nothing after it."""

    @classmethod
    def setUpClass(cls):
        b = _ends_block()
        cls.nets = {n.index: Layout(n.rungs, b.interface, label=n.label) for n in b.networks}

    def assert_ends(self, lay, want):
        """want: [(x, y)] of the rung ends, in rung order; every one drawn as a bar, no wire on its rung past it, and
        the drawing reads back as the code."""
        self.assertEqual([(round(x, 1), y) for x, y in lay.ends()], [(round(x, 1), y) for x, y in want])
        svg = lay.svg()
        self.assertEqual(sorted((round(x, 1), round(y, 1)) for x, y in _bars(svg)),
                         sorted((round(x, 1), round(y, 1)) for x, y in want))
        for x, y in want:
            wires = _wires_at(svg, y)
            self.assertTrue(any(abs(x2 - x) < .06 for _, x2 in wires), (x, y, wires))        # the wire ends at the bar
            self.assertFalse([w for w in wires if w[1] > x + .06], (x, y))                  # and nothing runs past it
        self.assertEqual(check(lay), [])

    def network_end(self, lay):
        return lay.right - END_IN

    def test_the_bar(self):
        self.assertEqual((END_IN, END_H, END_W, STUB), (5.4, 5.4, 1.8, 41))
        lay = self.nets[1]
        x, y = lay.ends()[0]
        self.assertIn('<rect class="end" x="%.1f" y="%.1f" width="1.8" height="5.4" fill="#1a1a1a"/>'
                      % (x - END_W, y - END_H / 2), lay.svg())

    def test_one_coil(self):
        lay = self.nets[1]
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])
        coil = _view(lay, 'Coil')
        self.assertEqual(lay._elx(coil.el.eid) + coil.w, lay.right)                    # the bar inside the coil's cell

    def test_coils_in_a_row(self):
        lay = self.nets[2]
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])

    def test_a_coil_on_a_branch_below(self):
        lay = self.nets[3]
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[0]), (self.network_end(lay), lay.ys[1])])

    def test_an_open_eno_in_the_top_rung(self):
        lay = self.nets[4]
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])

    def test_an_open_eno_below(self):
        lay = self.nets[5]
        mv = _view(lay, 'Move')
        stub = lay._elx(mv.el.eid) + mv.lw + mv.bw + STUB
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[0]), (stub, lay.ys[1])])

    def test_a_box_without_eno(self):
        for nw in (6, 7):
            with self.subTest(nw):
                self.assert_ends(self.nets[nw], [])

    def test_jump_and_return_coils(self):
        for nw in (8, 9, 10):
            with self.subTest(nw):
                lay = self.nets[nw]
                self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])

    def test_a_coil_under_a_jump_label(self):
        lay = self.nets[11]
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])
        self.assertIn('translate(', lay.svg().split('<rect class="end"')[0])           # inside the label's shift

    def test_several_rungs_from_the_rail(self):
        lay = self.nets[12]
        self.assert_ends(lay, [(self.network_end(lay), lay.ys[k]) for k in range(3)])

    def test_an_edge_or_timer_box_with_its_rung_output_open(self):
        """TIA's picture (zzLadBitLogic NW18, NW19; zzLadTimer NW1, NW3 with the coil after the box removed): an
        R_TRIG's open ENO and a TP's open Q run to the network's end and close with the bar, as a coil's rung."""
        for nw, instr in ((13, 'R_TRIG'), (14, 'TP')):
            with self.subTest(instr):
                lay = self.nets[nw]
                self.assertTrue(_view(lay, instr))
                self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])

    def test_an_empty_network(self):
        for rungs in ([], parse_block(_xml_src(_empty_network())).networks[0].rungs):
            lay = Layout(rungs, None)
            self.assert_ends(lay, [(self.network_end(lay), lay.ys[0])])
            self.assertEqual(_wires_at(lay.svg(), lay.ys[0]), [(X0, self.network_end(lay))])

    def test_simaticml_from_tia(self):
        """TIA's own export of zzLadControl: RET, an empty network, JMP, JMPN, a jump label with a coil; JMP_LIST and
        SWITCH without one."""
        b = parse_block(from_file(CONTROL))
        for n in b.networks:
            with self.subTest(n.index):
                lay = Layout(n.rungs, b.interface, label=n.label)
                self.assert_ends(lay, [] if n.index in (6, 7) else [(self.network_end(lay), lay.ys[0])])

    def test_both_formats_alike(self):
        """The fixture's networks from SimaticML and from .s7dcl: a coil, a coil on a branch, a box on the rail. Only
        the rows differ, as SimaticML's operands carry comments."""
        xml, sd = parse_block(_xml_src()), parse_block(BlockSource('Main', FIXTURE_SD, None, 'Main.s7dcl'))

        def ends(lay):
            rows = sorted(set(lay.ys.values()))
            return [(round(x, 1), rows.index(y)) for x, y in lay.ends()]
        for nx, ns in zip(xml.networks, sd.networks):
            with self.subTest(nx.index):
                lx, ls = Layout(nx.rungs, xml.interface), Layout(ns.rungs, sd.interface)
                self.assertTrue(ends(lx))
                self.assertEqual(ends(lx), ends(ls))
                self.assertEqual(len(_bars(lx.svg())), len(ends(lx)))

    def test_in_the_block_viewer(self):
        from TiaChangeReports.viewer import view
        with tempfile.TemporaryDirectory() as d:
            _write(d, {'Ends.s7dcl': ENDS})
            html, _ = view.page(os.path.join(d, 'Ends.s7dcl'))
        self.assertEqual(html.count('<rect class="end"'), sum(len(lay.ends()) for lay in self.nets.values()))
        html, _ = view.page(CONTROL)
        self.assertEqual(html.count('<rect class="end"'), 7)

    def test_no_diff_mark_on_the_run_or_the_bar(self):
        """An added coil is filled over its cell, as before; the run past a box to the network's end carries no mark."""
        lay = self.nets[4]
        mv = _view(lay, 'Move')
        marks = lay.marks({mv.el.eid: 'added', _view(lay, 'Contact').el.eid: 'added'}, {})
        x, y = lay.ends()[0]
        self.assertFalse([m for m in marks if m[3] < x <= m[3] + m[5] and m[4] <= y <= m[4] + m[6]])


class EndMarkChecked(unittest.TestCase):
    """verify.check: an end mark where no wire ends, or touching a line other than the end of the one it closes, would
    read as a cut or a junction; one in an element of another rung would cover its texts."""

    def moved(self, lay, k, to):
        """The layout with its k-th end mark at to."""
        marks = lay.ends()
        marks[k] = to
        lay.ends = lambda: marks
        return check(lay)

    def test_a_bar_on_a_wire(self):
        lay = Layout([], None)
        x, y = lay.ends()[0]
        self.assertEqual(check(lay), [])
        self.assertIn('end mark on a line at (%.0f, %.0f)' % (x - 100, y), self.moved(lay, 0, (x - 100, y)))

    def test_a_bar_at_no_wires_end(self):
        b = _ends_block()
        for nw, k in ((0, 0), (4, 1)):                                    # a coil's run, an open ENO's stub below
            with self.subTest(nw):
                lay = Layout(b.networks[nw].rungs, b.interface)
                x, y = lay.ends()[k]
                self.assertEqual(check(lay), [])
                self.assertEqual(self.moved(lay, k, (x - 20, y)),
                                 ["end mark at no wire's end at (%.0f, %.0f)" % (x - 20, y)])

    def test_a_bar_on_a_vertical_connector(self):
        b = _ends_block()
        lay = Layout(b.networks[2].rungs, b.interface)                    # the coil on a branch below
        (_, y0), (x, y1) = lay.ends()
        vx = lay.x[lay.g.find(lay.info[1]['s'])]
        self.assertEqual(check(lay), [])
        for to in ((vx, (y0 + y1) / 2), (vx + END_W / 2, y1)):        # on the connector, and at its foot
            self.assertIn('end mark on a line at (%.0f, %.0f)' % to, self.moved(lay, 1, to))

    def test_a_bar_in_an_element_of_another_rung(self):
        b = _ends_block()
        lay = Layout(b.networks[2].rungs, b.interface)
        (x, y0), _ = lay.ends()
        self.assertTrue([p for p in self.moved(lay, 1, (x, y0 + 12)) if p.startswith('end mark in Coil(')])


if __name__ == '__main__':
    unittest.main()
