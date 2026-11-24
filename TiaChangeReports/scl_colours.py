"""The words of an SCL network in the colours TIA V20's SCL editor gives them, as read from pictures of the editor:
one tokenizer over the text of the lines, so a block reads alike from .s7dcl and SimaticML (test BothFormatsAlike),
with the block's interface for what the text does not tell, a local constant (LocalConstants).

of_network(net, texts, block) -> the tokens of each line of an SCL network, None for another language
(WhatStaysInOneColour). lines(texts, itf=None) -> per line [(kind, text)], the texts in order joined giving the line
back unchanged: colouring never adds, drops or moves a character (TextAndMarksUnchanged). kind is a key of KINDS, or
None for what has no colour of its own: spaces, a pragma, a character no token takes, a DB's data not after a dot, a
word no rule names (the last row of the rules' table below). The lines are one side's whole network as it stands;
page and view give each side its own lines.

Pass 1, _cut: each line into whole tokens. What is decided for a whole line comes first, then the tokens one by one;
the first that applies wins (WhichLineRuleGoesFirst; WhereATokenEnds for where each token ends). A token of WORD_LIKE
never ends inside a word: a word character after it takes the rest of the word with it (WhereATokenEnds).

    | order | what                                  | takes                                                        |
    |-------|---------------------------------------|--------------------------------------------------------------|
    | 1     | a comment open from the line before   | up to its close, or the whole line                           |
    | 2     | REGION, the first token after spaces, | when anything but spaces follows: the rest of the line, as   |
    |       | comments and pragmas                  | the region's name                                            |
    | 3     | spaces                                |                                                              |
    | 4     | a pragma {...}                        | up to its }; a } in double or single quotes does not end it, |
    |       |                                       | a quote left open runs to the line's end                     |
    | 5     | a line comment //                     | to the line's end                                            |
    | 6     | a comment (* *) or (/* */)            | up to its close; left open, the line and the next ones       |
    | 7     | a string, plain or with a type prefix | up to its quote ($ escapes inside); left open, the line      |
    | 8     | a literal                             | the list LITERALS, one pattern per form                      |
    | 9     | a #name, a quoted name                | $ escapes inside a quoted one                                |
    | 10    | an address                            | the lists ADDRESS_AREAS, PERIPHERAL_AREAS, ADDRESS_SIZES,    |
    |       |                                       | NUMBERED_AREAS (the comment over them says what they cover)  |
    | 11    | a DB's data (DBX0.0, DBW2)            | wherever it stands; pass 2 makes it an operand after a "."   |
    | 12    | a word, an operator of the list       |                                                              |
    |       | OPERATORS, a ";"                      |                                                              |

So nothing inside a comment, a string or a quoted name is looked at again.

Pass 2, _kinds: each token's kind, from its own group (_GROUP_KIND) or, for a word, #name, quoted name or DB's data,
by the rules of the list RULES. It is given the tokens only, and a rule a _Name: its token, its neighbours and what
the tokens before it carry; no rule is handed the line's text or a place in it (test_pass_2_reads_tokens_only). The
neighbours are the network's tokens in order, over its lines, that are no space, no comment and no pragma
(_NO_NEIGHBOUR, _neighbours). So a rule reads past spaces, comments, pragmas and line ends (TheRulesAsAGrid, its HOLD
columns); a string, a quoted name and a ";" are neighbours, and a rule that wants another token there does not hold
(its BREAK columns). What a rule carries ends at a ";" or a word of the list STOPPERS (_stops; HalfWrittenNetworks);
the words of the lists LOGIC_KEYWORDS and WORD_OPERATORS end nothing. The network's end ends every rule
(HalfWrittenNetworks.test_the_networks_end_ends_every_rule).

The rules of RULES, in the order _name_kind runs them; the first that applies gives the kind. Each rule that goes by
position has rows in TheRulesAsAGrid (test_the_grid_holds_every_rule_that_goes_by_position):

    | rule                         | pos. | when                                                  | kind               |
    |------------------------------|------|-------------------------------------------------------|--------------------|
    | a member, a call after a dot | yes  | the neighbour before is "."                           | block call before  |
    |                              |      |                                                       | "(", else operand  |
    | a DB's data not after a dot  | no   | a DB's data (after a dot the rule above holds)        | black              |
    | a data type of a type test   | yes  | not called; the neighbour before is "=" or "<>", the  | constant           |
    |                              |      | one before that the ")" closing the "(" after a word  |                    |
    |                              |      | of TYPE_TESTS (a stopper forgets that "("); a word or |                    |
    |                              |      | quoted name, never a #name                            |                    |
    | a block call by its name     | yes  | a #name or quoted name before "("                     | block call         |
    | a local constant             | yes  | a #name of the interface's constants, before no "."   | local constant     |
    |                              |      | or "["                                                |                    |
    | a #name or quoted name       | no   | any other                                             | operand            |
    | a word of REGION_WORDS       | no   |                                                       | region             |
    | a word of BOOLS              | no   |                                                       | constant           |
    | a word of WORD_OPERATORS     | no   |                                                       | operator           |
    | a word of KEYWORDS           | no   |                                                       | keyword            |
    | a jump label after GOTO      | yes  | the neighbour before is GOTO                          | label              |
    | an instruction               | yes  | before "("                                            | instruction        |
    | a parameter name             | yes  | before ":=" or "=>", with a parenthesis open (its     | parameter          |
    |                              |      | depth counted over lines; a stopper sets it to 0)     |                    |
    | ENO                          | no   |                                                       | operand            |
    | a jump label where it stands | yes  | the first neighbour of its line, before ":"           | label              |
    | (none)                       |      | any other word                                        | black              |

So a word's own text (REGION_WORDS to KEYWORDS) goes before the label, call and parameter rules: NOT( is an operator,
IF( a keyword, TRUE: a constant.

What SCL's grammar sets here and no picture of TIA has shown: a comment or a line end in a rule's gap; an ANY pointer
as one constant, with a type word of the list DATA_TYPES; an absolute address of the lists as one operand; a pragma
before REGION; a } inside a pragma's quoted value; a type test compared with a type test (the second called, so an
instruction). Where the grammar reads otherwise, this tokenizer's own way, as accepted: a number, an address or a DB's
data and a word written with no space between them one token (1TO, %M1.0AND; the grammar reads two, and TIA writes
the space); a parameter named like a DB's data black, as a DB's data (#f(DBW2 := 1); the grammar reads a parameter).
Not settled by any picture (NotSettledByAPicture): a call on an array element of instances (#arr[1](, #arr an
operand), an address after a quoted tag ("Tag":P, P black), NULL (black), a type test as a CASE selector (its labels
black).

html(tokens, marks) writes one line: a span with the kind's class around a coloured word, none around a word whose kind
has no class; a plain <span> around each range of marks (the changed words, page._word_marks) with the colours inside
it, so a mark that cuts a coloured word gives two spans of its colour (TextAndMarksUnchanged)."""
import re
from html import escape

