"""What a session cost, from Claude Code's transcripts of it: one .jsonl per session id under <config>\\projects\\<folder>\\, the
folder named after the session's worktree, and beside each a folder of its subagents' transcripts. It only reads them.

The transcript's shape is Claude Code's and changes with its releases: what this cannot read it counts as skipped and says so.
A request is one call to the model; several lines of a transcript share it, by its request id, and it is counted once.
"""
import json
import os
import re
from collections import defaultdict
from pathlib import Path

# Dollars per million tokens: (uncached input, cache read, output). A cache write costs WRITE_5M times the input price for
# the 5 minute cache, WRITE_1H times for the 1 hour one. A model not here gets tokens and no dollars.
PRICES = {
    'claude-opus-5-5': (4.00, 0.20, 20.00),
    'claude-sonnet-5-5': (2.00, 0.10, 10.00),
    'claude-fable-5-2': (8.00, 0.20, 40.00),
}
WRITE_5M, WRITE_1H = 1.25, 2.0
PRICES_TAKEN = ('2026-11-21, from the Claude API list prices in the model table of Claude Code\'s claude-api skill '
                '(cached 2026-11-03); cache writes as the API prices them, 1.25 and 2 times input')
METERS = ('input', 'write_5m', 'write_1h', 'write_unknown', 'read', 'output')
METER_NAMES = {'input': 'uncached input', 'write_5m': 'cache writes, 5 min', 'write_1h': 'cache writes, 1 h',
               'write_unknown': 'cache writes, lifetime not recorded', 'read': 'cache reads', 'output': 'output'}
SESSION_ID = re.compile(r'^[A-Za-z0-9-]{1,100}$')
SHOWN_KINDS = 10
SHOWN_TOOLS = 8


