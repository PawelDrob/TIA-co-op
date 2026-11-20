"""The words of an SCL network in the colours TIA V20's SCL editor gives them, as read from pictures of the editor:
one tokenizer over the text of the lines, so a block reads alike from .s7dcl and SimaticML, with the block's interface
for what the text does not tell (a local constant).

of_network(net, lines, block) -> the tokens of each line of an SCL network, None for another language.
lines(texts, itf=None) -> per line [(kind, text)], the texts in order joined giving the line back unchanged: colouring
never adds, drops or moves a character. kind is a key of KINDS, or None for what has no colour of its own (spaces, and
what the tokenizer does not take: those stay in the text's black). A comment opened by (* or (/* goes on over the
next lines until it closes; a string left open colours to the end of its line.

html(tokens, marks) writes one line: a span with the kind's class around a coloured word, a plain <span> around each
range of marks (the changed words, page._word_marks) with the colours inside it."""
import re
from html import escape

# kind: (class, colour as read, what). A kind without a class is TIA's black, the text's own colour: no span.
KINDS = {
    'keyword': ('sk', '#0000ff', 'a keyword of a statement, and AND, OR, XOR'),
    'region': ('sr', '#c91ffe', 'REGION and END_REGION'),
    'constant': ('sc', '#005989', 'a constant as written (Bool, number, time, date, string, typed), a region\'s name'),
    'comment': ('sm', '#187e2b', 'a comment: //, (* *), a multilingual (/* */)'),
    'operand': ('so', '#4c3f88', 'an operand, local or global, with its members, index and slice'),
    'local constant': ('sl', '#02284e', 'a local constant: a #name the interface declares in VAR CONSTANT'),
    'block call': ('sb', '#670667', 'the block or instance a call calls: #instance(, "FC"(, "DB"('),
    'instruction': ('si', '#51120f', 'an instruction called as a function: MAX(, SQRT('),
    'parameter': ('sp', '#350034', 'the name of a parameter in a call: IN :=, Q =>'),
    'operator': ('sx', '#414141', 'an operator or punctuation, and NOT and MOD'),
    'semicolon': (None, '#000000', 'the semicolon ending a statement'),
    'label': (None, '#000000', 'a jump label, where it stands and after GOTO'),
}
CSS = ''.join('.ldiff table.scl .%s{color:%s}' % (c, col) for c, col, _ in KINDS.values() if c) + '\n'

KEYWORDS = frozenset('IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO BY DO END_FOR WHILE END_WHILE REPEAT UNTIL '
                     'END_REPEAT RETURN EXIT CONTINUE GOTO AND OR XOR'.split())