# kind: (class, the name of the palette it is drawn in, what). TIA's colours as read are the names' values in TIA's
# native theme (TiaHmiGenerator\hmipreview\static\tia-theme.css). A kind without a class is drawn in --text, the
# text's own colour: no span.
KINDS = {
    'keyword': ('sk', '--scl-keyword', 'a keyword of a statement, and AND, OR, XOR'),
    'region': ('sr', '--scl-region', 'REGION and END_REGION'),
    'constant': ('sc', '--scl-constant', 'a constant as written (Bool, number, time, date, string, typed), a region\'s name'),
    'comment': ('sm', '--scl-comment', 'a comment: //, (* *), a multilingual (/* */)'),
    'operand': ('so', '--scl-operand', 'an operand, local or global, with its members, index and slice'),
    'local constant': ('sl', '--scl-local-constant', 'a local constant: a #name the interface declares in VAR CONSTANT'),
    'block call': ('sb', '--scl-block-call', 'the block or instance a call calls: #instance(, "FC"(, "DB"('),
    'instruction': ('si', '--scl-instruction', 'an instruction called as a function: MAX(, SQRT('),
    'parameter': ('sp', '--scl-parameter', 'a name before := or => with a parenthesis open: IN :=, Q =>'),
    'operator': ('sx', '--scl-operator', 'an operator or punctuation, and NOT and MOD'),
    'semicolon': (None, '--text', 'the semicolon ending a statement'),
    'label': (None, '--text', 'a jump label, where it stands and after GOTO'),
}
CSS = ''.join('.ldiff table.scl .%s{color:var(%s)}' % (c, name) for c, name, _ in KINDS.values() if c) + '\n'

