"""A stand-in for TiaBridge.ps1 in the tests: MCP over stdio (one JSON-RPC message per line), the tools the runner
calls, `progress {json}` lines on stderr. No TIA: a sleeping child process stands in for it.

python fake_bridge.py <config.json> <settings.json>
config: export (folder to copy), export_seconds (a part's wait), not_exportable ({part: [{name, folder, reason, message}]}), login_args (background_open takes umc_user / umc_password, safety_login a
password), protected {user, password}, fail_open (error object), failed ([{name, error}] in the blocks part),
khp ([names]), prompts ([{caption, text, answer}] in the background_open result), compile ("ok" / "refused"),
safety ("<password>"), die_on (tool name: the process exits during that call), progress (false: no progress lines),
plain (false: background_open has no plain argument and makes a git folder, as an older TiaBridge),
hmi_devices ([names]: the HMI parts run once per device, as FullExport.ps1; default none), hmi_export (folder copied
in with the first HMI part), hmi_failed ([{name, error}] in the hmi_screens part of each device).
"""
import json
import os
import shutil
import subprocess
import time
import sys

cfg = json.load(open(sys.argv[1], encoding='utf-8'))
settings = json.load(open(sys.argv[2], encoding='utf-8'))
state = {'repo': None, 'tia': None, 'exported': False}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def err(line):
    sys.stderr.write('[tiabridge 12:00:00] ' + line + '\n')
    sys.stderr.flush()


def progress(event, **p):
    if cfg.get('progress', True):
        err('progress ' + json.dumps(dict(event=event, **p)))


def tools():
    open_props = {'path': {}, 'repo': {}, 'write': {}}
    if cfg.get('plain', True):
        open_props['plain'] = {}
    safety_props = {}
    if cfg.get('login_args'):
        open_props.update(umc_user={}, umc_password={})
        if cfg.get('global_arg', True):
            open_props['umc_global'] = {}
        safety_props['password'] = {}
    return [{'name': 'background_open', 'inputSchema': {'properties': open_props}},
            {'name': 'background_close', 'inputSchema': {'properties': {}}},
            {'name': 'full_export', 'inputSchema': {'properties': {'parts': {}}}},
            {'name': 'compile', 'inputSchema': {'properties': {'scope': {}}}},
            {'name': 'safety_login', 'inputSchema': {'properties': safety_props}}]


def background_open(a):
    progress('step', step='start', state='start')
    state['tia'] = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'], creationflags=NO_WINDOW)
    pid = state['tia'].pid
    progress('tia', pid=pid)
    err('background start: 7000 ms')
    progress('step', step='start', state='done', ms=7000, pid=pid)
    progress('step', step='retrieve', state='start', pid=pid)
    prot = cfg.get('protected')
    if prot and (a.get('umc_user') != prot['user'] or a.get('umc_password') != prot['password']
                 or bool(a.get('umc_global')) != bool(prot.get('global'))):
        end_tia()
        return {'ok': False, 'step': 'retrieve',
                'error': {'type': 'Siemens.Engineering.EngineeringTargetInvocationException',
                          'message': 'The project is protected.', 'details': [], 'inner': []},
                'hint': 'The project is protected (project protection or UMC user management).'}
    if cfg.get('fail_open'):
        end_tia()
        return {'ok': False, 'step': 'retrieve', 'error': cfg['fail_open']}
    state['repo'] = os.path.join(settings['projectsRoot'], a['repo'])
    os.makedirs(state['repo'], exist_ok=True)
    if not a.get('plain'):
        os.makedirs(os.path.join(state['repo'], '.git'), exist_ok=True)
    r = {'ok': True, 'processId': state['tia'].pid, 'upgraded': False,
         'steps': [{'step': 'start', 'ms': 7000}, {'step': 'retrieve', 'ms': 30000}, {'step': 'bind', 'ms': 5000}]}
    if cfg.get('prompts'):
        r['prompts'] = cfg['prompts']
    return r