WORD_OPERATORS = frozenset(('NOT', 'MOD'))
BOOLS = frozenset(('TRUE', 'FALSE'))
_END = {'(*': '*)', '(/*': '*/)'}

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<pragma>\{[^}]*\}?)
  | (?P<line_comment>//.*)
  | (?P<open>\(/\*|\(\*)
  | (?P<string>(?:[A-Za-z_]\w*\#)?'(?:\$.|[^'$])*')
  | (?P<open_string>(?:[A-Za-z_]\w*\#)?'.*)
  | (?P<typed>[A-Za-z_]\w*\#[-+]?\w+(?:\.\w+)?(?:[-\#:]\w+(?:\.\w+)?)*)
  | (?P<number>\d+\#[\w]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][-+]?\d+)?)
  | (?P<local>\#(?:"(?:\$.|[^"$])*"|[A-Za-z_]\w*))
  | (?P<global>"(?:\$.|[^"$])*")
  | (?P<address>%[A-Za-z]+[\d.]*)
  | (?P<word>[A-Za-z_]\w*)
  | (?P<operator>:=|\?=|\+=|-=|\*=|/=|=>|<=|>=|<>|\*\*|\.\.|[-+*/<>=:,.()\[\]&^])
  | (?P<semicolon>;)
""", re.X)
# what a group of _TOKEN is, apart from those whose kind depends on what stands around them
_GROUP_KIND = {'space': None, 'pragma': None, 'line_comment': 'comment', 'string': 'constant', 'open_string': 'constant',
               'typed': 'constant', 'number': 'constant', 'address': 'operand', 'operator': 'operator',
               'semicolon': 'semicolon'}
_PARAM = re.compile(r'\s*(?::=|=>)')
_CALL = re.compile(r'\s*\(')


def of_network(net, texts, block):
    """The tokens of each of texts, the lines of network net of block (lines()); None for a network in another language
    than SCL, whose text stays in one colour. block None: no interface at hand."""
    if net is None or net.lang != 'SCL':
        return None
    return lines(texts, block.interface if block is not None else None)


def lines(texts, itf=None):
    """[[(kind, text)] of each line]; itf: the block's Interface (s7dcl.Interface), or None where none is at hand:
    then no #name is a local constant."""
    consts = _constants(itf)
    out, end = [], None
    for text in texts:
        toks, end = _tokenize(text, end, consts)
        out.append(toks)
    return out


def _constants(itf):
    """The names of the interface's local constants (VAR CONSTANT), upper case: TIA's names do not differ by case."""
    if itf is None:
        return frozenset()
    return frozenset(k.upper() for k, m in itf.root.children.items() if m.section == 'CONSTANT')


def _tokenize(text, end, consts):
    """(tokens of one line, the end of a comment still open after it or None)."""
    toks, i = [], 0
    if end:                                     # a comment going on from the line before
        k = text.find(end)
        stop = len(text) if k < 0 else k + len(end)
        toks.append(('comment', text[:stop]))
        if k < 0:
            return toks, end
        i, end = stop, None
    words = []                                  # (index in toks, upper text) of the words, for what follows a word
    while i < len(text):
        m = _TOKEN.match(text, i)
        if m is None:                           # nothing the tokenizer takes: one character in the text's black
            toks.append((None, text[i]))
            i += 1
            continue
        kind, t = m.lastgroup, m.group()
        if kind == 'open':
            k = text.find(_END[t], m.end())
            if k < 0:
                toks.append(('comment', text[i:]))
                return toks, _END[t]
            t = text[i:k + len(_END[t])]
            kind = 'comment'
        elif kind == 'word':
            kind = _word(t, text, m.end(), toks, words)
            if kind == 'region' and t.upper() == 'REGION' and not words and text[m.end():].strip():
                toks.append(('region', t))      # the rest of the line is the region's name
                rest = text[m.end():]
                lead = len(rest) - len(rest.lstrip())
                toks += [(None, rest[:lead])] * bool(lead) + [('constant', rest[lead:])]
                return toks, None
            words.append((len(toks), t.upper()))
        elif kind in ('local', 'global'):
            kind = _operand(t, text, m.end(), consts, toks)
        else:
            kind = _GROUP_KIND[kind]
        toks.append((kind, t))
        i += len(t)
    return toks, None


def _after_dot(toks):
    return bool(toks) and toks[-1] == ('operator', '.')


def _word(t, text, end, toks, words):
    up = t.upper()
    if _after_dot(toks):
        return 'operand'                        # a member: "Db".motor, #inst.Q
    if up in ('REGION', 'END_REGION'):
        return 'region'
    if up in BOOLS:
        return 'constant'
    if up in WORD_OPERATORS:
        return 'operator'
    if up in KEYWORDS:
        return 'keyword'
    if words and words[-1][1] == 'GOTO' and words[-1][0] == len(toks) - 2:
        return 'label'
    rest = text[end:]
    if _CALL.match(rest):
        return 'instruction'
    if _PARAM.match(rest):
        return 'parameter'
    if not words and not any(k for k, _ in toks) and rest.lstrip().startswith(':'):
        return 'label'                          # lblEnd: at the start of its line
    return None


def _operand(t, text, end, consts, toks):
    if _after_dot(toks):
        return 'operand'
    if _CALL.match(text, end):
        return 'block call'
    if t.startswith('#') and t[1:].strip('"').upper() in consts and text[end:end + 1] not in ('.', '['):
        return 'local constant'
    return 'operand'


def html(toks, marks=()):
    """One line's HTML: marks are (start, end) character ranges, each written as a plain <span> (the report's changed
    word) with the coloured words inside it; a coloured word a mark cuts is two spans."""
    text = ''.join(t for _, t in toks)
    kind_at = dict(zip(_starts(toks), (k for k, _ in toks)))
    cuts = sorted({0, len(text)} | {p for m in marks for p in m} | set(kind_at))
    open_marks = {s: e for s, e in marks}
    out, kind, in_mark = [], None, None
    for a, b in zip(cuts, cuts[1:]):
        kind = kind_at.get(a, kind)
        if in_mark is None and a in open_marks:
            in_mark = open_marks[a]
            out.append('<span>')
        cls = KINDS[kind][0] if kind else None
        piece = escape(text[a:b])
        out.append('<span class="%s">%s</span>' % (cls, piece) if cls else piece)
        if in_mark == b:
            out.append('</span>')
            in_mark = None
    return ''.join(out)


def _starts(toks):
    pos = 0
    for _, t in toks:
        yield pos
        pos += len(t)
