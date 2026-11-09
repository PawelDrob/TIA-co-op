"""A fake exporter: the steps, times, progress, failures, prompts and logins of a real one, without TIA.

For the tests and for developing the window. Times are those measured on a mid-size project, times `speed` (0: no
waiting). With `process`, a sleeping child process stands in for TIA, so the window's "Stop now" has a real pid.

What an archive does comes from the archive file itself when it holds JSON (the samples\\ folder has some):
  export      "v1" / "v2" (TiaChangeReports' made-up test plant) or a folder to copy (relative to the file); default v1;
              its plc\\tags\\ only when the PLC tag tables are exported
  umc         {"user": ..., "password": ..., "global"?: true}: the project is protected; open asks for the login
              (global: the user is a UMC server user, the window's "UMC server user" box must be ticked)
  safety      the safety password; "F_" names in uncompiled then export only after a compile with it
  uncompiled  names that export only after a compile; protected: know-how protected; fsystem: F-system blocks
  fail        {"start"|"open"|"compile"|"export"|"close": "missing_products"|"licence"|"locked"|"openness"|
               "crash"|"other"}
  prompts     [{"phase": ..., "text": ..., "answer": ...}]: TIA prompts answered in that phase
  counts      objects per part ({"blocks": 109, ...}); times: seconds per phase ({"retrieve": 40, ...})
  hmi         the HMI export copied in when the HMI parts are exported: "v1" / "v2" (samples\\hmi\\, made-up
              screens and a tag table) or a folder holding hmi\\ (relative to the file); default: that of export
  hmi_devices the HMI devices (default ["Panel_1"]; [] none); with several, each gets hmi\\<device>\\
  hmi_failed  names of HMI screens TIA fails to export (on every device)
Any other file (a real archive) gets the defaults.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

from . import errors
from .exporter import (HMI_PARTS, ExportFailed, Exporter, ExportResult, NeedsLogin, OpenResult,
                       item_name, part_where)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PLANT = os.path.join(ROOT, 'TiaChangeReports', 'tests', 'fixtures', 'plant')
HMI_SAMPLES = os.path.join(HERE, 'samples', 'hmi')

TIMES = {'start': 8.0, 'retrieve': 40.0, 'copy': 5.0, 'open': 11.0, 'upgrade': 325.0, 'protected': 20.0,
         'compile': 30.0, 'safety': 60.0, 'close': 8.0}
COUNTS = {'blocks': 109, 'dbs': 263, 'types': 131, 'plc_tags': 12, 'library_types': 177,
          'hmi_screens': 64, 'hmi_templates': 3, 'hmi_popups': 6, 'hmi_slideins': 0, 'hmi_screen_globals': 1,
          'hmi_tags': 14, 'hmi_textlists': 45, 'hmi_graphiclists': 9, 'hmi_scripts': 5, 'hmi_cycles': 3,
          'hmi_connections': 2, 'graphics': 80}
# the HMI parts: about 40 s per device (21 to 52 s measured)
PART_SECONDS = {'blocks': 95.0, 'dbs': 62.0, 'types': 5.0, 'plc_tags': 3.0, 'library_types': 28.0,
                'hmi_screens': 22.0, 'hmi_templates': 1.0, 'hmi_popups': 2.0, 'hmi_screen_globals': 0.5,
                'hmi_tags': 6.0, 'hmi_textlists': 3.0, 'hmi_graphiclists': 1.0, 'hmi_scripts': 1.0,
                'hmi_cycles': 0.5, 'hmi_connections': 0.5, 'graphics': 4.0}
PREFIX = {'blocks': 'FB_Block_', 'dbs': 'DB_Data_', 'types': 'UDT_Type_', 'plc_tags': 'TagTable_',
          'library_types': 'LT_Type_',
          'hmi_screens': 'Screen_', 'hmi_templates': 'Template_', 'hmi_popups': 'Popup_', 'hmi_slideins': 'SlideIn_',
          'hmi_screen_globals': 'Global_', 'hmi_tags': 'Tags_',
          'hmi_textlists': 'TextList_', 'hmi_graphiclists': 'GraphicList_', 'hmi_scripts': 'Script_',
          'hmi_cycles': 'Cycle_', 'hmi_connections': 'Connection_', 'graphics': 'Graphic_'}
DEFAULT = {'export': 'v1', 'fsystem': ['F_Main_Safety_FOB'], 'protected': [], 'uncompiled': []}

ERRORS = {
    'missing_products': {'type': 'Siemens.Engineering.MissingProductsException',
                         'message': 'The project cannot be opened: products are missing.',
                         'details': ['Example Drive Package V2.1: not installed']},
    'licence': {'type': 'Siemens.Engineering.LicenseNotFoundException',
                'message': 'No valid license found for STEP 7 Professional.'},
    'locked': 'The project is open in TIA (process 4242) and locked there; the background session does not take '
              'it over.',
    'openness': {'type': 'Siemens.Engineering.EngineeringSecurityException',
                 'message': 'Access denied: the user is not a member of the group Siemens TIA Openness.'},
    'crash': {'type': 'Siemens.Engineering.NonRecoverableException', 'message': 'TIA Portal has ended.',
              'tiaDisconnected': True},
    'other': {'type': 'Siemens.Engineering.EngineeringTargetInvocationException',
              'message': 'The fake was told to fail here.'},
}
PROTECTED = {'type': 'Siemens.Engineering.EngineeringTargetInvocationException',
             'message': 'The project is protected. Enter the user name and password of a project user (UMC).'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def read_config(path):
    try:
        if os.path.getsize(path) < (1 << 20):
            with open(path, encoding='utf-8-sig') as f:
                text = f.read()
            if text.lstrip().startswith('{'):
                cfg = json.loads(text)
                cfg['_dir'] = os.path.dirname(os.path.abspath(path))
                return cfg
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return dict(DEFAULT)


class FakeExporter(Exporter):
    name = 'fake'
    version = 'fake-1'
    needs_tia = False

    def __init__(self, speed=1.0, process=True):
        self.speed = speed
        self.process = process
        self._child = None
        self.cfg = {}
        self.export_dir = None
        self.compiled = False
        self.safety_ok = False
        self.calls = []                  # tests: the calls made, in order

    # ---------------------------------------------------------------- helpers
    def _wait(self, seconds):
        if self.speed > 0 and seconds > 0:
            time.sleep(seconds * self.speed)

    def _t(self, phase):
        return float((self.cfg.get('times') or {}).get(phase, TIMES[phase]))

    def _fail(self, phase):
        kind = (self.cfg.get('fail') or {}).get(phase)
        if not kind:
            return
        err = ERRORS.get(kind, ERRORS['other'])
        if phase in ('start', 'open') or kind == 'crash':
            self._end_tia()
        raise ExportFailed(errors.plain(err), err)

    def _prompts(self, phase, hooks):
        for p in self.cfg.get('prompts') or ():
            if p.get('phase') == phase:
                hooks.prompt(p.get('text', 'TIA asked something.'), p.get('answer', 'No'))

    def _end_tia(self):
        if self._child:
            try:
                self._child.kill()
                self._child.wait(5)
            except OSError:
                pass
            self._child = None

    # ---------------------------------------------------------------- interface
    def open(self, source, export_dir, hooks, login=None):
        self.calls.append('open')
        self.cfg = read_config(source.path)
        self.export_dir = export_dir
        times = {}
        t0 = time.monotonic()
        self._wait(self._t('start'))
        self._fail('start')
        pid = 0
        if self.process and not self._child:
            self._child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(86400)'],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        if self._child:
            pid = self._child.pid
            hooks.tia(pid)
        times['start'] = int((time.monotonic() - t0) * 1000)
        hooks.phase('open')
        t0 = time.monotonic()
        umc = self.cfg.get('umc')
        if umc:
            if isinstance(umc, str):
                umc = {'password': umc}
            if not login:
                self._wait(self._t('protected'))
                self._end_tia()
                raise NeedsLogin('umc_login', errors.plain(PROTECTED), PROTECTED)
            if (login.get('password') != umc.get('password') or (umc.get('user') and login.get('user') != umc['user'])
                    or bool(umc.get('global')) != bool(login.get('umc_global'))):
                self._wait(self._t('protected'))
                self._end_tia()
                raise NeedsLogin('umc_login', 'The project user or password was not accepted.', PROTECTED, wrong=True)
        self._wait(self._t('retrieve') if source.kind == 'archive' else self._t('copy') + self._t('open'))
        if source.upgrade:
            hooks.log('info', 'Upgrading the copy from V%d to V20' % source.version)
            self._wait(self._t('upgrade'))
        self._prompts('open', hooks)
        self._fail('open')
        times['open'] = int((time.monotonic() - t0) * 1000)
        return OpenResult(pid, times, source.upgrade)

    def login_hint(self, kind):
        """So a tester is not puzzled that a real password is refused: the sample's one."""
        if kind == 'safety_password':
            pw = self.cfg.get('safety')
            return ('Fake TIA: the sample password is %s.' % pw) if pw else 'Fake TIA: any password is accepted.'
        umc = self.cfg.get('umc')
        if isinstance(umc, str):
            umc = {'password': umc}
        if not umc:
            return 'Fake TIA: any login is accepted.'
        text = 'Fake TIA: the sample login is %s / %s' % (umc.get('user') or '(any user)', umc.get('password'))
        return text + (', with "UMC server user" ticked.' if umc.get('global') else '.')

    def compile(self, hooks, safety_password=None):
        self.calls.append('compile')
        self._wait(self._t('compile'))
        safety = self.cfg.get('safety')
        if safety_password is not None:
            if safety and safety_password != safety:
                raise NeedsLogin('safety_password', 'The safety password was not accepted.', wrong=True)
            self._wait(self._t('safety'))
            self.safety_ok = True
        self._prompts('compile', hooks)
        self._fail('compile')
        self.compiled = True
        return [n for n in self.cfg.get('uncompiled') or () if n.startswith('F_') and not self.safety_ok]

    def _hmi_source(self):
        src = self.cfg.get('hmi', self.cfg.get('export', 'v1'))
        if not src:
            return None
        src = os.path.join(HMI_SAMPLES, src) if src in ('v1', 'v2') else os.path.join(self.cfg.get('_dir', ROOT), src)
        return src if os.path.isdir(os.path.join(src, 'hmi')) else None

    def _copy_hmi(self, devices):
        src = self._hmi_source()
        if not src or not devices:
            return
        for d in devices:
            dest = os.path.join(self.export_dir, 'hmi', *([d] if len(devices) > 1 else []))
            shutil.copytree(os.path.join(src, 'hmi'), dest, dirs_exist_ok=True)

    def export(self, parts, hooks):
        self.calls.append('export')
        src = self.cfg.get('export', 'v1')
        src = os.path.join(PLANT, src) if src in ('v1', 'v2') else os.path.join(self.cfg.get('_dir', ROOT), src)
        if os.path.isdir(self.export_dir):
            shutil.rmtree(self.export_dir)
        shutil.copytree(src, self.export_dir)
        if 'plc_tags' not in parts:                   # what TIA would not have exported
            for pattern in (('plc', 'tags'), ('plc', '*', 'tags')):        # one PLC, several
                for tags in glob.glob(os.path.join(self.export_dir, *pattern)):
                    shutil.rmtree(tags)
        counts = dict(COUNTS, **(self.cfg.get('counts') or {}))
        devices = list(self.cfg.get('hmi_devices', ['Panel_1']))
        if any(p in HMI_PARTS for p in parts):
            self._copy_hmi(devices)
            if not devices:
                hooks.log('info', 'The project has no HMI device: the report compares the PLC only.')
        out, done = [], {}
        for part in parts:
            if hooks.cancelled():
                return ExportResult(cancelled=True)
            n = int(counts.get(part, 0))
            each = (self.cfg.get('times') or {}).get(part, PART_SECONDS.get(part, 1.0)) / max(n, 1)
            on = [''] if part not in HMI_PARTS or part == 'graphics' else devices
            for device in on:
                for i in range(1, n + 1):
                    self._wait(each)
                    item = '%s%03d' % (PREFIX.get(part, 'X_'), i)
                    hooks.progress(i, n, '%s: %s' % (part_where(part, device), item))
                hooks.log('info', 'Exported %s: %d of %d' % (part_where(part, device), n, n))
                done[part] = done.get(part, 0) + n
                if part == 'hmi_screens':
                    for name in self.cfg.get('hmi_failed') or ():
                        out.append({'name': item_name(name, part, device), 'why': errors.why_not_exported(
                            {'message': 'The fake was told not to export this screen.'})})
            if part == 'blocks':
                self._prompts('export', hooks)
                self._fail('export')
        for name in self.cfg.get('uncompiled') or ():
            if not self.compiled or (name.startswith('F_') and not self.safety_ok):
                out.append({'name': name, 'why': errors.why_not_exported(
                    'Inconsistent blocks and PLC data types (UDT) cannot be exported.')})
        for name in self.cfg.get('protected') or ():
            out.append({'name': name, 'why': 'know-how protected: only its interface is compared'})
        for name in self.cfg.get('fsystem') or ():
            out.append({'name': name,
                        'why': errors.why_not_exported("The export of block '%s' is not permitted." % name)})
        return ExportResult(out, counts=done)

    def close(self, hooks):
        self.calls.append('close')
        self._wait(self._t('close'))
        self._prompts('close', hooks)
        try:
            self._fail('close')
        finally:
            self._end_tia()

    def kill(self):
        self.calls.append('kill')
        self._end_tia()
