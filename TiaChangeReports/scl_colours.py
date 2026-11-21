"""The words of an SCL network in the colours TIA V20's SCL editor gives them, as read from pictures of the editor:
one tokenizer over the text of the lines, so a block reads alike from .s7dcl and SimaticML, with the block's interface
for what the text does not tell (a local constant).

of_network(net, lines, block) -> the tokens of each line of an SCL network, None for another language.
lines(texts, itf=None) -> per line [(kind, text)], the texts in order joined giving the line back unchanged: colouring
never adds, drops or moves a character. kind is a key of KINDS, or None for what has no colour of its own: spaces, a
pragma in braces, a character no token takes, a word no rule names (a data type's name outside a type test, NULL);
those stay in the text's black.

Two passes, in this order:
1. _cut cuts each line into whole tokens: spaces, a comment of each kind ((* *), (/* */), //, one left open going on
   over the next lines until it closes), a pragma in braces, a string (with its type prefix), a typed constant, a
   number, a #name, a quoted name, an absolute address, a word, an operator or punctuation (a parenthesis among them),
   the semicolon. A string left open runs to the end of its line. Nothing inside a comment, a string or a quoted name
   is looked at again.
2. _kinds gives each token its kind, over the network's lines together: the lines given, each side's text as it
   stands, never the rows of a diff. A token's kind follows from its own text, and for the rules that go by position
   from its neighbours: the tokens before and after it in the statement, past spaces, comments and line ends, which
   SCL reads alike. A string or a quoted name is a neighbour, as it is a token of the statement. The rules that read
   neighbours, and what each reads:
   - a call: the neighbour after is "(". A word is then an instruction (MAX(), a #name or quoted name a block call
     (#inst(, "Fc"(); a word after "." a block call too (#timer.TON().
   - a member: the neighbour before is "." (a word or #name after it is an operand, unless it is called).
   - a parameter name: a word whose neighbour after is ":=" or "=>", inside a call's parentheses (their depth counted
     over the network's lines).
   - a data type a type test compares with: a word or quoted name whose neighbour before is "=" or "<>", and the one
     before that the ")" closing the parentheses right after TypeOf, TypeOfElements or TypeOfDB (TypeOf(#x) = Int):
     a constant. Two neighbours back, the parentheses paired over the network's lines.
   - a jump label: a word that is the first neighbour of its line with ":" after it, or a word whose neighbour before
     is GOTO.
   - a region's name: what follows REGION as the first neighbour of its line, to the end of that line, // and all, is
     one constant and no neighbour of anything.
   - a local constant: a #name the interface declares in VAR CONSTANT whose neighbour after is no "." or "[".
What SCL's grammar sets here and no picture of TIA has shown: a comment or a line end in a rule's gap. Not settled by
any picture: a call on an array element of instances (#arr[1](, #arr an operand), an address after a quoted tag
("Tag":P, P black), NULL (black).

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
  | (?P<typed>[^\W\d]\w*\#[-+]?\w+(?:\.\w+)?(?:[-\#:]\w+(?:\.\w+)?|(?<=[eE])\+\d+)*)
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
    state = {'end': None}                       # a comment left open at the end of a line
    return _kinds([_cut(text, state) for text in texts], _constants(itf))


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


def _kinds(cuts, consts):
    """Pass 2: per line [(kind, text)] of the tokens of _cut, each kind from its token and the neighbours the rules in
    the module doc name. The neighbours are the stream of the network's tokens that are no space and no comment, over
    its lines; a region's name is none."""
    out = [[(_GROUP_KIND.get(g), t) for g, t in cut] for cut in cuts]
    stream, firsts, regions = [], set(), set()          # stream: (line, index in its cut)
    for n, cut in enumerate(cuts):
        real = [k for k, (g, _) in enumerate(cut) if g not in ('space', 'comment')]
        if not real:
            continue
        r = real[0]
        firsts.add((n, r))
        if cut[r][0] == 'word' and cut[r][1].upper() == 'REGION' and len(real) > 1:
            start = next(k for k in range(r + 1, len(cut)) if cut[k][0] != 'space')
            name = ''.join(t for _, t in cut[start:])                   # the region's name, to the end of the line
            out[n] = out[n][:r] + [('region', cut[r][1])] + out[n][r + 1:start] + [('constant', name)]
            regions.add(n)
            stream.append((n, r))
            continue
        stream += [(n, k) for k in real]

    def tok(i):
        return cuts[stream[i][0]][stream[i][1]] if 0 <= i < len(stream) else (None, None)

    closes = _type_test_closes([tok(i) for i in range(len(stream))])
    depth = 0
    for i, (n, k) in enumerate(stream):
        group, t = cuts[n][k]
        if group in ('word', 'local', 'global') and n not in regions:
            before = tok(i - 1)
            compared = before in (('operator', '='), ('operator', '<>')) and i - 2 in closes
            out[n][k] = (_name_kind(group, t, before, tok(i + 1), compared, (n, k) in firsts, depth, consts), t)
        if (group, t) == ('operator', '('):
            depth += 1
        elif (group, t) == ('operator', ')'):
            depth = max(0, depth - 1)
    return out


def _type_test_closes(toks):
    """The places in toks (the network's stream) of the ")" that close the parentheses right after a type test
    (TypeOf( ... ))."""
    out, opened = set(), []                     # opened: per "(" still open, whether it follows a type test
    for i, (g, t) in enumerate(toks):
        if (g, t) == ('operator', '('):
            prev = toks[i - 1] if i else (None, None)
            opened.append(prev[0] == 'word' and prev[1].upper() in TYPE_TESTS)
        elif (g, t) == ('operator', ')') and opened:
            if opened.pop():
                out.add(i)
    return out


def _name_kind(group, t, before, after, compared, first, depth, consts):
    """The kind of a word, #name or quoted name from its text and its neighbours (module doc, pass 2): before and after,
    its neighbours; compared: it stands right after a type test's ")" and "=" or "<>"; first: it is the first neighbour
    of its line; depth: the parentheses open before it."""
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