# The tokenizer's own lists; the tests go over them (test_scl_colours: WhereATokenEnds, TheLiteralsAsATable,
# HalfWrittenNetworks).
STATEMENT_KEYWORDS = frozenset('IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO BY DO END_FOR WHILE END_WHILE REPEAT '
                               'UNTIL END_REPEAT RETURN EXIT CONTINUE GOTO'.split())
LOGIC_KEYWORDS = frozenset(('AND', 'OR', 'XOR'))     # keywords that stand inside parentheses
KEYWORDS = STATEMENT_KEYWORDS | LOGIC_KEYWORDS
WORD_OPERATORS = frozenset(('NOT', 'MOD'))
BOOLS = frozenset(('TRUE', 'FALSE'))
REGION_WORDS = frozenset(('REGION', 'END_REGION'))
TYPE_TESTS = frozenset(('TYPEOF', 'TYPEOFELEMENTS', 'TYPEOFDB'))    # what they are compared with is a data type
# The words that end what a rule carries (a call's open parentheses, a type test's), with the ";" _stops adds: none
# stands inside parentheses. The words of LOGIC_KEYWORDS and WORD_OPERATORS do, and are none of them.
STOPPERS = STATEMENT_KEYWORDS | REGION_WORDS
# The elementary data types: an ANY pointer's type word is one of them. A typed number takes any word before its #
# (W#16#, DW#, CHAR#16#41 among them); INTEGER_TYPES and REAL_TYPES are what its test goes over.
INTEGER_TYPES = 'BYTE WORD DWORD LWORD SINT INT DINT LINT USINT UINT UDINT ULINT'.split()
REAL_TYPES = 'REAL LREAL'.split()
DATA_TYPES = (['BOOL'] + INTEGER_TYPES + REAL_TYPES + 'TIME LTIME S5TIME DATE TOD TIME_OF_DAY LTOD LTIME_OF_DAY DT '
              'DATE_AND_TIME LDT DTL CHAR WCHAR STRING WSTRING'.split())
# Absolute addresses as SCL of the S7-1200 and S7-1500 writes them, with "%": the process image, the peripheral access
# with ":P", bit memory, timers and counters, a DB's data, a slice of an operand (#w.%X3); a DB's data by itself
# (DBX0.0, DBW2) is a token of its own, an operand after any "." ("Db".DBX0.0). Not in these lists, as no V20 export
# here holds them and none is settled as V20 SCL: the peripheral form of the S7-300 and S7-400 (%PIW256, %PQW2,
# German %PEW256, %PAW2), a DB's number alone (%DB1, a DB_ANY), and an ANY pointer to local or instance data
# (P#L0.0 BYTE 4, P#DIX0.0 BYTE 4).
ADDRESS_AREAS = ('I', 'Q', 'M', 'E', 'A')            # inputs, outputs, bit memory (E and A: the German mnemonics)
PERIPHERAL_AREAS = ('I', 'Q', 'E', 'A')              # the areas read or written past the process image, with :P
ADDRESS_SIZES = ('X', 'B', 'W', 'D')                 # a bit (X, or none: %M10.0), a byte, a word, a double word
NUMBERED_AREAS = ('T', 'C', 'Z')                     # timers and counters, by number (Z: the German counter)
OPERATORS = (':=', '?=', '+=', '-=', '*=', '/=', '=>', '<=', '>=', '<>', '**', '..', '-', '+', '*', '/', '<', '>', '=',
             ':', ',', '.', '(', ')', '[', ']', '&', '^')
_END = {'(*': '*)', '(/*': '*/)'}


def _words(words):
    return '(?i:%s)' % '|'.join(sorted(words, key=len, reverse=True))


def _chars(letters):
    return '[%s]' % ''.join(letters)


