"""The words of an SCL network in the colours TIA V20's SCL editor gives them, as read from pictures of the editor:
one tokenizer over the text of the lines, so a block reads alike from .s7dcl and SimaticML, with the block's interface
for what the text does not tell (a local constant).

of_network(net, lines, block) -> the tokens of each line of an SCL network, None for another language.
lines(texts, itf=None) -> per line [(kind, text)], the texts in order joined giving the line back unchanged: colouring
never adds, drops or moves a character. kind is a key of KINDS, or None for what has no colour of its own (spaces, and
what the tokenizer does not take: those stay in the text's black).

Two passes per line, in this order:
1. _cut cuts the line into whole tokens: spaces, a comment of each kind ((* *), (/* */), //, one left open going on
   over the next lines until it closes), a pragma in braces, a string (with its type prefix), a typed constant, a
   number, a #name, a quoted name, an absolute address, a word, an operator or punctuation (a parenthesis among them),
   the semicolon. A string left open runs to the end of its line. Nothing inside a comment, a string or a quoted name
   is looked at again.
2. _kinds gives each token its kind. A token's kind follows from its own text, and for the rules that go by position
   from its neighbours: the token before and the token after it that are not spaces, on its line (a comment is a
   neighbour like any other token, so a comment after a name ends what a rule reads). The rules that read neighbours,
   and what each reads:
   - a call: the token after is "(". A word is then an instruction (MAX(), a #name or quoted name a block call (#inst(,
     "Fc"(); a word after "." a block call too (#timer.TON().
   - a member: the token before is "." (a word or #name after it is an operand, unless it is called).
   - a parameter name: a word whose token after is ":=" or "=>", inside a call's parentheses (their depth carried over
     the lines of the network).
   - a data type a type test compares with: a word or quoted name whose token before is "=" or "<>" and the one before
     that the ")" closing the parentheses right after TypeOf, TypeOfElements or TypeOfDB (TypeOf(#x) = Int), a
     constant.
   - a jump label: a word that is the line's first token with ":" after it, or a word whose token before is GOTO.
   - a region's name: what follows REGION as the line's first token, to the end of the line, // and all, is one
     constant.
   - a local constant: a #name the interface declares in VAR CONSTANT whose token after is no "." or "[".

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
TYPE_TESTS = frozenset(('TYPEOF', 'TYPEOFELEMENTS', 'TYPEOFDB'))    # what they are compared with is a data type
_END = {'(*': '*)', '(/*': '*/)'}

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<pragma>\{[^}]*\}?)
  | (?P<line_comment>//.*)
  | (?P<open>\(/\*|\(\*)
  | (?P<string>(?:[^\W\d]\w*\#)?'(?:\$.|[^'$])*')
  | (?P<open_string>(?:[^\W\d]\w*\#)?'.*)
  | (?P<typed>[^\W\d]\w*\#[-+]?\w+(?:\.\w+)?(?:[-\#:]\w+(?:\.\w+)?)*)
  | (?P<number>\d+\#[\w]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][-+]?\d+)?)
  | (?P<local>\#(?:"(?:\$.|[^"$])*"|[^\W\d]\w*))
  | (?P<global>"(?:\$.|[^"$])*")
  | (?P<address>%[A-Za-z]+[\d.]*)
  | (?P<word>[^\W\d]\w*)
  | (?P<operator>:=|\?=|\+=|-=|\*=|/=|=>|<=|>=|<>|\*\*|\.\.|[-+*/<>=:,.()\[\]&^])
  | (?P<semicolon>;)
""", re.X)
# the kind of a token by its group alone; word, local and global go by their text and neighbours
_GROUP_KIND = {'space': None, 'pragma': None, 'comment': 'comment', 'string': 'constant', 'typed': 'constant',
               'number': 'constant', 'address': 'operand', 'operator': 'operator', 'semicolon': 'semicolon',
               'other': None}


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
    state = {'end': None, 'depth': 0}           # a comment left open; the parentheses a call left open
    return [_kinds(_cut(text, state), state, consts) for text in texts]


def _constants(itf):
    """The names of the interface's local constants (VAR CONSTANT), upper case: TIA's names do not differ by case."""
    if itf is None:
        return frozenset()
    return frozenset(k.upper() for k, m in itf.root.children.items() if m.section == 'CONSTANT')


