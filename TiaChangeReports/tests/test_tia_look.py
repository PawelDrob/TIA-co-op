"""The drawing as TIA draws it at 100%, checked against TIA screenshots; the cases of those networks (a
call box, R_TRIG, compare contacts, SR, TON, a branch from the node where another one ends) are in fixtures\\plant, an
example machine of our own. From the repo root: python -m unittest discover -s TiaChangeReports/tests -t .
"""
import os
import tempfile
import unittest

from TiaChangeReports.compare import Callees
from TiaChangeReports.render_lad import C_CMT, C_CST, C_DEF, C_VAL, LINE, Layout, display_operand, operand_lines
from TiaChangeReports.s7dcl import parse_block
from TiaChangeReports.source import BlockSource, FolderSnapshot, from_file
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
        self.assertLess(abs(row['#PH_FINE'] - row['#"OIL"']), 20)
        self.assertEqual(check(lay), [])

    def test_sr_and_ton_nw3_nw4(self):
        sr = _view(self.lay(self.pfd, 3), 'S_SR')
        self.assertEqual((sr.title, sr.instlines), ('SR', ['#ioHw.AtNeck']))
        self.assertEqual([n for n, _ in sr.lefts], ['S', 'R1'])
        ton = _view(self.lay(self.pfd, 4), 'TON')
        self.assertEqual((ton.title, ton.sub), ('TON', 'Time'))
        self.assertEqual(dict(ton.rights)['ET'], [('T#0ms', C_DEF, False)])


if __name__ == '__main__':
    unittest.main()