# One piece for where an address points, made from the lists, for an address (%) and an ANY pointer (P#) alike: an
# area's bit (X or none) or byte, word or double word of the sizes; a DB's bit (X) or byte, word or double word.
_BIT, _WIDE = _chars(ADDRESS_SIZES[:1]), _chars(ADDRESS_SIZES[1:])
_OFFSET = r'(?:%s?\d+\.\d+|%s\d+)' % (_BIT, _WIDE)                                      # 1.0, X1.0, W2
_DB_PART = r'DB(?:%s\d+\.\d+|%s\d+)' % (_BIT, _WIDE)                                    # DBX0.0, DBW2
_DB_DATA = r'DB\d+\.%s' % _DB_PART                                                       # DB1.DBX0.0, DB1.DBW2
_LOCATION = r'(?:%s|%s%s)' % (_DB_DATA, _chars(ADDRESS_AREAS), _OFFSET)                  # DB1.DBX0.0, I1.0, QW2
_ADDRESS = r'(?i:%%(?:%s:P|%s|%s\d+|%s\d+))' % (
    _chars(PERIPHERAL_AREAS) + _OFFSET, _LOCATION, _chars(NUMBERED_AREAS), _chars(ADDRESS_SIZES))
# the last two: %T1, %C2, %Z3; a slice %X3, %B0

# The number forms: the base decides the digits; only a decimal real has an exponent, and only it a sign there.
_BASED = r'(?:2\#[01_]+|8\#[0-7_]+|16\#[0-9A-Fa-f_]+)'
_REAL = r'(?:\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d[\d_]*)?|\d[\d_]*[eE][-+]?\d[\d_]*)'
_INT = r'\d[\d_]*'
_DATE = r'\d+-\d+-\d+'
_CLOCK = r'\d+:\d+(?::\d+(?:\.\d+)?)?'                                          # 12:30, 12:30:00.500
_DURATION = r'(?:\d[\d_]*(?:\.\d+)?(?:ms|us|ns|d|h|m|s)_?)+'                   # 1d2h3m4s5ms, 1s_200ms, 1.5s
_PREFIX = r'[^\W\d]\w*\#'                                                       # a typed constant's type and #
# Each literal form one pattern: (form, pattern). A "-" or ":" between digits stands only in the date and time-of-day
# forms; a sign only right after the # of a time, a typed integer or a typed real, and in a real's exponent; a typed
# string is a string (pass 1, order 7).
LITERALS = [
    ('time', r'(?i:LTIME|LT|TIME|T|S5TIME|S5T)\#[-+]?(?i:%s)' % _DURATION),
    ('date and time', r'(?i:LDATE_AND_TIME|DATE_AND_TIME|LDT|DTL|DT)\#%s-%s' % (_DATE, _CLOCK)),
    ('date', r'(?i:DATE|D)\#%s' % _DATE),
    ('time of day', r'(?i:LTIME_OF_DAY|TIME_OF_DAY|LTOD|TOD)\#%s' % _CLOCK),
    ('pointer', r'(?i:P\#%s)(?:[ \t]+%s[ \t]+\d+)?' % (_LOCATION, _words(DATA_TYPES))),     # P#DB1.DBX0.0 BYTE 1
    ('typed Bool', r'%s(?i:TRUE|FALSE)' % _PREFIX),
    ('typed based number', r'%s%s' % (_PREFIX, _BASED)),
    ('typed real', r'%s[-+]?%s' % (_PREFIX, _REAL)),
    ('typed integer', r'%s[-+]?%s' % (_PREFIX, _INT)),
    ('based number', _BASED),
    ('real', _REAL),
    ('integer', _INT),
]
_STRING = r"(?:%s)?'(?:\$.|[^'$])*'" % _PREFIX
_TOKEN = re.compile('|'.join([
    r'(?P<space>\s+)',
    r'(?P<pragma>\{(?:"[^"]*"?|' + r"'[^']*'?|[^}\"'])*\}?)",  # a } in quotes ends it not; a quote left open runs on
    r'(?P<line_comment>//.*)',
    r'(?P<open>\(/\*|\(\*)',
    r'(?P<string>%s)' % _STRING,
    r"(?P<open_string>(?:%s)?'.*)" % _PREFIX,
    r'(?P<literal>%s)' % '|'.join('(?:%s)' % p for _, p in LITERALS),
    r'(?P<local>\#(?:"(?:\$.|[^"$])*"|[^\W\d]\w*))',
    r'(?P<global>"(?:\$.|[^"$])*")',
    r'(?P<address>%s)' % _ADDRESS,
    r'(?P<db_data>(?i:DB(?:%s\d+\.\d+|%s\d+(?!\w))))' % (_BIT, _WIDE),  # DBX0.0, DBW2 by itself; DBW2x a name
    r'(?P<word>[^\W\d]\w*)',
    r'(?P<operator>%s)' % '|'.join(re.escape(o) for o in sorted(OPERATORS, key=len, reverse=True)),
    r'(?P<semicolon>;)',
]))
WORD_LIKE = ('literal', 'local', 'address', 'db_data', 'word')     # each ends at a word end (_cut)
# the kind of a token by its group alone; word, local, global and db_data go by the rules of pass 2 (RULES)
_GROUP_KIND = {'space': None, 'pragma': None, 'comment': 'comment', 'string': 'constant', 'literal': 'constant',
               'address': 'operand', 'operator': 'operator', 'semicolon': 'semicolon', 'region name': 'constant',
               'other': None}
