"""The window's model with no window and no process: the run's state from the runner's event lines, and its texts."""
import json
import sys
import unittest
from datetime import datetime, timedelta

from TiaArchiveCompare.runner import VERSION
from TiaArchiveCompare.window.model import TITLE, RunModel, StepState, format_ms

T0 = datetime(2026, 10, 30, 12, 0, 0)


def later(seconds):
    return T0 + timedelta(seconds=seconds)


def line(**event):
    return json.dumps(event)


def planned():
    m = RunModel()
    m.start(T0)
    m.apply(line(t='plan', steps=[{'id': 'checkA', 'text': 'Check this PC'},
                                  {'id': 'openA', 'text': 'Unpack and open archive A'},
                                  {'id': 'exportA', 'text': 'Export project A'},
                                  {'id': 'report', 'text': 'Compare and write the report'}]), T0)
    return m


class Steps(unittest.TestCase):
    def test_the_model_needs_no_window(self):
        self.assertNotIn('tkinter', sys.modules)

    def test_plan_fills_pending_steps(self):
        m = planned()
        self.assertEqual(4, len(m.steps))
        self.assertEqual('openA', m.steps[1].id)
        self.assertEqual('Unpack and open archive A', m.steps[1].text)
        self.assertTrue(all(s.state == StepState.PENDING for s in m.steps))

    def test_step_running_then_done_keeps_the_runners_time(self):
        m = planned()
        m.apply(line(t='step', id='openA', state='running', last_ms=41000), T0)
        s = m.step('openA')
        self.assertEqual(StepState.RUNNING, s.state)
        self.assertEqual('0:12 (last 0:41)', m.step_time(s, later(12)))
        self.assertIs(s, m.current_step)
        m.apply(line(t='step', id='openA', state='done', ms=38200), later(38))
        self.assertEqual(StepState.DONE, s.state)
        self.assertEqual('38.2 s', m.step_time(s, later(50)))
        self.assertIsNone(m.current_step)

    def test_step_time_without_the_runners_ms_uses_elapsed(self):
        m = planned()
        m.apply(line(t='step', id='checkA', state='running'), T0)
        m.apply(line(t='step', id='checkA', state='done'), later(0.4))
        self.assertEqual('0.4 s', m.step_time(m.step('checkA'), later(5)))
        self.assertEqual('', m.step_time(m.step('report'), later(5)))

    def test_skipped_step_shows_no_time(self):
        m = planned()
        m.apply(line(t='step', id='report', state='skipped', ms=0), T0)
        self.assertEqual('', m.step_time(m.step('report'), T0))

    def test_format_duration(self):
        self.assertEqual('0.4 s', format_ms(400))
        self.assertEqual('59.9 s', format_ms(59900))
        self.assertEqual('1:00', format_ms(60000))
        self.assertEqual('14:02', format_ms(842000))
        self.assertEqual('1:02:03', format_ms(3723000))

    def test_failed_step_keeps_its_error(self):
        m = planned()
        m.apply(line(t='step', id='openA', state='running'), T0)
        m.apply(line(t='step', id='openA', state='failed', ms=5000, error='The project is protected (UMC).'), T0)
        self.assertEqual(StepState.FAILED, m.step('openA').state)
        self.assertEqual('The project is protected (UMC).', m.step('openA').error)
        self.assertEqual('Unpack and open archive A: The project is protected (UMC).', m.step_error)


class Progress(unittest.TestCase):
    def test_progress_line(self):
        m = planned()
        m.apply(line(t='step', id='exportA', state='running'), T0)
        m.apply(line(t='progress', id='exportA', done=25, total=40, item='FB_Conveyor_012'), later(5))
        self.assertEqual(25, m.progress.done)
        self.assertEqual(40, m.progress.total)
        self.assertEqual('Export project A: 25 of 40 (FB_Conveyor_012)', m.progress_line(later(151)))
        m.apply(line(t='step', id='exportA', state='done'), later(160))
        self.assertIsNone(m.progress)

    def test_progress_line_without_progress_shows_the_running_step(self):
        m = planned()
        m.apply(line(t='step', id='openA', state='running', last_ms=41000), T0)
        self.assertEqual('Unpack and open archive A: 0:12 (last run 0:41)', m.progress_line(later(12)))


