"""The watcher's pane: a table of the live bridges (and orphaned TIAs) and the last notifications below it, as lines
that fit a width. The watcher gives the rows (Watcher.view), this module only formats them."""
from TiaAgentStatus import state as st
from TiaAgentStatus import statusline

GAP = '  '
# key, header, widest, right-aligned
COLUMNS = [('agent', 'Agent', 20, False), ('project', 'Project', 24, False), ('win', 'Win', 4, False),
           ('call', 'Call', 32, False), ('time', 'Time', 8, True), ('mem', 'Mem', 6, True),
           ('cpu', 'CPU%', 5, True), ('prompt', 'Last prompt', 48, False)]
# the layouts tried in turn until one fits a narrow pane: the columns left out, and the shrinking steps (these
# columns down to this width, the widest first)
LAYOUTS = [((), [(('prompt',), 16), (('agent', 'project'), 10)]),
           (('prompt',), [(('agent', 'project'), 8), (('call',), 12)]),
           (('prompt', 'project'), [(('agent',), 8), (('call',), 12), (('agent',), 5), (('call',), 8)])]


def local(t):
    return t.astimezone().strftime('%H:%M:%S')


def cpu(percent):
    """90%, 180% (two cores), 0%"""
    return '' if percent is None else f'{percent:.0f}%'


def prompt_text(p):
    """14:03 Import: Overwrite? -> No"""
    if not p:
        return ''
    at = st.parse_time(p.get('at'))
    text = ': '.join(x for x in (p.get('caption'), p.get('text')) if x) or p.get('kind') or '?'
    words = [at.astimezone().strftime('%H:%M') if at else '', ' '.join(text.split())]
    if p.get('answer'):
        words.append(f"-> {p['answer']}")
    return ' '.join(w for w in words if w)


def cells(r, now):
    """The texts of one row. r: {state, agent, info (TIA process or None), cpu (% of one core or None), orphan}."""
    s = r['state']
    tia, op, info = s.get('tia'), s.get('operation'), r['info']
    if r.get('orphan'):
        call, time = f"orphan (bridge {r['orphan']} gone)", ''
    elif op:
        call, time = statusline.operation_text(op), statusline.elapsed(op.get('since'), now)
    else:
        call, time = 'idle', ''
    if not tia:
        mem = ''
    elif not info:
        mem = 'gone'
    else:
        mem = statusline.memory(info.get('memory')).replace(' ', '')
    return {'agent': r.get('agent') or '-', 'project': s.get('project') or '-',
            'win': '-' if not tia else 'yes' if tia.get('window', True) else 'no', 'call': call, 'time': time,
            'mem': mem, 'cpu': cpu(r.get('cpu')) if info else '', 'prompt': prompt_text(s.get('lastPrompt'))}


def cut(text, width, more):
    """text at most width characters, a cut one ending in `more`."""
    if len(text) <= width:
        return text
    return text[:width - len(more)].rstrip() + more if width > len(more) else text[:width]


def widths(rows, width):
    """{key: width} of the columns that fit in width, in the first layout that fits after shrinking; the narrowest
    layout when none does (the lines are cut then)."""
    for dropped, steps in LAYOUTS:
        w = {key: min(high, max([len(head)] + [len(r[key]) for r in rows]))
             for key, head, high, _ in COLUMNS if key not in dropped}
        if not any(r['prompt'] for r in rows):
            w.pop('prompt', None)
        for keys, floor in steps:
            over = sum(w.values()) + len(GAP) * (len(w) - 1) - width
            while over > 0:
                widest = max((k for k in keys if k in w), key=lambda k: w[k], default=None)
                if widest is None or w[widest] <= floor:
                    break
                w[widest] -= 1
                over -= 1
        if sum(w.values()) + len(GAP) * (len(w) - 1) <= width:
            break
    return w


def render(view, width=100, height=None, plain=True):
    """The lines of the pane, each at most width - 1 characters (no wrap in the last column). view: {now, folder,
    rows, notes}. plain: ASCII only (not a console, --once); else '…' marks a cut and orphan rows are yellow. height:
    the notifications give way first, then the table rows ("+N more")."""
    now = view['now']
    more = '~' if plain else '…'
    width = max(20, width - 1)
    rows = [cells(r, now) for r in view['rows']]
    orphans = sum(1 for r in view['rows'] if r.get('orphan'))
    lines, marks = [], set()
    if not rows:
        lines.append(f"{local(now)}  0 bridges")
        heads = [head for key, head, _, _ in COLUMNS if key != 'prompt']
        lines.append(cut(GAP.join(heads), width, more))
        lines.append(cut(GAP.join('-' * len(h) for h in heads), width, more))
        lines.append(cut(f"no TIA bridge running; watching {view['folder']}", width, more))
    else:
        n = len(rows) - orphans
        head = f"{local(now)}  {n} bridge{'' if n == 1 else 's'}"
        if orphans:
            head += f", {orphans} orphaned TIA{'' if orphans == 1 else 's'}"
        lines.append(head)
        w = widths(rows, width)
        cols = [c for c in COLUMNS if c[0] in w]

        def line(texts):
            out = []
            for key, _, _, right in cols:
                t = cut(texts[key], w[key], more)
                out.append(t.rjust(w[key]) if right else t.ljust(w[key]))
            return GAP.join(out).rstrip()

        lines.append(line({c[0]: c[1] for c in cols}))
        lines.append(GAP.join('-' * w[c[0]] for c in cols))
        shown = list(zip(view['rows'], rows))
        if height and len(lines) + len(shown) > height - 1:   # never more lines than the pane: a redraw would scroll
            shown = shown[:max(0, height - 2 - len(lines))]
        for r, texts in shown:
            if r.get('orphan'):
                marks.add(len(lines))
            lines.append(line(texts))
        if len(shown) < len(rows):
            lines.append(f'+{len(rows) - len(shown)} more')
    notes = list(view['notes'])
    if height:
        room = height - 1 - len(lines) - 2    # a blank line and the heading
        notes = notes[len(notes) - room:] if room > 0 else []
    if notes:
        lines.append('')
        lines.append('Last notifications')
        for at, text, count in notes:
            lines.append(f"{local(at)}  {text}" + (f' (x{count})' if count > 1 else ''))
    lines = [cut(x, width, more) if len(x) > width else x for x in lines[:height - 1 if height else None]]
    if plain:
        return [x.encode('ascii', 'replace').decode('ascii') for x in lines]
    return [f'\x1b[33m{x}\x1b[0m' if i in marks else f'\x1b[1m{x}\x1b[0m' if i == 1 and rows else x
            for i, x in enumerate(lines)]


class Screen:
    """Redraws the pane in place: the cursor home, each line cleared to its end, the rest of the screen cleared;
    one write per frame, so nothing flickers."""

    def __init__(self, out):
        self.out = out
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except (AttributeError, OSError):
            pass
        self.out.write('\x1b[?25l\x1b[2J')

    def draw(self, lines):
        self.out.write('\x1b[H' + '\x1b[K\n'.join(lines) + '\x1b[K\x1b[J')
        self.out.flush()

    def close(self):
        self.out.write('\x1b[?25h\n')
        self.out.flush()