_BEFORE_REGION = ('space', 'comment', 'pragma')       # what may stand before REGION on its line (pass 1, row 2)
_NO_NEIGHBOUR = ('space', 'comment', 'pragma')        # what a rule of pass 2 reads past (_neighbours)


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
    state['end']: the end of a comment still open from the line before, and after this line. A token of WORD_LIKE
    that a word character follows takes the rest of that word with it: no token ends inside a word."""
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
        elif group in WORD_LIKE:
            t += _WORD_REST.match(text, m.end()).group()     # a word end: 42abc and %IW2x stay whole
        out.append((group, t))
        i += len(t)
        if group == 'word' and t.upper() == 'REGION' and all(g in _BEFORE_REGION for g, _ in out[:-1]):
            rest = text[i:]                     # order 2: the rest of a REGION line is its name
            lead = len(rest) - len(rest.lstrip())
            if rest.strip():
                out += [('space', rest[:lead])] * bool(lead) + [('region name', rest[lead:])]
                return out
    return out


_WORD_REST = re.compile(r'\w*')


class _Name:
    """What a rule of pass 2 knows of a word, #name, quoted name or DB's data: its group and text, its neighbours
    before and after ((group, text) of a token, or (None, None) past the network's ends), and from the tokens before
    it: compared (it stands right after a type test's ")" and "=" or "<>"), first (the first neighbour of its line),
    depth (the parentheses open before it), and the interface's local constants (consts). No rule gets the line's
    text or a place in it: a rule reads tokens only."""
    __slots__ = ('group', 'text', 'before', 'after', 'compared', 'first', 'depth', 'consts')

    def __init__(self, group, text, before, after, compared, first, depth, consts):
        self.group, self.text, self.before, self.after = group, text, before, after
        self.compared, self.first, self.depth, self.consts = compared, first, depth, consts

    @property
    def called(self):
        return self.after == ('operator', '(')

    @property
    def up(self):
        return self.text.upper()


def _neighbours(stream, i):
    """(the token before, the token after) stream[i] among the network's neighbours, (None, None) past its ends."""
    return (stream[i - 1] if i > 0 else (None, None)), (stream[i + 1] if i + 1 < len(stream) else (None, None))


def _kinds(cuts, consts):
    """Pass 2 (module doc, its tables): per line [(kind, text)] of the tokens of _cut. It is given the tokens only."""
    out = [[(_GROUP_KIND.get(g), t) for g, t in cut] for cut in cuts]
    places, firsts = [], set()                  # (line, index in its cut) of the neighbours, in order
    for n, cut in enumerate(cuts):
        real = [(n, k) for k, (g, _) in enumerate(cut) if g not in _NO_NEIGHBOUR]
        firsts.update(real[:1])
        places += real
    stream = [cuts[n][k] for n, k in places]
    closes = _type_test_closes(stream)
    depth = 0
    for i, (n, k) in enumerate(places):
        group, t = stream[i]
        if group in ('word', 'local', 'global', 'db_data'):
            before, after = _neighbours(stream, i)
            compared = before in (('operator', '='), ('operator', '<>')) and i - 2 in closes
            name = _Name(group, t, before, after, compared, (n, k) in firsts, depth, consts)
            out[n][k] = (_name_kind(name), t)
        if (group, t) == ('operator', '('):
            depth += 1
        elif (group, t) == ('operator', ')'):
            depth = max(0, depth - 1)
        elif _stops((group, t)):
            depth = 0                           # no ";" and no word of STOPPERS stands inside parentheses
    return out


def _stops(tok):
    """A ";" or a word of the list STOPPERS: what ends a call's or a type test's parentheses left open."""
    return tok[0] == 'semicolon' or (tok[0] == 'word' and tok[1].upper() in STOPPERS)


def _type_test_closes(toks):
    """The places in toks (the network's neighbours) of the ")" that close the parentheses right after a type test
    (TypeOf( ... )); a stopper (_stops) forgets the parentheses still open."""
    out, opened = set(), []                     # opened: per "(" still open, whether it follows a type test
    for i, (g, t) in enumerate(toks):
        if (g, t) == ('operator', '('):
            prev = toks[i - 1] if i else (None, None)
            opened.append(prev[0] == 'word' and prev[1].upper() in TYPE_TESTS)
        elif (g, t) == ('operator', ')') and opened:
            if opened.pop():
                out.add(i)
        elif _stops((g, t)):
            opened = []
    return out


_SKIP = object()            # a rule that does not apply to a name


def _member(n):
    if n.before == ('operator', '.'):
        return 'block call' if n.called else 'operand'
    return _SKIP


def _db_data(n):
    return None if n.group == 'db_data' else _SKIP


def _type_test(n):
    return 'constant' if n.compared and n.group != 'local' and not n.called else _SKIP


def _named_call(n):
    return 'block call' if n.group in ('local', 'global') and n.called else _SKIP


def _local_constant(n):
    if n.group == 'local' and n.text[1:].strip('"').upper() in n.consts and \
            n.after not in (('operator', '.'), ('operator', '[')):
        return 'local constant'
    return _SKIP


def _operand(n):
    return 'operand' if n.group in ('local', 'global') else _SKIP


def _in(words, kind):
    return lambda n: kind if n.up in words else _SKIP


def _label_after_goto(n):
    return 'label' if n.before[0] == 'word' and n.before[1].upper() == 'GOTO' else _SKIP


def _instruction(n):
    return 'instruction' if n.called else _SKIP


def _parameter(n):
    return 'parameter' if n.depth and n.after in (('operator', ':='), ('operator', '=>')) else _SKIP


def _eno(n):
    return 'operand' if n.up == 'ENO' else _SKIP


def _label_first(n):
    return 'label' if n.first and n.after == ('operator', ':') else _SKIP


# The rules of pass 2 in the order the code runs them (_name_kind): (name, it goes by position, the rule). The module
# doc's order table is this list; TheRulesAsAGrid goes over the rules that go by position.
RULES = [
    ('a member, a call after a dot', True, _member),
    ("a DB's data not after a dot", False, _db_data),
    ('a data type of a type test', True, _type_test),
    ('a block call by its name', True, _named_call),
    ('a local constant', True, _local_constant),
    ('a #name or quoted name', False, _operand),
    ('a word of REGION_WORDS', False, _in(REGION_WORDS, 'region')),
    ('a word of BOOLS', False, _in(BOOLS, 'constant')),
    ('a word of WORD_OPERATORS', False, _in(WORD_OPERATORS, 'operator')),
    ('a word of KEYWORDS', False, _in(KEYWORDS, 'keyword')),
    ('a jump label after GOTO', True, _label_after_goto),
    ('an instruction', True, _instruction),
    ('a parameter name', True, _parameter),
    ('ENO', False, _eno),
    ('a jump label where it stands', True, _label_first),
]


def _name_kind(name):
    """The kind of a word, #name, quoted name or DB's data (a _Name): the first of RULES that applies; none, black."""
    for _, _, rule in RULES:
        kind = rule(name)
        if kind is not _SKIP:
            return kind
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
