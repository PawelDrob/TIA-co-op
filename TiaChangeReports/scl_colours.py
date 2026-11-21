"""The words of an SCL network in the colours TIA V20's SCL editor gives them, as read from pictures of the editor:
one tokenizer over the text of the lines, so a block reads alike from .s7dcl and SimaticML, with the block's interface
for what the text does not tell (a local constant).

of_network(net, lines, block) -> the tokens of each line of an SCL network, None for another language.
lines(texts, itf=None) -> per line [(kind, text)], the texts in order joined giving the line back unchanged: colouring
never adds, drops or moves a character. kind is a key of KINDS, or None for what has no colour of its own: spaces, a
pragma in braces, a character no token takes, a word no rule names (a data type's name outside a type test, NULL);
those stay in the text's black. The lines are one side's whole network as it stands, never the rows of a diff.

Pass 1, _cut: each line into whole tokens. What is decided for a whole line comes first, then the tokens one by one;
the first that applies wins:

    | order | what                                  | takes                                                        |
    |-------|---------------------------------------|--------------------------------------------------------------|
    | 1     | a comment open from the line before   | up to its close, or the whole line                           |
    | 2     | REGION, the first token after spaces  | when anything but spaces follows: the rest of the line, as   |
    |       | and comments                          | the region's name (a //, a comment, a string in it too)      |
    | 3     | spaces                                |                                                              |
    | 4     | a pragma {...}                        | up to its }, or the line's end                               |
    | 5     | a line comment //                     | to the line's end                                            |
    | 6     | a comment (* *) or (/* */)            | up to its close; left open, the line and the next ones       |
    | 7     | a string, plain or typed (WSTRING#)   | up to its quote ($' and $$ inside); left open, the line      |
    | 8     | a literal, one pattern per form       | LITERALS: the form decides which characters it holds         |
    | 9     | a #name, a quoted name, an address    |                                                              |
    | 10    | a word, an operator, a semicolon      |                                                              |

So nothing inside a comment, a string, a quoted name or a region's name is looked at again, and a line rule (2, 5) is
settled before any token rule of pass 2 sees the line.

Pass 2, _kinds: each token's kind, from its own text and, for the rules that go by position, from its neighbours: the
network's tokens in order, over its lines, that are no space, no comment, no pragma and no region's name. So a rule
reads past spaces, comments, pragmas and line ends, which SCL reads alike; a string, a quoted name, an operator and a
keyword are neighbours, and a rule that wants another token there does not hold. The rules, what each reads, and what
ends what it carries:

    | rule                          | reads                                        | carries, and what ends it          |
    |-------------------------------|----------------------------------------------|------------------------------------|
    | a call                        | the neighbour after is "("                   |                                    |
    | a member, a call after a dot  | the neighbour before is "."                  |                                    |
    | a parameter name              | the neighbour after is ":=" or "=>", inside  | the depth of open parentheses,     |
    |                               | a call's parentheses                         | over lines; a ";" sets it to 0     |
    | a data type of a type test    | the neighbour before is "=" or "<>", the one | the open "(" of TypeOf,            |
    |                               | before that the ")" of TypeOf(,             | TypeOfElements, TypeOfDB; a ";"     |
    |                               | TypeOfElements( or TypeOfDB(                 | forgets them                       |
    | a jump label                  | the first neighbour of its line with ":"     |                                    |
    |                               | after it, or a word after GOTO               |                                    |
    | a local constant              | the neighbour after is no "." or "["         |                                    |

A word, a #name or a quoted name is then a call (an instruction, MAX(; a block call, #inst(, "Fc"(, #timer.TON(), a
member (an operand), a parameter name, a data type of a type test (a constant, in quotes or not), a jump label or a
local constant (a #name the interface declares in VAR CONSTANT); else by its text: a keyword, REGION, TRUE or FALSE,
NOT or MOD (an operator), ENO (an operand), a #name or quoted name an operand, another word black. The network's end
ends every rule.

What SCL's grammar sets here and no picture of TIA has shown: a comment or a line end in a rule's gap, an ANY pointer
(P#DB1.DBX0.0 BYTE 1) as one constant. Not settled by
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

# The number forms: the base decides the digits; only a decimal real has an exponent, and only it a sign there.
_BASED = r'(?:2\#[01_]+|8\#[0-7_]+|16\#[0-9A-Fa-f_]+)'
_REAL = r'(?:\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d[\d_]*)?|\d[\d_]*[eE][-+]?\d[\d_]*)'
_INT = r'\d[\d_]*'
_DURATION = r'(?:\d[\d_]*(?:\.\d+)?(?:ms|us|ns|d|h|m|s)_?)+'                   # 1d2h3m4s5ms, 1s_200ms, 1.5s
_DATE = r'\d+-\d+-\d+'
_CLOCK = r'\d+:\d+(?::\d+(?:\.\d+)?)?'                                          # 12:30, 12:30:00.500
_PREFIX = r'[^\W\d]\w*\#'                                                       # a typed constant's type and #
# Each literal form one pattern: (form, pattern). Only the date and time-of-day forms hold a "-" or ":"; only a typed
# number a sign after its #; a typed string is a string (pass 1, order 7).
LITERALS = [
    ('time', r'(?i:LTIME|LT|TIME|T|S5TIME|S5T)\#[-+]?(?i:%s)' % _DURATION),
    ('date and time', r'(?i:LDATE_AND_TIME|DATE_AND_TIME|LDT|DTL|DT)\#%s-%s' % (_DATE, _CLOCK)),
    ('date', r'(?i:DATE|D)\#%s' % _DATE),
    ('time of day', r'(?i:LTIME_OF_DAY|TIME_OF_DAY|LTOD|TOD)\#%s' % _CLOCK),
    ('counter', r'(?i:C)\#\d+'),
    ('pointer', r'(?i:P)\#(?:(?i:DB)\d+\.(?i:DB)[XBWDxbwd]\d+(?:\.\d+)?|[IQMEALiqmeal][XBWDxbwd]?\d+(?:\.\d+)?)'
                r'(?:[ \t]+(?i:BOOL|BYTE|WORD|DWORD|INT|DINT|REAL|CHAR)[ \t]+\d+)?'),     # P#DB1.DBX0.0 BYTE 1
    ('typed Bool', r'%s(?i:TRUE|FALSE)\b' % _PREFIX),
    ('typed based number', r'%s[-+]?%s' % (_PREFIX, _BASED)),
    ('typed real', r'%s[-+]?%s' % (_PREFIX, _REAL)),
    ('typed integer', r'%s[-+]?%s' % (_PREFIX, _INT)),
    ('based number', _BASED),
    ('real', _REAL),
    ('integer', _INT),
]
_STRING = r"(?:%s)?'(?:\$.|[^'$])*'" % _PREFIX
_TOKEN = re.compile('|'.join([
    r'(?P<space>\s+)',
    r'(?P<pragma>\{[^}]*\}?)',
    r'(?P<line_comment>//.*)',
    r'(?P<open>\(/\*|\(\*)',
    r'(?P<string>%s)' % _STRING,
    r"(?P<open_string>(?:%s)?'.*)" % _PREFIX,
    r'(?P<literal>%s)' % '|'.join('(?:%s)' % p for _, p in LITERALS),
    r'(?P<local>\#(?:"(?:\$.|[^"$])*"|[^\W\d]\w*))',
    r'(?P<global>"(?:\$.|[^"$])*")',
    r'(?P<address>%[A-Za-z]+\d+(?:\.\d+)?)',
    r'(?P<word>[^\W\d]\w*)',
    r'(?P<operator>:=|\?=|\+=|-=|\*=|/=|=>|<=|>=|<>|\*\*|\.\.|[-+*/<>=:,.()\[\]&^])',
    r'(?P<semicolon>;)',
]))
# the kind of a token by its group alone; word, local and global go by their text and neighbours
_GROUP_KIND = {'space': None, 'pragma': None, 'comment': 'comment', 'string': 'constant', 'literal': 'constant',
               'address': 'operand', 'operator': 'operator', 'semicolon': 'semicolon', 'region name': 'constant',
               'other': None}
_NO_NEIGHBOUR = ('space', 'comment', 'pragma', 'region name')


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
    """Pass 1 (module doc, its table): [(group, text)] of whole tokens, the texts joined giving the line back.
    state['end']: the end of a comment still open from the line before, and after this line."""
    out, i = [], 0
    if state['end']:                            # order 1: a comment going on from the line before
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
        if group == 'word' and t.upper() == 'REGION' and all(g in ('space', 'comment') for g, _ in out[:-1]):
            rest = text[i:]                     # order 2: the rest of a REGION line is its name
            lead = len(rest) - len(rest.lstrip())
            if rest.strip():
                out += [('space', rest[:lead])] * bool(lead) + [('region name', rest[lead:])]
                return out
    return out


def _kinds(cuts, consts):
    """Pass 2 (module doc, its table): per line [(kind, text)] of the tokens of _cut."""
    out = [[(_GROUP_KIND.get(g), t) for g, t in cut] for cut in cuts]
    stream, firsts = [], set()                  # stream: (line, index in its cut) of the neighbours, in order
    for n, cut in enumerate(cuts):
        real = [(n, k) for k, (g, _) in enumerate(cut) if g not in _NO_NEIGHBOUR]
        firsts.update(real[:1])
        stream += real

    def tok(i):
        return cuts[stream[i][0]][stream[i][1]] if 0 <= i < len(stream) else (None, None)

    closes = _type_test_closes([tok(i) for i in range(len(stream))])
    depth = 0
    for i, (n, k) in enumerate(stream):
        group, t = cuts[n][k]
        if group in ('word', 'local', 'global'):
            before = tok(i - 1)
            compared = before in (('operator', '='), ('operator', '<>')) and i - 2 in closes
            out[n][k] = (_name_kind(group, t, before, tok(i + 1), compared, (n, k) in firsts, depth, consts), t)
        if (group, t) == ('operator', '('):
            depth += 1
        elif (group, t) == ('operator', ')'):
            depth = max(0, depth - 1)
        elif group == 'semicolon':
            depth = 0                           # no ";" stands inside parentheses: a call left open ends here
    return out


def _type_test_closes(toks):
    """The places in toks (the network's neighbours) of the ")" that close the parentheses right after a type test
    (TypeOf( ... )); a ";" forgets the parentheses still open."""
    out, opened = set(), []                     # opened: per "(" still open, whether it follows a type test
    for i, (g, t) in enumerate(toks):
        if (g, t) == ('operator', '('):
            prev = toks[i - 1] if i else (None, None)
            opened.append(prev[0] == 'word' and prev[1].upper() in TYPE_TESTS)
        elif (g, t) == ('operator', ')') and opened:
            if opened.pop():
                out.add(i)
        elif g == 'semicolon':
            opened = []
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