class Log(unittest.TestCase):
    def test_log_and_stderr_lines(self):
        m = planned()
        m.apply(line(t='log', level='warn', text='Something odd'), T0)
        m.stderr('Traceback (most recent call last):', later(1))
        m.apply('not json at all', later(2))
        self.assertEqual(3, len(m.log))
        self.assertEqual('12:00:00 warn   Something odd', str(m.log[0]))
        self.assertEqual('stderr', m.log[1].level)
        self.assertEqual('12:00:02 raw    not json at all', str(m.log[2]))
        self.assertTrue(m.log_text().endswith('not json at all\r\n'))
        self.assertFalse(m.log[1].detail)
        m.stderr('bridge: [tiabridge 12:00:03] background start: 8048 ms', later(3))
        self.assertTrue(m.log[3].detail)
        self.assertIn('background start: 8048 ms', m.log_text())

    def test_unknown_event_and_step_are_ignored(self):
        m = planned()
        m.apply(line(t='future_thing', x=1), T0)
        m.apply(line(t='step', id='nope', state='running'), T0)
        m.apply(line(no_t=1), T0)
        self.assertEqual(4, len(m.steps))
        self.assertEqual(0, len([l for l in m.log if l.level != 'raw']))

    def test_a_question_and_the_choice_are_logged_never_the_answer(self):
        m = planned()
        m.asked('safety_password', 'Line7_Conveyor', False, T0)
        m.asked('umc_login', '', True, T0)
        self.assertEqual('Asked for the safety password of Line7_Conveyor: given', m.log[0].text)
        self.assertEqual('Asked for the project login: skipped', m.log[1].text)


class Events(unittest.TestCase):
    def test_tia_pid_kept(self):
        m = planned()
        m.apply(line(t='tia', pid=4242), T0)
        self.assertEqual(4242, m.tia_pid)

    def test_prompt_is_warned_and_counted(self):
        m = planned()
        m.apply(line(t='prompt', text='Do you want to upgrade the library?', answer='No'), T0)
        self.assertEqual(1, len(m.prompts))
        self.assertEqual('warn', m.log[0].level)
        self.assertEqual('TIA asked: "Do you want to upgrade the library?" Answered: No', m.log[0].text)

    def test_prompt_without_its_texts_logs_them_empty(self):
        m = planned()
        m.apply(line(t='prompt'), T0)
        self.assertEqual('TIA asked: "" Answered: ', m.log[0].text)

    def test_ask_is_returned(self):
        m = planned()
        r = m.apply(line(t='ask', id='a1', kind='safety_password', project='Line7_Conveyor'), T0)
        self.assertEqual('a1', r.ask.id)
        self.assertEqual('safety_password', r.ask.kind)
        self.assertEqual('Line7_Conveyor', r.ask.project)
        self.assertEqual('', r.ask.hint or '')
        r = m.apply(line(t='ask', id='a2', kind='safety_password', project='P',
                         hint='Fake TIA: the sample password is safe-1.'), T0)
        self.assertEqual('Fake TIA: the sample password is safe-1.', r.ask.hint)