def full_export(a):
    if not state['exported']:
        dest = state['repo']
        for x in os.listdir(cfg['export']):
            s = os.path.join(cfg['export'], x)
            (shutil.copytree if os.path.isdir(s) else shutil.copy)(s, os.path.join(dest, x))
        state['exported'] = True
    details, lines = [], []
    for part in a['parts']:
        n = 3
        hmi = part.startswith('hmi_')
        if hmi and cfg.get('hmi_export') and not state.get('hmi'):
            shutil.copytree(os.path.join(cfg['hmi_export'], 'hmi'), os.path.join(state['repo'], 'hmi'))
            state['hmi'] = True
        for device in (cfg.get('hmi_devices') or []) if hmi else ['']:
            at = {'device': device} if device else {}
            progress('part', part=part, state='start', **at)
            for i in range(1, n + 1):
                progress('object', part=part, kind=part, n=i, of=n, name='%s_%d' % (part, i), ok=True, **at)
                if i == 1 and cfg.get('export_seconds'):
                    time.sleep(cfg['export_seconds'])      # a long part: the cancel ends this process
            progress('part', part=part, state='done', exported=n, count=n, failed=0, ms=100, **at)
            d = {'part': part, 'device': device, 'count': n, 'exported': n, 'failed': [], 'knowHowProtected': []}
            if part == 'blocks':
                d['failed'] = cfg.get('failed', [])
                d['knowHowProtected'] = cfg.get('khp', [])
            if part == 'hmi_screens':
                d['failed'] = cfg.get('hmi_failed', [])
            d['notExported'] = (cfg.get('not_exportable') or {}).get(part, [])
            if d['notExported'] or d['failed']:
                d['exported'] = n - len(d['notExported']) - len(d['failed'])
            details.append(d)
            lines.append('%s%s: %d/%d, 0.1 s' % (part, '@' + device if device else '', d['exported'], n))
    return {'ok': True, 'parts': lines, 'details': details, 'failed': [], 'leftOut': []}


def compile_(a):
    if cfg.get('compile', 'refused') == 'refused':
        return {'ok': False, 'refused': 'compile is refused in a background session: it opens a copy for export only.'}
    return {'ok': True, 'scope': 'plc', 'errors': 0, 'items': []}


def safety_login(a):
    if a.get('password') != cfg.get('safety'):
        return {'ok': False, 'error': {'type': 'Siemens.Engineering.EngineeringTargetInvocationException',
                                       'message': 'The password is not correct.'}}
    return {'ok': True}


def end_tia():
    if state['tia']:
        state['tia'].kill()
        state['tia'].wait()
        state['tia'] = None


def background_close(a):
    progress('step', step='close', state='start', pid=state['tia'].pid if state['tia'] else 0)
    end_tia()
    return {'ok': True, 'closed': True, 'tiaEnded': True}


HANDLERS = {'background_open': background_open, 'full_export': full_export, 'compile': compile_,
            'safety_login': safety_login, 'background_close': background_close}

out = sys.stdout.buffer
for raw in sys.stdin.buffer:
    msg = json.loads(raw.decode('utf-8'))
    if 'id' not in msg:
        continue
    m = msg['method']
    if m == 'initialize':
        res = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'tia'}}
    elif m == 'tools/list':
        res = {'tools': tools()}
    elif m == 'tools/call':
        name = msg['params']['name']
        if cfg.get('die_on') == name:
            end_tia()
            err('dying in ' + name)
            sys.exit(3)
        r = HANDLERS[name](msg['params'].get('arguments') or {})
        with open(os.path.join(os.path.dirname(sys.argv[2]), 'calls.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'tool': name, 'args': msg['params'].get('arguments')}) + '\n')
        res = {'content': [{'type': 'text', 'text': json.dumps(r)}], 'isError': not r.get('ok')}
    else:
        res = {}
    out.write((json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': res}) + '\n').encode('utf-8'))
    out.flush()
end_tia()