def _cut(text, state):
    """Pass 1: [(group, text)] of whole tokens, the texts joined giving the line back. state['end']: the end of a
    comment still open from the line before, and after this line."""
    out, i = [], 0
    if state['end']:                            # a comment going on from the line before
        k = text.find(state['end'])
        stop = len(text) if k < 0 else k + len(state['end'])
        out.append(('comment', text[:stop]))
        if k < 0:
            return out
        i, state['end'] = stop, None
    while i < len(text):
        m = _TOKEN.match(text, i)
        if m is None:                           # nothing the tokenizer takes: one character in the text's black
            out.append(('other', text[i]))
            i += 1
            continue
        group, t = m.lastgroup, m.group()
        if group == 'open':
            k = text.find(_END[t], m.end())
            if k < 0:
                state['end'] = _END[t]
                t = text[i:]
            else:
                t = text[i:k + len(_END[t])]
            group = 'comment'
        elif group in ('line_comment', 'open_string'):
            group = {'line_comment': 'comment', 'open_string': 'string'}[group]
        out.append((group, t))
        i += len(t)
    return out


def _kinds(cut, state, consts):
    """Pass 2: [(kind, text)] of the tokens of _cut, each kind from its token and the neighbours the rules in the module
    doc name. state['depth']: the parentheses open from the lines before, and after this line."""
    real = [k for k, (g, _) in enumerate(cut) if g != 'space']        # the tokens that are neighbours
    first = real[0] if real else None
    if first is not None and cut[first][0] == 'word' and cut[first][1].upper() == 'REGION' and first != real[-1]:
        name = ''.join(t for _, t in cut[real[1]:])                     # the region's name, to the end of the line
        return ([(None, t) for _, t in cut[:first]] + [('region', cut[first][1])]
                + [(None, t) for _, t in cut[first + 1:real[1]]] + [('constant', name)])
    pos = {k: n for n, k in enumerate(real)}

    def near(k, step):
        n = pos[k] + step
        return cut[real[n]] if 0 <= n < len(real) else (None, None)

    type_closes = _type_test_closes(cut, real)
    out = []
    for k, (group, t) in enumerate(cut):
        kind = _GROUP_KIND.get(group)
        if group in ('word', 'local', 'global'):
            before, after = near(k, -1), near(k, 1)
            compared = before in (('operator', '='), ('operator', '<>')) and pos[k] >= 2 \
                and real[pos[k] - 2] in type_closes
            kind = _name_kind(group, t, before, after, compared, k == first, state['depth'], consts)
        if group == 'operator' and t in ('(', ')'):
            state['depth'] = state['depth'] + 1 if t == '(' else max(0, state['depth'] - 1)
        out.append((kind, t))
    return out


def _type_test_closes(cut, real):
    """The indexes in cut of the ")" that close the parentheses right after a type test (TypeOf( ... )) on this line."""
    out, opened = set(), []                     # opened: (index of "(", it follows a type test)
    for n, k in enumerate(real):
        g, t = cut[k]
        if (g, t) == ('operator', '('):
            prev = cut[real[n - 1]] if n else (None, None)
            opened.append(prev[0] == 'word' and prev[1].upper() in TYPE_TESTS)
        elif (g, t) == ('operator', ')') and opened:
            if opened.pop():
                out.add(k)
    return out


def _name_kind(group, t, before, after, compared, first, depth, consts):
    """The kind of a word, #name or quoted name from its text and its neighbours (module doc, pass 2): before and after,
    the tokens next to it; compared: it stands right after a type test's ")" and "=" or "<>"; first: it is the line's
    first token; depth: the parentheses open before it."""
    called = after == ('operator', '(')
    if before == ('operator', '.'):                                     # a member, or the call of #timer.TON(
        return 'block call' if called else 'operand'
    if compared and group != 'local':                                   # TypeOf(#x) = Int, = "Udt"
        return 'constant'
    if group in ('local', 'global'):
        if called:
            return 'block call'
        if group == 'local' and t[1:].strip('"').upper() in consts and after not in (('operator', '.'),
                                                                                       ('operator', '[')):
            return 'local constant'
        return 'operand'
    up = t.upper()
    if up in ('REGION', 'END_REGION'):
        return 'region'
    if up in BOOLS:
        return 'constant'
    if up in WORD_OPERATORS:
        return 'operator'
    if up in KEYWORDS:
        return 'keyword'
    if before[0] == 'word' and before[1].upper() == 'GOTO':
        return 'label'
    if called:
        return 'instruction'
    if depth and after in (('operator', ':='), ('operator', '=>')):
        return 'parameter'                      # inside a call's parentheses, on its line or one after
    if up == 'ENO':
        return 'operand'                        # ENO := FALSE; as TIA colours it
    if first and after == ('operator', ':'):
        return 'label'                          # lblEnd: at the start of its line
    return None


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
