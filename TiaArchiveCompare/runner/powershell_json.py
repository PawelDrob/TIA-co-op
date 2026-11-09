"""ConvertFrom-Json of Windows PowerShell 5.1, with which TiaBridge reads its settings (Get-BridgeSettings,
TiaBridge\\Repo.ps1). It parses with .NET's JavaScriptSerializer, which takes more than JSON (single quotes, unquoted
names, 007, 5-, NaN, a raw line break in a text) and refuses some of it (1e400, nesting over 102 levels); PowerShell
then refuses an empty name and two names that differ in case only. A test holds this reader to Get-BridgeSettings."""
import decimal
import math
import re
import unicodedata

DEPTH_LIMIT = 102           # ConvertFrom-Json's depth of 100, plus two
DECIMAL_MAX = decimal.Decimal('79228162514264337593543950335')
_DIGITS = r'(?:[0-9]+\.?[0-9]*|\.[0-9]+)'
_DECIMAL = re.compile(r'([+-]?)(%s)([+-]?)' % _DIGITS)        # a sign before or after
_DOUBLE = re.compile(r'[+-]?%s(?:[eE][+-]?[0-9]+)?' % _DIGITS)
_SYMBOLS = {'Infinity': math.inf, '-Infinity': -math.inf, 'NaN': math.nan}
_ESCAPES = {'"': '"', "'": "'", '/': '/', '\\': '\\', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
_HEX = frozenset('0123456789abcdefABCDEF')
_NUMBER_WHITE = ' \t\n\v\f\r'
_JSON_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')


class Refused(ValueError):
    """JSON, valid as such, that ConvertFrom-Json refuses; its text says why in plain words."""


class BadEscape(ValueError):
    """A backslash in a text that starts no escape, as a path with single backslashes has."""


def loads(text):
    """The value of text, None for none. ValueError where ConvertFrom-Json refuses the text: Refused for valid JSON,
    BadEscape for a backslash that starts no escape."""
    reader = _Reader(text)
    value = reader.value(0)
    if reader.next_char() is not None:
        raise ValueError('text after the value at %d' % (reader.pos - 1))
    return value


def _is_white(c):
    """Char.IsWhiteSpace."""
    return c in '\t\n\v\f\r \x85\xa0' or unicodedata.category(c) in ('Zs', 'Zl', 'Zp')


def _in_token(c):
    """Char.IsLetterOrDigit of a UTF-16 unit, and the four signs of a number."""
    return c in '.-_+' or (ord(c) <= 0xFFFF and unicodedata.category(c) in ('Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Nd'))


def _folded(name):
    """The name as StringComparison.OrdinalIgnoreCase compares it: each character's own upper case, where that is one
    character and not an ASCII one for a character outside ASCII (dotless i and long s keep theirs)."""
    def upper(c):
        u = c.upper()
        return u if len(u) == 1 and (u >= '\x80' or c < '\x80') else c
    return ''.join(upper(c) for c in name)


def _number(token):
    """The number .NET makes of an unquoted value: Int32, Int64 or Decimal without an exponent, else Double. None for
    what it refuses."""
    if 'e' not in token.lower():
        m = _DECIMAL.fullmatch(token)
        if m and not (m.group(1) and m.group(3)) and decimal.Decimal(m.group(2)) <= DECIMAL_MAX:
            return -float(m.group(2)) if '-' in (m.group(1), m.group(3)) else float(m.group(2))
    if _DOUBLE.fullmatch(token):
        value = float(token)
        return None if math.isinf(value) else value      # .NET Framework refuses what overflows a Double
    return _SYMBOLS.get(token)


class _Reader:
    """JavaScriptObjectDeserializer of .NET Framework 4, step by step, and PowerShell's check of the names."""

    def __init__(self, text):
        self.source = text
        self.pos = 0

    def fail(self, what, kind=ValueError):
        raise kind('%s at %d' % (what, self.pos))

    def next_char(self):
        while self.pos < len(self.source):
            c = self.source[self.pos]
            self.pos += 1
            if not _is_white(c):
                return c
        return None

    def value(self, depth):
        depth += 1
        if depth > DEPTH_LIMIT:
            raise Refused('nesting over %d levels' % DEPTH_LIMIT)
        c = self.next_char()
        if c is None:
            return None
        self.pos -= 1
        if c == '{':
            return self.object(depth)
        if c == '[':
            return self.array(depth)
        if c in '"\'':
            return self.text()
        return self.primitive()

    def object(self, depth):
        self.pos += 1
        members = None
        while True:
            c = self.next_char()
            if c is None:
                break
            self.pos -= 1
            if c == ':':
                self.fail('a colon without a name')
            name = None
            if c != '}':
                name = self.member_name()
                if self.next_char() != ':':
                    self.fail('no colon after a name')
            if members is None:
                members = {}
                if name == '':
                    raise Refused('an empty name')
                if name is None:            # .NET takes a first member without a name for an empty object
                    c = self.next_char()
                    break
            members[name] = self.value(depth)
            c = self.next_char()
            if c == '}':
                break
            if c != ',':
                self.fail('no comma or } after a member')
        if c != '}':
            self.fail('an object without its }')
        seen = {}
        for name in members:
            if name == '':
                raise Refused('an empty name')
            first = seen.setdefault(_folded(name), name)
            if first != name:
                raise Refused('two names that differ in case only: %s and %s' % (first, name))
        return members

    def member_name(self):
        c = self.next_char()
        if c is None:
            return None
        self.pos -= 1
        return self.text() if c in '"\'' else self.token()

    def array(self, depth):
        self.pos += 1
        items = []
        more = False
        while True:
            c = self.next_char()
            if c is None or c == ']':
                break
            self.pos -= 1
            items.append(self.value(depth))
            more = False
            c = self.next_char()
            if c == ']':
                break
            more = True
            if c != ',':
                self.fail('no comma or ] after an item')
        if more or c != ']':
            self.fail('an array with a comma at its end or without its ]')
        return items

    def text(self):
        quote = self.source[self.pos]
        self.pos += 1
        out = []
        while self.pos < len(self.source):
            c = self.source[self.pos]
            self.pos += 1
            if c == quote:
                return ''.join(out)
            if c != '\\':
                out.append(c)
            elif self.pos < len(self.source):
                escaped = self.source[self.pos]
                self.pos += 1
                if escaped == 'u':
                    out.append(self.code_unit())
                elif escaped in _ESCAPES:
                    out.append(_ESCAPES[escaped])
                else:
                    self.fail('an unknown escape', BadEscape)
        self.fail('a text without its closing quote')

    def code_unit(self):
        """\\u and four characters, read as Int32.Parse with NumberStyles.HexNumber: spaces around the digits too."""
        four = self.source[self.pos:self.pos + 4]
        self.pos += 4
        digits = four.strip(_NUMBER_WHITE)
        if len(four) < 4 or not digits or not set(digits) <= _HEX:
            self.fail('a \\u escape without four hex digits', BadEscape)
        return chr(int(digits, 16))

    def token(self):
        start = self.pos
        while self.pos < len(self.source) and _in_token(self.source[self.pos]):
            self.pos += 1
        return self.source[start:self.pos]

    def primitive(self):
        token = self.token()
        if token in ('null', 'true', 'false'):
            return {'null': None, 'true': True, 'false': False}[token]
        number = _number(token)
        if number is None and _JSON_NUMBER.fullmatch(token):
            raise Refused('the number %s, too large for it' % token)
        if number is None:
            self.fail('an unknown value %r' % token)
        return number
