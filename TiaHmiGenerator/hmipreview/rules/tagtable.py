"""HMI tag table rules. Generated tag tables only: an export is what TIA has. All are errors because TIA ended its
process at import on the cases they name, NonRecoverableException, everything since the last save lost
(docs/agent/wincc-comfort-openness.md section 7.2).

  tagtable.data-type       error: a DataType that the validator cannot check, so it is refused rather than taken, and
                           never learned from a file: none; white space around it ('Int ', a pretty-printed file); an
                           ELEMENTARY or FIXED_SIZE type, or an array of one, written otherwise than TIA writes it, in
                           another case ('int', 'array [0..1] of word'), by another name ('TOD') or with an array
                           prefix spaced otherwise than PREFIX ('Array[0..1]of Int'; between dimensions ', ' is
                           [INFERRED], an export showed one dimension only); the name of such a type, or of one of
                           OTHER_NAMES, in quotes as a PLC data type's ('"Int"', 'Array [0..1] of "time"'); and any
                           DataType that is neither of those nor TAUGHT (a string or a PLC data type, or an array of
                           one), such as Timer, HW_IO or 'Int' with a zero-width space: nothing would check its Length.
  tagtable.length          error: a tag's Length is not the size of its DataType, or it has none. Seen: an Int tag with
                           Length 1, "Cannot set the length for the <tag> tag because data of the connected data type
                           would have to be overwritten. The length of the data type is 2, the HMI tag has the value 1."
                           The size of an ELEMENTARY or FIXED_SIZE DataType (the other S7 types of a fixed size: Time,
                           Char, DTL, ...) is theirs, and that of an array of an ELEMENTARY one its number of elements
                           times its element's, whatever a file under hmi/tags says: hand-built tables were imported
                           from there before generated/tags, and the one that ended TIA was such a file. An array of
                           Bool or of a FIXED_SIZE type, or one whose bounds are not numbers or run backwards, is
                           refused: nothing shows how TIA counts its Length. A TAUGHT DataType: the Length its tags
                           carry in the tag table files under hmi/tags of this repo (this device, the other devices,
                           hmi/references); one no file holds is refused too, as nothing could check its Length.
  tagtable.hmi-data-type   error: a tag's HmiDataType is not the one TIA takes for its DataType, or it has none. Seen:
                           Word, "The HMI data type Word was not found"; the HMI tag of a PLC Word is a UInt. The one
                           of an ELEMENTARY DataType, and of an array of one, is fixed by ELEMENTARY; it is taken once
                           SEEN holds the DataType or a file pairs the two at the DataType's size. A file that pairs it
                           with another HmiDataType, or at another Length, teaches nothing. A FIXED_SIZE DataType: the
                           HmiDataType the files pair it with at its size, one way only, as nothing shows which TIA
                           takes. A TAUGHT DataType: the HmiDataType its tags in those files pair it with, one way only.

A TAUGHT DataType, and the HmiDataType of a FIXED_SIZE one, is learned from the files under hmi/tags, and nothing tells
a bridge export there from a file built by hand: a hand-built file teaches them too, a wrong Length of a TAUGHT type
included.

knowledge(repo) gives what the rules know; hmixml.tag_table builds tags from it.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from ..findings import error
from ..model import GENERATED, attribute

# DataType: (size in bytes, the HmiDataType TIA takes for it). Bool, Int, Word and DInt are seen in exports
# [EXPORT] (project B; Int 2 also in TIA's message above; DInt in a round trip through TIA). The others
# are the S7 sizes and, after Word -> UInt, the unsigned integer of a bit string [INFERRED]: no export of one was read.
ELEMENTARY = {'Bool': (1, 'Bool'), 'Byte': (1, 'USInt'), 'SInt': (1, 'SInt'), 'USInt': (1, 'USInt'),
              'Word': (2, 'UInt'), 'Int': (2, 'Int'), 'UInt': (2, 'UInt'),
              'DWord': (4, 'UDInt'), 'DInt': (4, 'DInt'), 'UDInt': (4, 'UDInt'), 'Real': (4, 'Real'),
              'LWord': (8, 'ULInt'), 'LInt': (8, 'LInt'), 'ULInt': (8, 'ULInt'), 'LReal': (8, 'LReal')}
# The other S7 types of a fixed size: their S7 size in bytes [INFERRED], no export of one was read. Nothing shows
# which HmiDataType TIA takes for them, so it is the one an export pairs them with at that size.
FIXED_SIZE = {'Char': 1, 'WChar': 2, 'S5Time': 2, 'Date': 2, 'Time': 4, 'Time_Of_Day': 4, 'LTime': 8,
              'LTime_Of_Day': 8, 'Date_And_Time': 8, 'LDT': 8, 'DTL': 12}
# Other names of FIXED_SIZE types, and the one TIA writes in an export [INFERRED].
OTHER_NAMES = {'TOD': 'Time_Of_Day', 'LTOD': 'LTime_Of_Day', 'DT': 'Date_And_Time', 'Date_And_LTime': 'LDT'}
# The DataTypes whose HmiDataType is taken without an export of this repo [EXPORT].
SEEN = frozenset(('Bool', 'Int', 'Word', 'DInt'))
_FOLDED = {**{t.casefold(): t for t in (*ELEMENTARY, *FIXED_SIZE)},
           **{n.casefold(): t for n, t in OTHER_NAMES.items()}}
# An array DataType in any spelling, and its prefix as TIA writes it: 'Array [', the bounds of each dimension
# without white space, ', ' between them, '] of '. All are matched whole (fullmatch), digits ASCII only.
ARRAY = re.compile(r'(array\s*\[([^\]]*)\]\s*of\s+)(\w+)', re.IGNORECASE)
_PREFIX = r'Array \[[^\]\s,]+(?:, [^\]\s,]+)*\] of '
PREFIX = re.compile(_PREFIX)
BOUNDS = re.compile(r' *(-?[0-9]+) *\.\. *(-?[0-9]+) *')
LENGTH = re.compile(r'[0-9]+')
# The DataTypes only an export can teach: a string or a PLC data type, or an array of one, as TIA writes them.
TAUGHT = re.compile(r'(%s)?(W?String(\[[0-9]+\])?|"[^"\x00-\x1f]+")' % _PREFIX)
TIA_ENDED = 'TIA ended its process on such an import (NonRecoverableException), losing everything since the last save.'
EXPORT_ONE = 'export a tag table that holds a tag of it (TiaBridge export kind hmi_tag_table)'


@dataclass(frozen=True)
class Shape:
    """A DataType read against ELEMENTARY and FIXED_SIZE, white space around it left out."""
    element: str = None    # the type it is or is an array of, as TIA writes it; None for any other
    prefix: str = ''       # 'Array [0..1] of ' for an array, as written
    count: int = 1         # the elements of an array; None when its bounds give none (uncounted)
    exact: bool = True     # written as TIA writes it: no white space around it, the element in TIA's case and by
                           # its name in an export, an array's prefix as PREFIX
    uncounted: str = None  # why an array's bounds give no count: 'not numbers' or 'backwards'; None when they do
    bounds: str = None     # an array's bounds, as written; None for no array

    @property
    def written(self):
        """The DataType as TIA writes it."""
        if self.bounds is None:
            return self.element
        return 'Array [%s] of %s' % (', '.join(re.sub(r'\s+', '', d) for d in self.bounds.split(',')), self.element)


def _padded(data_type):
    return data_type != data_type.strip()


def shape(data_type):
    raw = data_type or ''
    dt = raw.strip()
    if dt.casefold() in _FOLDED:
        element = _FOLDED[dt.casefold()]
        return Shape(element, '', 1, raw == element)
    m = ARRAY.fullmatch(dt)
    if not m or m.group(3).casefold() not in _FOLDED:
        return Shape()
    element = _FOLDED[m.group(3).casefold()]
    count, uncounted = 1, None
    for dim in m.group(2).split(','):
        b = BOUNDS.fullmatch(dim)
        if not b or int(b.group(2)) < int(b.group(1)):
            count, uncounted = None, 'backwards' if b else 'not numbers'
            break
        count *= int(b.group(2)) - int(b.group(1)) + 1
    return Shape(element, m.group(1), count,
                 not _padded(raw) and m.group(3) == element and bool(PREFIX.fullmatch(m.group(1))), uncounted,
                 m.group(2))


def _taught(data_type):
    """Whether only an export can teach the Length and HmiDataType of data_type (TAUGHT)."""
    return bool(TAUGHT.fullmatch(data_type or ''))


def _uncountable(s):
    """Whether s is an array whose Length nothing shows how TIA counts: of Bool, or of a FIXED_SIZE type."""
    return bool(s.prefix) and (s.element == 'Bool' or s.element in FIXED_SIZE)


def data_type_problem(data_type):
    """Why a DataType is refused before its Length is read, else None: none, white space around it, a known type (or
    an array of one) written in another case, by another name or with an array prefix TIA does not write, or one
    neither known nor TAUGHT."""
    dt = data_type or ''
    s = shape(dt)
    if not dt:
        return 'The tag has no DataType. Make such a tag in TIA.'
    if _padded(dt):
        return ("Data type %r has white space around it; nothing shows what TIA does with it. Write it as %s."
                % (dt, s.written if s.element else dt.strip()))
    if s.element and not s.exact:
        if dt[len(s.prefix):].casefold() != s.element.casefold():
            how = 'by another name'
        elif s.prefix.casefold() != s.written[:-len(s.element)].casefold():
            how = 'with its array prefix spaced otherwise'
        else:
            how = 'in another case'
        return ("Data type %r is %s, written %s; nothing shows what TIA does with that. Write it as %s."
                % (dt, s.element if not s.prefix else 'an array of ' + s.element, how, s.written))
    m = TAUGHT.fullmatch(dt)
    quoted = _FOLDED.get(m.group(2)[1:-1].strip().casefold()) if m and m.group(2).startswith('"') else None
    if quoted:
        return ("Data type %s is the S7 type %s quoted as the name of a PLC data type; nothing shows what TIA does "
                "with that. Write it as %s." % (dt, quoted, (m.group(1) or '') + quoted))
    if s.element is None and not _taught(dt):
        return ("Data type %r is neither an S7 type of a size the validator holds nor a string or a PLC data type, "
                "which a tag table export can teach, so nothing checks its Length. Make such a tag in TIA." % dt)
    return None


def _fixed_size(data_type):
    """The size of data_type that no file changes: of an ELEMENTARY or FIXED_SIZE type, or of an array of an
    ELEMENTARY one but Bool; None for any other DataType, and for one written otherwise than TIA writes it."""
    s = shape(data_type)
    if not s.element or not s.exact or s.count is None or _uncountable(s):
        return None
    return FIXED_SIZE[s.element] if s.element in FIXED_SIZE else s.count * ELEMENTARY[s.element][0]


def _elementary_hmi_type(data_type):
    """The HmiDataType ELEMENTARY fixes for data_type, None for a DataType it does not hold or one written otherwise."""
    s = shape(data_type)
    return s.prefix + ELEMENTARY[s.element][1] if s.element in ELEMENTARY and s.exact else None


def _paired(data_type):
    """Whether the HmiDataType of data_type is the one an export pairs it with: a TAUGHT or a FIXED_SIZE type."""
    s = shape(data_type)
    return _taught(data_type) or (s.element in FIXED_SIZE and not s.prefix)


@dataclass(frozen=True)
class Knowledge:
    sizes: dict           # {DataType: Length} of the TAUGHT DataTypes, from files
    pairs: dict           # {DataType: HmiDataType} of the _paired DataTypes, as the files pair them, one way only; a
                          # FIXED_SIZE one only from files that give it its size
    confirmed: frozenset  # ELEMENTARY DataTypes and arrays of one that a file pairs with ELEMENTARY's HmiDataType, at
                          # their size

    def size(self, data_type):
        if _taught(data_type):
            return self.sizes.get(data_type)
        return _fixed_size(data_type)

    def size_problem(self, data_type):
        """Why the size of data_type is not known, None when it is."""
        if self.size(data_type) is not None:
            return None
        problem = data_type_problem(data_type)
        if problem:
            return problem
        s = shape(data_type)
        if _uncountable(s):
            return ("The Length of an array of %s (%s) is not known: no export of one was read%s. Make such a tag in "
                    "TIA." % (s.element, data_type, ', and its bits may be counted otherwise than its elements'
                              if s.element == 'Bool' else ''))
        if s.uncounted == 'backwards':
            return ("The bounds of %s run backwards: an upper bound is below its lower one, so its size is not known. "
                    "Write the lower bound first." % data_type)
        if s.uncounted:
            return ("The bounds of %s are not numbers, so its size is not known. Write them as numbers, or make "
                    "such a tag in TIA." % data_type)
        return ("The size of data type %s is not known: no tag table file of this repo holds a tag of it. Then %s, "
                "and generate again." % (data_type, EXPORT_ONE))

    def hmi_type(self, data_type):
        """The HmiDataType TIA takes for data_type, None when nothing knows it."""
        if _paired(data_type):
            return self.pairs.get(data_type)
        return _elementary_hmi_type(data_type)

    def takes(self, data_type):
        """Whether hmi_type(data_type) is one TIA was seen to take: SEEN, or paired so in a file (an array: or its
        element)."""
        if _paired(data_type):
            return data_type in self.pairs
        s = shape(data_type)
        return s.exact and (s.element in SEEN or s.element in self.confirmed or data_type in self.confirmed)


def _tags(tables):
    for d in tables:
        for t in d.tree.iter('Hmi.Tag.Tag'):
            yield (d, t, t.findtext('LinkList/DataType/Name'), t.findtext('LinkList/HmiDataType/Name'),
                   attribute(t, 'Length'))


def knowledge(repo):
    """What the tag table files under hmi/tags of repo add to ELEMENTARY and FIXED_SIZE: the Length and HmiDataType
    of the TAUGHT DataTypes, the HmiDataType of the FIXED_SIZE ones, and which ELEMENTARY HmiDataTypes a file
    confirms. Of a type of a fixed size, a file teaches only at that size, and never changes it. A DataType whose
    tags there disagree on their Length or HmiDataType teaches nothing."""
    exports = [d for d in repo.tag_tables if d.origin != GENERATED] + list(repo.other_tag_tables)
    lengths, pairs = defaultdict(Counter), defaultdict(Counter)
    for _d, _t, dtype, htype, length in _tags(exports):
        if dtype and length and LENGTH.fullmatch(length.strip()):
            lengths[dtype][int(length)] += 1
        if dtype and htype:
            pairs[dtype][htype] += 1
    one = {t: next(iter(c)) for t, c in pairs.items() if len(c) == 1}
    sizes = {t: next(iter(c)) for t, c in lengths.items() if len(c) == 1}
    at_size = {t: h for t, h in one.items() if _fixed_size(t) is not None and sizes.get(t) == _fixed_size(t)}
    taught = {t: h for t, h in one.items() if _taught(t)}
    fixed = {t: h for t, h in at_size.items() if _paired(t)}
    return Knowledge({t: n for t, n in sizes.items() if _taught(t)}, {**taught, **fixed},
                     frozenset(t for t, h in at_size.items() if h == _elementary_hmi_type(t)))


def check(repo, ctx):
    generated = [d for d in repo.tag_tables if d.origin == GENERATED]
    if not generated:
        return
    k = knowledge(repo)
    for d, t, dtype, htype, length in _tags(generated):
        name = attribute(t, 'Name')
        problem = data_type_problem(dtype)
        if problem:
            yield error(d.path, name, 'tagtable.data-type', '%s %s' % (problem, TIA_ENDED))
            continue
        size = k.size(dtype)
        if size is None:
            yield error(d.path, name, 'tagtable.length', '%s Length %s cannot be checked. %s'
                        % (k.size_problem(dtype), length or '(none)', TIA_ENDED))
            if not _taught(dtype):
                continue                    # refused whatever an export shows: its HmiDataType does not matter
        elif length is None or length.strip() != str(size):
            yield error(d.path, name, 'tagtable.length',
                        "Length %s, but the length of data type %s is %d: TIA refuses it with \"Cannot set the length "
                        "for the tag because data of the connected data type would have to be overwritten\". %s"
                        % (length if length is not None else '(none)', dtype, size, TIA_ENDED))
        want = k.hmi_type(dtype) if dtype else None
        if want is None or htype != want:
            yield error(d.path, name, 'tagtable.hmi-data-type',
                        "HmiDataType %s, but TIA takes %s for data type %s; HmiDataType Word on a PLC Word failed "
                        "with \"The HMI data type Word was not found\".%s Generate again. %s"
                        % (htype or '(none)', want or 'an HmiDataType no tag table file of this repo shows',
                           dtype or '(none)', '' if want else ' Then %s.' % EXPORT_ONE, TIA_ENDED))
        elif not k.takes(dtype):
            yield error(d.path, name, 'tagtable.hmi-data-type',
                        "HmiDataType %s for data type %s is what TIA should take, but no export was seen to pair them "
                        "and HmiDataType Word on a PLC Word failed with \"The HMI data type Word was not found\". "
                        "If TIA has it, %s, then generate again. %s" % (htype, dtype, EXPORT_ONE, TIA_ENDED))