def projects_root(env=os.environ):
    """Where Claude Code keeps its transcripts: under CLAUDE_CONFIG_DIR when that is set, otherwise ~\\.claude."""
    return Path(env.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'projects'


def folder_name(path):
    """Claude Code's name for a working folder's transcripts: every character but a letter or digit becomes -."""
    return re.sub(r'[^A-Za-z0-9]', '-', str(path))


def names_hook_folder(line, hook_folder):
    """Whether a transcript line records a hook run of the session whose folder this is: session.py hook "<folder>"."""
    try:
        entry = json.loads(line)
    except ValueError:
        return False
    if not isinstance(entry, dict) or not isinstance(entry.get('hookInfos'), list):
        return False
    tail = os.path.normcase(f'hook "{Path(hook_folder).as_posix()}"')
    return any(isinstance(info, dict) and os.path.normcase(str(info.get('command', '')).rstrip()).endswith(tail)
               for info in entry['hookInfos'])


def ran_hooks_of(path, hook_folder):
    marker = Path(hook_folder).name
    try:
        with open(path, encoding='utf-8', errors='replace') as lines:
            return any(marker in line and names_hook_folder(line, hook_folder) for line in lines)
    except OSError:
        return False


def find_transcripts(root, worktree, hook_folder, ids):
    """The session's own transcripts, oldest first: those of the ids its record and hook hold, in any folder, and those in the
    worktree's folder whose hooks ran with the session's folder, as one started again or cleared before its hook kept every id
    leaves them. Then each one's subagents."""
    root = Path(root)
    found = []
    for session_id in ids:
        if SESSION_ID.match(session_id or ''):
            found += sorted(root.glob(f'*/{session_id}.jsonl'))
    folder = root / folder_name(worktree)
    known = {os.path.normcase(str(path)) for path in found}
    for path in sorted(folder.glob('*.jsonl')) if folder.is_dir() else []:
        if os.path.normcase(str(path)) not in known and ran_hooks_of(path, hook_folder):
            found.append(path)
    found = list(dict.fromkeys(found))
    found.sort(key=first_stamp)
    return [(path, 'session') for path in found] + [(sub, 'subagent') for path in found
                                                    for sub in sorted((path.parent / path.stem / 'subagents').glob('*.jsonl'))]


def first_stamp(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as lines:
            for line in lines:
                stamp = re.search(r'"timestamp":\s*"([^"]+)"', line)
                if stamp:
                    return stamp.group(1)
    except OSError:
        pass
    return ''


# --- reading one transcript

def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def meters_of(usage):
    """The tokens of one request by meter, or None when its usage is not of a shape this knows."""
    fresh, written, read, out = (count(usage.get(key)) for key in
                                 ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'))
    if None in (fresh, read, out):
        return None
    written = written or 0
    by_life = usage.get('cache_creation')
    five = count(by_life.get('ephemeral_5m_input_tokens')) if isinstance(by_life, dict) else None
    hour = count(by_life.get('ephemeral_1h_input_tokens')) if isinstance(by_life, dict) else None
    five, hour = five or 0, hour or 0
    if five + hour > written:
        five, hour = 0, 0
    details = usage.get('output_tokens_details')
    thinking = count(details.get('thinking_tokens')) if isinstance(details, dict) else None
    return {'input': fresh, 'write_5m': five, 'write_1h': hour, 'write_unknown': written - five - hour, 'read': read,
            'output': out, 'thinking': min(thinking or 0, out)}


class Chain:
    """One context: a session's transcript, or a subagent's. Its requests in order, and the calls each one made."""

    def __init__(self, path, kind):
        self.path, self.kind = path, kind
        self.requests = []    # [{'id', 'model', 'at', meters...}]
        self.calls = defaultdict(list)    # request id -> [kind of each call]
        self.shapes = []


def read_chains(path, kind, seen, skipped, roots):
    """The chains of one transcript; seen holds the request ids already counted in another, which are not counted again."""
    chains = {}
    with open(path, encoding='utf-8', errors='replace') as lines:
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                skipped['lines that are not JSON'] += 1
                continue
            if not isinstance(entry, dict):
                skipped['lines that are not JSON'] += 1
                continue
            side = kind == 'session' and entry.get('isSidechain') is True
            key = ('side', str(entry.get('agentId'))) if side else ('main',)
            if key not in chains:
                chains[key] = Chain(path, 'subagent' if side else kind)
            chain = chains[key]
            if entry.get('type') == 'api-request-shape' and isinstance(entry.get('shape'), dict):
                chain.shapes.append(entry['shape'])
            elif entry.get('type') == 'assistant':
                take_assistant(entry, chain, seen, skipped, roots)
    return [chain for chain in chains.values() if chain.requests or chain.shapes]


def take_assistant(entry, chain, seen, skipped, roots):
    message = entry.get('message') if isinstance(entry.get('message'), dict) else {}
    request = entry.get('requestId') or message.get('id')
    usage = message.get('usage')
    if not request or not isinstance(usage, dict):
        skipped['model lines without a request id or usage'] += 1
        return
    if request in seen and seen[request] is not chain:
        return    # a copy of a request counted in another transcript
    if request not in seen:
        meters = meters_of(usage)
        if meters is None:
            skipped['requests whose usage has a shape this does not know'] += 1
            seen[request] = None
            return
        if message.get('model') == '<synthetic>' and not any(meters[m] for m in METERS):
            seen[request] = None    # Claude Code's own stand-in for an answer: no request went out
            return
        seen[request] = chain
        chain.requests.append({'id': request, 'model': str(message.get('model') or '?'), 'at': entry.get('timestamp', ''), **meters})
    for part in message.get('content') if isinstance(message.get('content'), list) else []:
        if isinstance(part, dict) and part.get('type') == 'tool_use':
            chain.calls[request].append(kind_of_call(str(part.get('name') or '?'), part.get('input'), roots))


# --- what a call brings into the context

def kind_of_call(name, given, roots):
    """A name for what the call reads, so that calls reading the same kind of thing add up."""
    given = given if isinstance(given, dict) else {}
    if name in ('Read', 'NotebookRead'):
        return f'{name} {shown_path(given.get("file_path") or given.get("notebook_path") or given.get("path") or "?", roots)}'
    if name in ('Bash', 'PowerShell'):
        return f'{name} {program_of(str(given.get("command") or ""))}'
    if name == 'Skill':
        return f'Skill {given.get("skill") or "?"}'
    if name in ('Agent', 'Task'):
        return f'{name} {given.get("subagent_type") or "general-purpose"}'
    if name == 'ToolSearch':
        return 'ToolSearch: the tool definitions it loads'
    return name


def shown_path(path, roots):
    """A path inside one of the roots relative to it, with /; any other by its last two parts."""
    path = str(path).replace('\\', '/')
    for root in roots:
        root = str(root).replace('\\', '/').rstrip('/') + '/'
        if os.path.normcase(path).startswith(os.path.normcase(root)):
            return path[len(root):]
    parts = [part for part in path.split('/') if part]
    return '/'.join(parts[-2:]) or '?'


def program_of(command):
    """The first program a shell command runs, past cd and variables: git, sed, python."""
    for piece in re.split(r'&&|\|\||[;|\n]', command):
        piece = re.sub(r'^\s*(?:(?:\$?\w+=\S*|&)\s+)*', '', piece)
        quoted = re.match(r'^(["\'])(.+?)\1', piece)
        first = quoted.group(2) if quoted else (piece.split() or [''])[0]
        if not first or first.lower() in ('cd', 'set-location', 'pushd', 'export', 'set', 'echo', 'write-host'):
            continue
        program = re.split(r'[\\/]', first)[-1]
        return re.sub(r'(?i)\.exe$', '', program) or '?'
    return '?'


# --- the measure

def prompt_of(request):
    return request['input'] + request['write_5m'] + request['write_1h'] + request['write_unknown'] + request['read']


def cost_of(request):
    """Dollars of one request, and whether its model has a price. A cache write of no recorded lifetime is left out of them."""
    prices = PRICES.get(request['model'])
    if not prices:
        return 0.0, False
    given, read, out = prices
    dollars = (request['input'] * given + request['write_5m'] * given * WRITE_5M + request['write_1h'] * given * WRITE_1H
               + request['read'] * read + request['output'] * out) / 1e6
    return dollars, True


def steps_of(chain, kinds):
    """What each step added to the prompt, charged to the calls of the request before it, and the reads it caused: the requests
    after it in the same context. prompt(i) = prompt(i-1) + output fed back + what came in between. A prompt smaller than the one
    before means the context was compacted: what came before is carried only up to there."""
    requests = chain.requests
    prompts = [prompt_of(r) for r in requests]
    ends, end = [0] * len(requests), len(requests)
    for i in range(len(requests) - 1, -1, -1):
        ends[i] = end
        if i and prompts[i] < prompts[i - 1]:
            end = i
    first = 'first prompt: system text, tools, instructions' if chain.kind == 'session' else "a subagent's first prompt"

    def charge(kind, tokens, i, calls=0):
        row = kinds[kind]
        row['added'] += tokens
        row['read_again'] += tokens * (ends[i] - i - 1)
        row['calls'] += calls

    for i, request in enumerate(requests):
        if i == 0:
            charge(first, prompts[0], 0)
            continue
        if prompts[i] < prompts[i - 1]:
            charge('the context after a compaction', prompts[i], i)
            continue
        before = requests[i - 1]
        added = prompts[i] - prompts[i - 1] - before['output']
        charge("the model's own output, fed back", before['output'] + min(added, 0), i)
        added = max(added, 0)
        calls = chain.calls.get(before['id']) or []
        if not calls:
            charge('prompts and reminders, no call before', added, i)
        for call in calls:
            charge(call, added / len(calls), i, calls=1)


def prefix_of(shape):
    """The fixed prefix as one recorded request shape has it: the system text and each tool's definition, in characters."""
    system = shape.get('system') if isinstance(shape.get('system'), list) else []
    tools = shape.get('tools') if isinstance(shape.get('tools'), list) else []
    sizes = [len(part.get('text', '')) if isinstance(part, dict) else len(str(part)) for part in system]
    tool_sizes = sorted(((str(t.get('name') if isinstance(t, dict) else '?'), len(json.dumps(t, ensure_ascii=False))) for t in tools),
                        key=lambda item: -item[1])
    return {'system_characters': sum(sizes), 'system_parts': sizes,
            'tool_characters': sum(size for _, size in tool_sizes), 'tools': [{'name': n, 'characters': s} for n, s in tool_sizes]}


def measure(transcripts, roots=()):
    """The measure of a session from its transcripts, [(path, 'session' | 'subagent')], as data."""
    seen, skipped, chains = {}, defaultdict(int), []
    unreadable = []
    for path, kind in transcripts:
        try:
            chains += read_chains(path, kind, seen, skipped, roots)
        except OSError as error:
            unreadable.append(f'{path}: {error}')
    totals = dict.fromkeys(METERS + ('thinking',), 0)
    dollars, by_meter = 0.0, dict.fromkeys(METERS, 0.0)
    models, unpriced = defaultdict(int), defaultdict(int)
    sub = {'agents': 0, 'requests': 0, 'dollars': 0.0}
    for chain in chains:
        if chain.kind == 'subagent' and chain.requests:
            sub['agents'] += 1
        for request in chain.requests:
            for meter in totals:
                totals[meter] += request[meter]
            models[request['model']] += 1
            cost, priced = cost_of(request)
            dollars += cost
            if chain.kind == 'subagent':
                sub['requests'] += 1
                sub['dollars'] += cost
            if not priced:
                unpriced[request['model']] += 1
                continue
            given, read, out = PRICES[request['model']]
            for meter, price in (('input', given), ('write_5m', given * WRITE_5M), ('write_1h', given * WRITE_1H), ('read', read),
                                 ('output', out)):
                by_meter[meter] += request[meter] * price / 1e6
    own = [r for chain in chains if chain.kind == 'session' for r in chain.requests]
    own.sort(key=lambda r: r['at'])
    prompts = [prompt_of(r) for r in own]
    kinds = defaultdict(lambda: {'added': 0, 'calls': 0, 'read_again': 0})
    for chain in chains:
        steps_of(chain, kinds)
    shapes = [shape for chain in chains if chain.kind == 'session' for shape in chain.shapes]
    priced_all = not unpriced and not totals['write_unknown']
    return {
        'transcripts': [str(path) for path, _ in transcripts],
        'sessions': sum(1 for _, kind in transcripts if kind == 'session'),
        'requests': sum(len(chain.requests) for chain in chains),
        'models': dict(models),
        'tokens': totals,
        'dollars': {'total': round(dollars, 4), 'by_meter': {m: round(v, 4) for m, v in by_meter.items()}, 'complete': priced_all,
                    'unpriced_requests': dict(unpriced), 'unpriced_writes': totals['write_unknown']},
        'prices': {'taken': PRICES_TAKEN, 'per_million': {m: dict(zip(('input', 'cache_read', 'output'), p)) for m, p in PRICES.items()},
                   'write_5m_times_input': WRITE_5M, 'write_1h_times_input': WRITE_1H},
        'prompt': {'first': prompts[0], 'last': prompts[-1], 'mean': round(sum(prompts) / len(prompts))} if prompts else None,
        'subagents': {**sub, 'dollars': round(sub['dollars'], 4)},
        'context': sorted(({'kind': k, 'added': round(v['added']), 'calls': v['calls'], 'read_again': round(v['read_again'])}
                           for k, v in kinds.items()), key=lambda row: -row['read_again']),
        'prefix': {**prefix_of(shapes[-1]), 'shapes_recorded': len(shapes)} if shapes else None,
        'skipped': {**skipped, **({'transcripts that could not be read': len(unreadable)} if unreadable else {})},
        'unreadable': unreadable,
    }


# --- as text

def short_text(name, data):
    """A few lines: requests, the four meters and their dollars, the cost, the prompt."""
    if not data['transcripts']:
        return f'{name}: no transcript of it found'
    tokens, money = data['tokens'], data['dollars']
    models = ', '.join(f'{model} {n}' if len(data['models']) > 1 else model for model, n in sorted(data['models'].items()))
    files = data['sessions']
    lines = [f'{name}: {data["requests"]:,} requests in {files} transcript{"s" if files != 1 else ""}, {models or "no model"}']
    width = max(len(f'{tokens[m]:,}') for m in METERS)
    for meter in METERS:
        if meter == 'write_unknown' and not tokens[meter]:
            continue
        price = '' if meter == 'write_unknown' else f'  ${money["by_meter"][meter]:,.2f}'
        extra = f'  thinking {tokens["thinking"]:,}' if meter == 'output' else ''
        lines.append(f'  {METER_NAMES[meter]:<20} {tokens[meter]:>{width},}{price}{extra}')
    if data['models'] and not any(model in PRICES for model in data['models']):
        lines.append('  cost: no list price known for ' + ', '.join(sorted(data['models'])))
    else:
        lines.append(f'  cost ${money["total"]:,.2f} at list prices taken {PRICES_TAKEN.split(",")[0]}' + ('' if money['complete'] else ', without:'))
        for model, n in sorted(money['unpriced_requests'].items()):
            lines.append(f'    {n:,} requests of {model}, whose price is not known')
        if money['unpriced_writes']:
            lines.append(f'    {money["unpriced_writes"]:,} cache write tokens of no recorded lifetime')
    if data['subagents']['requests']:
        sub = data['subagents']
        lines.append(f'  of it {sub["agents"]} subagents: {sub["requests"]:,} requests, ${sub["dollars"]:,.2f}')
    if data['prompt']:
        prompt = data['prompt']
        lines.append(f'  prompt: first {prompt["first"]:,}, last {prompt["last"]:,}, mean {prompt["mean"]:,}')
    for what, n in sorted(data['skipped'].items()):
        lines.append(f'  skipped: {n:,} {what}')
    return '\n'.join(lines)


def full_text(name, data):
    """The short form, then what entered the context and the fixed prefix."""
    lines = [short_text(name, data)]
    if not data['transcripts']:
        return lines[0]
    rows = data['context']
    if rows:
        total = sum(row['read_again'] for row in rows) or 1
        lines.append('What entered the context, by kind: tokens added, calls, tokens read again by the requests after it')
        for row in rows[:SHOWN_KINDS]:
            calls = f'{row["calls"]:>4} calls' if row['calls'] else ' ' * 10
            lines.append(f'  {row["kind"][:58]:<58} {row["added"]:>9,} {calls} {row["read_again"]:>13,}  {100 * row["read_again"] / total:4.1f} %')
        rest = rows[SHOWN_KINDS:]
        if rest:
            read = sum(row['read_again'] for row in rest)
            lines.append(f'  {f"the {len(rest)} other kinds":<58} {sum(row["added"] for row in rest):>9,} '
                         f'{sum(row["calls"] for row in rest):>4} calls {read:>13,}  {100 * read / total:4.1f} %')
    prefix = data['prefix']
    if prefix:
        lines.append(f'Fixed prefix, in characters, from the last of {prefix["shapes_recorded"]} recorded request shapes: system text '
                     f'{prefix["system_characters"]:,} in {len(prefix["system_parts"])} parts, {len(prefix["tools"])} tools '
                     f'{prefix["tool_characters"]:,}')
        for tool in prefix['tools'][:SHOWN_TOOLS]:
            lines.append(f'  {tool["name"]:<40} {tool["characters"]:>8,}')
        rest = prefix['tools'][SHOWN_TOOLS:]
        if rest:
            lines.append(f'  {f"the {len(rest)} other tools":<40} {sum(t["characters"] for t in rest):>8,}')
    else:
        lines.append('Fixed prefix: the transcript records no request shape')
    lines += [f'  could not be read: {line}' for line in data['unreadable']]
    lines.append('Transcripts: ' + ', '.join(data['transcripts']))
    return '\n'.join(lines)