class End(unittest.TestCase):
    REPORT = 'C:\\r\\report.html'

    def test_end_ok(self):
        m = planned()
        m.apply(line(t='prompt', text='Q', answer='No'), T0)
        r = m.apply(line(t='end', ok=True, report='C:\\Runs\\x\\report.html', folder='C:\\Runs\\x', changed=7,
                         not_exported=[{'name': 'FB_Secret', 'why': 'know-how protected'},
                                       {'name': 'F_Main', 'why': 'F-system block'}]), later(842))
        self.assertTrue(r.ended)
        self.assertTrue(m.end.ok)
        self.assertEqual('C:\\Runs\\x\\report.html', m.end.report)
        self.assertEqual('C:\\Runs\\x', m.end.folder)
        self.assertEqual(2, len(m.end.not_exported))
        self.assertEqual('know-how protected', m.end.not_exported[0].why)
        self.assertEqual('Done in 14:02: 7 changed, 2 not in the report, 1 TIA prompt answered, see the log.',
                         m.result_line())

    def test_end_ok_only_moved(self):
        for changed, moved, want in ((0, 3, 'Done in 5.0 s: 3 only moved.'),
                                     (2, 3, 'Done in 5.0 s: 2 changed, 3 only moved.'),
                                     (0, 0, 'Done in 5.0 s: no changes.')):
            m = planned()
            m.apply(line(t='end', ok=True, report=self.REPORT, changed=changed, moved=moved), later(5))
            self.assertEqual(want, m.result_line())

    def test_end_ok_changed_as_a_list_and_no_prompts(self):
        m = planned()
        m.apply(line(t='end', ok=True, report=self.REPORT, changed=['FB_A', 'FB_B']), later(5))
        self.assertEqual(2, m.end.changed)
        self.assertEqual('C:\\r', m.end.folder)
        self.assertEqual('Done in 5.0 s: 2 changed.', m.result_line())

    def test_end_ok_nothing_changed(self):
        m = planned()
        m.apply(line(t='end', ok=True, report=self.REPORT, changed=0), later(5))
        self.assertEqual('Done in 5.0 s: no changes.', m.result_line())

    def test_end_cancelled(self):
        m = planned()
        m.apply(line(t='end', ok=False, cancelled=True), later(90))
        self.assertTrue(m.end.cancelled)
        self.assertEqual('Cancelled after 1:30. TIA was closed; no project was changed.', m.result_line())

    def test_end_failed_names_the_step(self):
        m = planned()
        m.apply(line(t='step', id='openA', state='failed', error='Not in the group Siemens TIA Openness.'), T0)
        m.apply(line(t='end', ok=False, error='The comparison stopped.'), later(3))
        self.assertEqual('Failed: The comparison stopped. (step "Unpack and open archive A")', m.result_line())
        self.assertEqual('Unpack and open archive A: Not in the group Siemens TIA Openness.', m.step_error)

    def test_end_failed_with_an_error_naming_the_step_does_not_repeat_it(self):
        m = planned()
        m.apply(line(t='step', id='openA', state='failed', error='Package missing.'), T0)
        m.apply(line(t='end', ok=False, error='Unpack and open archive A: Package missing.'), later(3))
        self.assertEqual('Failed: Unpack and open archive A: Package missing.', m.result_line())

    def test_end_failed_without_an_error_uses_the_steps(self):
        m = planned()
        m.apply(line(t='step', id='openA', state='failed', error='No TIA V20.'), T0)
        m.apply(line(t='end', ok=False), later(3))
        self.assertEqual('Failed at "Unpack and open archive A": No TIA V20.', m.result_line())

    def test_end_failed_without_anything(self):
        m = planned()
        m.apply(line(t='end', ok=False), later(3))
        self.assertEqual('Failed: see the log.', m.result_line())

    def test_runner_exit_without_end(self):
        m = planned()
        m.runner_exited(3, later(4))
        self.assertFalse(m.end.ok)
        want = 'Failed: the runner ended without a result (exit code 3). See the log.'
        self.assertEqual(want, m.result_line())
        m.runner_exited(0, later(5))   # a second notice changes nothing
        self.assertEqual(want, m.result_line())

    def test_runner_exit_after_end_keeps_the_end(self):
        m = planned()
        m.apply(line(t='end', ok=True, report=self.REPORT, changed=1), later(5))
        m.runner_exited(0, later(6))
        self.assertTrue(m.end.ok)


class Stop(unittest.TestCase):
    def test_stopped_marks_the_running_step_and_the_result(self):
        m = planned()
        m.apply(line(t='tia', pid=77), T0)
        m.apply(line(t='step', id='exportA', state='running'), T0)
        m.stopped(later(200))
        self.assertEqual(StepState.CANCELLED, m.step('exportA').state)
        self.assertEqual(StepState.SKIPPED, m.step('report').state)
        self.assertEqual('Stopped after 3:20: the runner and TIA were ended. A leftover work copy is removed at the '
                         'next start.', m.result_line())
        m.runner_exited(-1, later(201))
        self.assertTrue(m.end.stopped)

    def test_stop_now_offered_after_the_timeout(self):
        m = planned()
        self.assertFalse(m.offer_stop_now(later(500)))
        m.cancel_requested(later(10))
        self.assertFalse(m.offer_stop_now(later(129)))
        self.assertTrue(m.offer_stop_now(later(130)))
        m.apply(line(t='end', ok=False, cancelled=True), later(131))
        self.assertFalse(m.offer_stop_now(later(140)))

    def test_start_resets(self):
        m = planned()
        m.apply(line(t='end', ok=True, report='C:\\r\\report.html'), T0)
        m.start(later(60))
        self.assertEqual(0, len(m.steps))
        self.assertIsNone(m.end)
        self.assertEqual(0, len(m.log))
        self.assertEqual(0, m.tia_pid)


class TheTitle(unittest.TestCase):
    def test_the_window_says_its_version(self):
        # a download's name says it too (package\build.py), so a person can tell which one runs
        self.assertEqual('TIA Archive Compare ' + VERSION, TITLE)


if __name__ == '__main__':
    unittest.main()
