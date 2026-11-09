"""Read a SimaticML block export (.xml: OBs, and blocks TIA would not export as SIMATIC SD) into the model of
s7dcl.py: interface, block properties, networks; LAD (FlgNet: parts and wires) into the rungs of a .s7dcl LAD
network, SCL (StructuredText tokens) into its text. Diff, layout, verify and page work on it unchanged.

FlgNet -> rungs: every wire that carries power flow is a node, an O (OR) part of a LAD network joins the wires at its
inputs and its output into one node (_joins_wires; else it is a part like the others, as in FBD, where an O is a gate
and no junction). Each other part is an element from the node at its rung-in (in / pre / en / IN / s) to the node at
its rung-out (out / eno / Q / q), or to the end of the rung when nothing is connected there; a box input fed by logic
is a pin on its node ('wire#wN'). The elements are then written as rungs the way the SD exporter does (checked against
blocks exported in both formats): the first rung from the power rail to the first element that ends a rung, at a
junction through the first input; then, for the nodes of each rung in turn, the other branches that end there and
those that start there, of those that end there the one that starts on the node written last first, else in the order
of the O's inputs (TIA's one O of an OR holds the ends of the legs before the branches inside them); the logic feeding a
box pin after the rung of its box. A negated pin reads NOT: 'in2 := NOT #x', 'in1 := NOT wire#wN', and 'out => NOT' on a
pin the rung runs through; an AND gate's rung-in and output as TIA's FBD text, 'NOT A( in2 := #b ) NOT' after 'RUNG #a';
a negated contact or coil operand is I_Contact / I_Coil.
"""
import re
import xml.etree.ElementTree as ET

from . import instructions, s7dcl
from .iface import setpoint_default
from .names import object_name
from .s7dcl import RELATIONS, Block, Element, Interface, Member, Network, Rung, wire_of

KINDS = {'SW.Blocks.OB': 'ORGANIZATION_BLOCK', 'SW.Blocks.FB': 'FUNCTION_BLOCK', 'SW.Blocks.FC': 'FUNCTION',
         'SW.Blocks.GlobalDB': 'DATA_BLOCK', 'SW.Blocks.InstanceDB': 'DATA_BLOCK', 'SW.Blocks.ArrayDB': 'DATA_BLOCK',
         'SW.Types.PlcStruct': 'TYPE'}

SECTIONS = {'Input': 'INPUT', 'Output': 'OUTPUT', 'InOut': 'IN_OUT', 'Static': 'STAT', 'Temp': 'TEMP',
            'Constant': 'CONSTANT', 'None': 'UDT'}

LANGS = {'F_LAD': 'LAD', 'F_FBD': 'FBD', 'F_SCL': 'SCL', 'F_STL': 'STL'}


BLOCK_RE = r'<SW\.(Blocks\.[A-Za-z]+|Types\.PlcStruct)[ >]'      # also for git grep -E
ELEMENT_RE = r'<SW\.[A-Za-z.]+[ >/]'                              # the export's object: its first SW. element


def is_block(text):
    """True for the SimaticML export of a PLC block or PLC data type (not an HMI screen or a tag table, nor a global
    library type's version metadata holding one further down)."""
    return export_kind(text) == 'block'


def export_kind(text):
    """'block' for the SimaticML export of a PLC block or data type; for an export holding one further down, why it is
    no block export (to name it as skipped); else None (an HMI screen, a tag table)."""
    m = re.search(ELEMENT_RE, text or '')
    return element_kind(m and m.group(), bool(m) and bool(re.search(BLOCK_RE, text)))


def element_kind(first, holds):
    """export_kind from the first SW. element of an export (None: none) and whether a block element is in it."""
    if first and re.match(BLOCK_RE, first):
        return 'block'
    return 'no block export: %s holding a block' % first[1:-1].strip() if first and holds else None


def same_export(a, b):
    """Two SimaticML texts (or None) that differ at most in the export time, which TIA stamps on every export."""
    if a is None or b is None:
        return a is b
    return a == b or _CREATED.sub('', a) == _CREATED.sub('', b)


_CREATED = re.compile(r'<Created>[^<]*</Created>')


def _no_text(item):
    al = _kid(item, 'AttributeList')
    text = _kid(al, 'Text') if al is not None else None
    return text is None or not (text.text or '').strip()


def _expansion(sections):
    """The Sections under a Member hold only what TIA writes when it expands a UDT member: members, a struct's nested,
    with a name, a data type, a version, a start value or a comment (the report sees those), nothing a user set
    otherwise."""
    return all(_bare_member(m) for section in _kids(sections, 'Section') for m in _kids(section))


def _bare_member(m):
    if _local(m.tag) != 'Member' or set(m.attrib) - {'Name', 'Datatype', 'Version'}:
        return False
    for c in m:
        tag = _local(c.tag)
        if tag not in ('StartValue', 'Comment', 'Member', 'Sections') or (tag == 'Member' and not _bare_member(c)) \
                or (tag == 'Sections' and not _expansion(c)):
            return False
    return True


def _other_language(el, lang):
    tag = _local(el.tag)
    if tag == 'MultilingualTextItem':
        return _text(_kid(el, 'AttributeList'), 'Culture') != lang
    return tag == 'MultiLanguageText' and el.get('Lang') != lang


def _plain(el, uids=None, lang=None):
    """An element without what TIA writes differently per export: the export time and how it was exported, the object
    numbers (ID left out; UId, which tells what a wire connects, numbered by first appearance in its network), the order
    of the languages and a language without a text, TIA's expansion of a UDT member under a Member (_expansion), and a
    block's number while automatic numbering is on (TIA's; a user cannot set it then, and an .s7dcl does not write it).
    lang: only this language's texts (the others are compared apart, as texts)."""
    tag = _local(el.tag)
    if uids is None or tag == 'SW.Blocks.CompileUnit':
        uids = {}
    auto = tag == 'AttributeList' and _text(el, 'AutoNumber') == 'true'
    kids = [_plain(c, uids, lang) for c in el
            if _local(c.tag) != 'DocumentInfo' and not (tag == 'Member' and _local(c.tag) == 'Sections' and _expansion(c))
            and not (_local(c.tag) == 'MultilingualTextItem' and _no_text(c)) and not (lang and _other_language(c, lang))
            and not (auto and _local(c.tag) == 'Number')]
    if tag == 'ObjectList' and all(k[0] == 'MultilingualTextItem' for k in kids):
        kids = sorted(kids, key=repr)
    attrs = sorted((k, uids.setdefault(v, len(uids)) if k == 'UId' else v) for k, v in el.attrib.items() if k != 'ID')
    return tag, attrs, (el.text or '').strip(), kids


def _member_sources(owner, path, lang, out):
    """{path: a member's part of the file, without its struct members, which have their own}."""
    for m in _kids(owner, 'Member'):
        here = path + _name(m.get('Name'))
        plain = _plain(m, lang=lang)
        out[here] = plain[:3] + ([k for k in plain[3] if k[0] != 'Member'],)
        _member_sources(m, here + '.', lang, out)


def _block_of(xml):
    root = ET.fromstring(xml.lstrip('\ufeff').encode('utf-8'))
    return next((c for c in root if _local(c.tag) in KINDS), None)


def _read(itf):
    """{path: what the report read of a member}, in the paths of _member_sources."""
    out = {}

    def walk(member, path):
        for m in member.children.values():
            here = path + _name(m.name)
            out[here] = (m.type, m.value, m.comment, m.retain, sorted(m.attrs.items()), m.section,
                         sorted((k, v) for k, v in itf.start.items() if k == here or k.startswith((here + '.', here + '['))))
            walk(m, here + '.')
    walk(itf.root, '')
    return out


# What the report reads of a member's fields, as positions in _read's values. A field not here it does not read.
_MEMBER_READS = {'Datatype': (0,), 'Remanence': (3,), 'StartValue': (1, 6), 'Comment': (2,), 'AttributeList': (4,),
                 'Subelement': (6,), 'Sections': (6,)}
# Which properties the report shows a block attribute as (parse_block), by the attribute's name.
_ATTRIBUTE_READS = {'Number': ('S7_BlockNumber',), 'SetENOAutomatically': ('S7_GenerateENOforSCL',),
                    'IsIECCheckEnabled': ('S7_IECCheck',), 'MemoryLayout': ('S7_Optimized',),
                    'ProgrammingLanguage': ('S7_PreferredLanguage', 'S7_Safety'),
                    'IsRetainMemResEnabled': ('S7_StandardRetain',), 'HeaderVersion': ('S7_Version',),
                    'SecondaryType': ('Event class',), 'Title': ('S7_BlockTitle',), 'Comment': ('S7_BlockComment',)}


# What TIA writes on a member of a section that has the field; another section has none.
_SECTION_DEFAULTS = {'Remanence': {None, 'NonRetain'}, 'Accessibility': {None, 'Public'}}


def _fields(plain):
    """{field: its value} of a member's part of the file: its attributes and its children by tag."""
    out = {k: v for k, v in plain[1] if k != 'Name'}
    for kid in plain[3]:
        out.setdefault(kid[0], []).append(kid)
    return out


def _member_unread(b, a, rb, ra):
    """A member's field differs and what the report reads of it does not: told apart field by field, so also on a member
    whose row is changed for another field. A member gone to another section, which the report shows, gets that section's
    defaults: no difference of its own. rb, ra: _read's values, None where the report does not read the member."""
    fb, fa = _fields(b), _fields(a)
    other_section = rb is not None and ra is not None and rb[5] != ra[5]
    for field in set(fb) | set(fa):
        if fb.get(field) != fa.get(field):
            if other_section and field in _SECTION_DEFAULTS and {fb.get(field), fa.get(field)} <= _SECTION_DEFAULTS[field]:
                continue
            reads = _MEMBER_READS.get(field, ())
            if rb is None or ra is None or not any(rb[k] != ra[k] for k in reads):
                return True
    return False


def unread_differs(bxml, axml, bblk, ablk, lang=None):
    """The interface or a block attribute of two SimaticML exports differs in what the report does not read: a member's
    field (_member_unread), an attribute whose property the report does not show differing. Language items aside: they
    are compared as texts."""
    lang = lang or s7dcl.LANG
    b, a = _block_of(bxml), _block_of(axml)
    if b is None or a is None:
        return True

    def members(blk):
        out = {}
        al = _kid(blk, 'AttributeList')
        for itf in _kids(al, 'Interface'):
            for secs in _kids(itf, 'Sections'):
                for sec in _kids(secs, 'Section'):
                    if sec.get('Name') != 'Return':              # the declaration shows it
                        _member_sources(sec, '', lang, out)
        return out
    mb, ma = members(b), members(a)
    rb, ra = _read(bblk.interface), _read(ablk.interface)
    if not rb and not ra:                                        # an instance DB: its FB's interface is not read
        if mb != ma:
            return True
    for path in set(mb) & set(ma):
        if mb[path] != ma[path] and _member_unread(mb[path], ma[path], rb.get(path), ra.get(path)):
            return True

    def attributes(blk):
        out = {}
        al = _kid(blk, 'AttributeList')
        auto = _text(al, 'AutoNumber') == 'true'
        for c in al:
            if _local(c.tag) not in ('Interface', 'Name') and not (auto and _local(c.tag) == 'Number'):
                out[_local(c.tag), c.get('Name')] = _plain(c, lang=lang)
        for ol in _kids(blk, 'ObjectList'):
            for c in ol:
                if _local(c.tag) != 'SW.Blocks.CompileUnit':
                    out[c.get('CompositionName') or _local(c.tag), None] = _plain(c, lang=lang)
        return out
    ab, aa = attributes(b), attributes(a)
    for k in set(ab) | set(aa):
        if ab.get(k) != aa.get(k) and not any(bblk.props.get(p) != ablk.props.get(p) for p in _ATTRIBUTE_READS.get(k[0], ())):
            return True
    return _frame(bxml, lang) != _frame(axml, lang)


def _frame(xml, lang):
    """A SimaticML export without what is compared apart: the block's attributes but its interface, the members of its
    sections (of a function's Return member only its type, which the declaration shows), its networks, texts and other
    objects; of the block's name, which the page shows, only that it is there; the TIA version that exported it, which
    files_alike tells only when nothing else changed. What is left: the document's and the block element's own
    fields, those of the interface and its sections, and anything else they hold."""
    root = ET.fromstring(xml.lstrip('\ufeff').encode('utf-8'))
    for eng in _kids(root, 'Engineering'):
        eng.attrib.pop('version', None)
    blk = next((c for c in root if _local(c.tag) in KINDS), None)
    for c in blk:
        tag = _local(c.tag)
        for x in list(c):
            if tag == 'AttributeList' and _local(x.tag) == 'Name':
                x.text = None
            elif tag == 'ObjectList' or (tag == 'AttributeList' and _local(x.tag) != 'Interface'):
                c.remove(x)
    for sec in blk.iterfind('./{*}AttributeList/{*}Interface/{*}Sections/{*}Section'):
        for m in _kids(sec, 'Member'):
            if sec.get('Name') == 'Return':
                m.attrib.pop('Datatype', None)
            else:
                sec.remove(m)
    return _plain(root, lang=lang)


def text_entries(xml, lang=None):
    """[(the text in the report's language, ((language, text), ...) in the others)] of a SimaticML export: its multilingual
    texts and comments, those with a text in another language."""
    lang = lang or s7dcl.LANG
    try:
        root = ET.fromstring(xml.lstrip('\ufeff').encode('utf-8'))
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        tag = _local(el.tag)
        texts = []
        if tag == 'MultilingualText':
            for ol in _kids(el, 'ObjectList'):
                for item in _kids(ol, 'MultilingualTextItem'):
                    al = _kid(item, 'AttributeList')
                    text = _kid(al, 'Text') if al is not None else None
                    if text is not None and (text.text or '').strip():
                        texts.append((_text(al, 'Culture'), text.text))
        elif tag == 'Comment':
            texts = [(c.get('Lang'), c.text) for c in _kids(el, 'MultiLanguageText') if (c.text or '').strip()]
        others = tuple(sorted(x for x in texts if x[0] != lang))
        if others:
            out.append((next((t for k, t in texts if k == lang), ''), others))
    return out


def alike_exports(a, b):
    """Two SimaticML texts that differ at most in what TIA writes differently per export."""
    if same_export(a, b):
        return True
    try:
        return _plain(ET.fromstring(a.lstrip('\ufeff').encode('utf-8'))) == _plain(ET.fromstring(b.lstrip('\ufeff').encode('utf-8')))
    except ET.ParseError:
        return False


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _kids(el, name=None):
    return [c for c in el if name is None or _local(c.tag) == name]


def _kid(el, name):
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el, name, default=''):
    c = _kid(el, name) if el is not None else None
    return (c.text or '').strip() if c is not None and c.text else default


def _mltext(owner, composition, lang):
    """Text of the MultilingualText of `owner` with this CompositionName: `lang`, else the first that is not
    empty."""
    for objs in _kids(owner, 'ObjectList'):
        for mt in _kids(objs, 'MultilingualText'):
            if mt.get('CompositionName') != composition:
                continue
            texts = []
            for ol in _kids(mt, 'ObjectList'):
                for item in _kids(ol, 'MultilingualTextItem'):
                    al = _kid(item, 'AttributeList')
                    texts.append((_text(al, 'Culture'), (_kid(al, 'Text').text or '') if _kid(al, 'Text') is not None
                                  else ''))
            own = next((t for c, t in texts if c == lang), '')
            return own or next((t for _, t in texts if t), '')
    return ''


# ---------------------------------------------------------------- operands

_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

# Names the SD export quotes although they are identifiers (TIA's own list is not published): in SCL the reserved
# words and a few more, in LAD also instruction names and address mnemonics (as seen in the .s7dcl exports of real
# projects).
SCL_KEYWORDS = set('''
    to by do if of or and not xor mod for else elsif then case while repeat until exit continue return goto true false
    array struct type begin const label function function_block organization_block data_block var var_input var_output
    var_in_out var_temp end_var end_if end_for end_while end_case end_repeat end_struct end_type region end_region ref
    ref_to null at on port sequence
    '''.split())
LAD_KEYWORDS = SCL_KEYWORDS | set('interlock interface remote entry timer override id lt gt le ge eq ne left right mid '
                                  'max min ew pd'.split())


def _name(n, quoted=False, keywords=LAD_KEYWORDS):
    return '"%s"' % n if quoted or not _IDENT.match(n) or n.lower() in keywords else n


def _constant(acc):
    c = _kid(acc, 'Constant')
    if c is None:
        return ''
    if c.get('Name'):                                         # a named constant
        return c.get('Name')
    return _text(c, 'ConstantValue')


def operand(acc):
    """Text of an Access as .s7dcl writes it: '#a.b[1, #i]', '"DB".x', literal values, '#CONST'."""
    scope = acc.get('Scope')
    if scope in ('LiteralConstant', 'TypedConstant'):
        return _constant(acc)
    if scope == 'LocalConstant':
        return '#' + _name(_constant(acc))
    if scope == 'GlobalConstant':
        return '"%s"' % _constant(acc)
    if scope == 'Label':                                      # a jump label: its name, as .s7dcl writes it
        return (_kid(acc, 'Label').get('Name') or '') if _kid(acc, 'Label') is not None else ''
    if scope == 'SystemType':                                 # a type constant: its name, as .s7dcl writes it
        return _text(acc, 'DataType')
    sym = _kid(acc, 'Symbol')
    if sym is None and _kid(acc, 'Address') is not None:
        return address(_kid(acc, 'Address'))
    if sym is None:
        return _constant(acc) or scope or ''
    parts = []
    for k, comp in enumerate(_kids(sym, 'Component')):
        s = _name(comp.get('Name'), quoted=(k == 0 and scope == 'GlobalVariable'))
        if comp.get('AccessModifier') == 'Reference':
            s += '^'
        idx = [operand(a) for a in _kids(comp, 'Access')]
        if idx:
            s += '[%s]' % ', '.join(idx)
        parts.append(s)
    text = '.'.join(parts)
    return '#' + text if scope == 'LocalVariable' else text


_AREAS = {'Input': 'I', 'Output': 'Q', 'Memory': 'M'}
_SIZES = {'Byte': 'B', 'SInt': 'B', 'USInt': 'B', 'Char': 'B', 'Word': 'W', 'Int': 'W', 'UInt': 'W', 'DWord': 'D', 'DInt': 'D',
          'UDInt': 'D', 'Real': 'D', 'LWord': 'L', 'LInt': 'L', 'ULInt': 'L', 'LReal': 'L'}


def address(a):
    """An absolute address as .s7dcl writes it: %T1, %C1; of an input, output or memory %I1.0, %MW2. Any other is written
    with all it holds: two different ones never read the same."""
    area, typ, offset = a.get('Area'), a.get('Type'), a.get('BitOffset') or '0'
    if area in ('Timer', 'Counter') and offset.isdigit():
        return '%%%s%s' % (area[0], offset)
    if area in _AREAS and offset.isdigit() and (typ == 'Bool' or typ in _SIZES):
        byte, bit = divmod(int(offset), 8)
        return '%%%s%d.%d' % (_AREAS[area], byte, bit) if typ == 'Bool' else '%%%s%s%d' % (_AREAS[area], _SIZES[typ], byte)
    return ' '.join('%s=%s' % kv for kv in sorted(a.attrib.items()))


# ---------------------------------------------------------------- SCL

# A parameter TIA writes in quotes in SCL, as its .s7dcl does; SimaticML holds only its name.
SCL_QUOTED = {'PORT': '"PORT"'}


def scl_text(st, lang=None):
    """Source text of a StructuredText network."""
    out = []
    _text_walker(out, lang)(st)
    return ''.join(out)


def stl_text(sl, lang=None):
    """Source text of a StatementList network: a statement a line, its parts as the export holds them (TIA's own token
    names: Assign, where the editor writes =). COMMENT and EMPTY_LINE are tokens of a line without a statement."""
    lines = []
    for statement in _kids(sl, 'StlStatement'):
        parts = []
        for c in statement:
            buf = []
            _text_walker(buf, lang, True)([c])
            if ''.join(buf).strip():
                parts.append(''.join(buf).strip())
        lines.append(' '.join(parts))
    return '\n'.join(lines)


def _text_walker(out, lang, stl=False):
    """A function that writes the text of an element's children into out. stl: a parameter on a line of its own, as its
    export has no token between its name and its operand."""
    lang = lang or s7dcl.LANG

    def write_comments(el):                                  # of an element written by its names only
        for note in el.iter():
            if _local(note.tag) in ('LineComment', 'Comment'):
                out.append(' ')
                walk([note])

    def walk(el):
        for c in el:
            t = _local(c.tag)
            if t == 'Blank':
                out.append(' ' * int(c.get('Num', '1')))
            elif t == 'NewLine':
                out.append('\n' * int(c.get('Num', '1')))
            elif t == 'Token':
                out.append(c.get('Text', ''))
            elif t == 'Text':
                out.append(c.text or '')
            elif t == 'StlToken':
                out.append('' if c.get('Text') in ('COMMENT', 'EMPTY_LINE') else c.get('Text', ''))
                walk(c)
            elif t == 'LineComment':                         # in a line: (* *); on its own or at the end of one: //
                bracket = c.get('Inserted') == 'true'        # NoClosingBracket="false" stands on // as well
                out.append('(*' if bracket else '//')
                walk(c)
                if bracket:
                    out.append('*)')
            elif t == 'Comment':                             # a multilingual comment, as in the palette
                texts = [(x.get('Lang'), x.text or '') for x in _kids(c, 'MultiLanguageText')]
                out.append('(/*%s*/)' % (next((x for k, x in texts if k == lang), '') or next((x for _, x in texts if x), '')))
            elif t == 'DataType':                            # TypeOf(#x) = Int
                out.append(c.text or '')
            elif t == 'Label':                               # GOTO a; a:
                out.append(c.get('Name', ''))
                walk(c)
            elif t == 'Address':                             # in a Symbol: TIA's note of where it lies
                pass
            elif t == 'Access':
                if stl and _kid(c, 'Instruction') is None and _kid(c, 'CallInfo') is None:   # STL holds no token in it
                    out.append(operand(c))
                    write_comments(c)                        # TIA keeps an end-of-line comment in the operand
                else:
                    _scl_access(c, out, walk)
            elif t == 'Component':
                q = any(_local(a.tag) == 'BooleanAttribute' and a.get('Name') == 'HasQuotes' and a.text == 'true'
                        for a in c)
                out.append(_name(c.get('Name'), q, SCL_KEYWORDS))
                walk(c)
            elif t in ('Constant',):
                out.append(_constant_scl(c))
            elif t in ('ConstantValue', 'ConstantType', 'BooleanAttribute', 'StringAttribute', 'IntegerAttribute'):
                pass
            elif t == 'Parameter':
                name = c.get('Name', '')
                out.append('\n    %s ' % name if stl else SCL_QUOTED.get(name, name))
                walk(c)
            elif t == 'Instruction':                         # typed: CONCAT + String -> CONCAT_STRING
                out.append(c.get('Name', '') + ''.join('_' + (v.text or '').upper() for v in _kids(c, 'TemplateValue')
                                                       if v.get('Type') == 'Type'))
                walk(c)
            elif t == 'CallInfo':
                inst = _kid(c, 'Instance')
                if inst is not None:
                    _scl_access(inst, out, walk)
                elif c.get('Name'):
                    out.append('"%s"' % c.get('Name'))
                walk(c)
            elif t == 'Instance':                            # a CallInfo writes its name, an Instruction does not
                write_comments(c)
            else:
                walk(c)
    return walk


def _constant_scl(c):
    v = _text(c, 'ConstantValue')
    typ = _kid(c, 'ConstantType')
    return v if typ is None or c.get('Name') is None else v


def _scl_access(acc, out, walk):
    scope = acc.get('Scope')
    if _kid(acc, 'Address') is not None and _kid(acc, 'Symbol') is None:
        out.append(address(_kid(acc, 'Address')))
        return
    if scope in ('LocalVariable', 'LocalConstant') or (_local(acc.tag) == 'Instance' and scope == 'LocalVariable'):
        out.append('#')
    if _local(acc.tag) == 'Instance':
        for comp in _kids(acc, 'Component'):
            out.append(_name(comp.get('Name'), scope == 'GlobalVariable'))
        return
    if scope in ('LiteralConstant', 'TypedConstant', 'LocalConstant', 'GlobalConstant'):
        c = _kid(acc, 'Constant')
        if c is not None and c.get('Name'):
            out.append(_name(c.get('Name'), scope == 'GlobalConstant'))
        elif c is not None:
            out.append(_text(c, 'ConstantValue'))
        return
    walk(acc)


# ---------------------------------------------------------------- LAD

# rung-in and rung-out pins, in order of preference
RUNG_IN = ('in', 'pre', 'en', 'IN', 's', 'S', 'CU', 'CD')
RUNG_OUT = ('out', 'eno', 'Q', 'q', 'QU', 'Q1')

def _card_pins(name, card):
    """Pins of the parts the export sizes by their Card (cardinality), every one of them as TIA draws them:
    [(name and order as the .s7dcl export writes them, name in the XML, direction)]; None for other parts. The SD
    export writes a destination dst<k> where the XML has dest<k>, and else before the destinations."""
    dests = [('dst%d' % k, 'dest%d' % k, '=>') for k in range(card)]
    if name == 'JmpList':
        return [('k', 'k', ':=')] + dests
    if name == 'Switch':
        return [('k', 'k', ':=')] + [('case%d' % k, 'case%d' % k, ':=') for k in range(card)] + \
            [('else', 'else', '=>')] + dests
    if name == 'Calc':
        return [('in%d' % k, 'in%d' % k, ':=') for k in range(1, card + 1)] + [('out', 'out', '=>')]
    return None

# pins of system instructions: (name as .s7dcl writes it, direction); pins not listed keep their name, ':='
def _seq(prefix, n, d):
    return ' '.join('%s%02d%s' % (prefix, k, d) for k in range(n))


# Pins of system instructions in the order and spelling of the SD export ('name:=' input or in-out, 'name=>'
# output; from the .s7dcl exports of real projects). The XML lists no pins for a part, and its wires do
# not keep that order once a pin is fed by logic.
PINS = {k: v.split() for k, v in {
    'TON': 'PT:=pt ET=>et', 'TOF': 'PT:=pt ET=>et', 'TP': 'PT:=pt ET=>et', 'TONR': 'R:=r PT:=pt ET=>et',
    'R_TRIG': 'CLK:=clk Q=>q', 'F_TRIG': 'CLK:=clk Q=>q',
    'ESTOP1': 'E_STOP:= ACK_NEC:= ACK:= TIME_DEL:= Q=> Q_DELAY=> ACK_REQ=> DIAG=>',
    'FDBACK': 'ON:= FEEDBACK:= QBAD_FIO:= ACK_NEC:= ACK:= FDB_TIME:= Q=> ERROR=> ACK_REQ=> DIAG=>',
    'ACK_GL': 'ACK_GLOB:=',
    'RCVDP': 'ACK_REI:= %s SUBI_00:= SUBI_01:= SUBDI_00:= DP_DP_ID:= TIMEOUT:= LADDR:= ERROR=> SUBS_ON=> '
             'ACK_REQ=> SENDMODE=> %s RD_I_00=> RD_I_01=> RD_DI_00=> RET_DPRD=> RET_DPWR=> DIAG=>'
             % (_seq('SUBBO_', 16, ':='), _seq('RD_BO_', 16, '=>')),
    'SENDDP': '%s SD_I_00:= SD_I_01:= SD_DI_00:= DINTMODE:= DP_DP_ID:= TIMEOUT:= LADDR:= ERROR=> SUBS_ON=> '
              'RET_DPRD=> RET_DPWR=> DIAG=>' % _seq('SD_BO_', 16, ':='),
    'Runtime': 'ret_val=> mem:=', 'RD_SYS_T': 'RET_VAL=> OUT=>', 'RD_SINFO': 'RET_VAL=> TOP_SI=> START_UP_SI=>',
    'DPRD_DAT': 'LADDR:= RET_VAL=> RECORD=>', 'InRange': 'min:= in:= max:=', 'OutRange': 'min:= in:= max:=',
    'TSEND_C': 'REQ:= CONT:= LEN:= DONE=> BUSY=> ERROR=> STATUS=> CONNECT:= DATA:= ADDR:= COM_RST:=',
    'TRCV_C': 'EN_R:= CONT:= LEN:= ADHOC:= DONE=> BUSY=> ERROR=> STATUS=> RCVD_LEN=> CONNECT:= DATA:= ADDR:= '
              'COM_RST:=',
    'T_DIAG': 'REQ:= ID:= DONE=> BUSY=> ERROR=> STATUS=> RESULT:=',
    'GetChecksum': 'Scope:= Range:= Subrange:= Done=> Busy=> Error=> Status=> Checksum:=',
}.items()}


def _pin(spec):
    """'PT:=pt' -> ('PT', ':=', 'pt'); 'Q=>' -> ('Q', '=>', 'Q')."""
    m = re.match(r'^(\w+)(:=|=>)(\w*)$', spec)
    return m.group(1), m.group(2), m.group(3) or m.group(1)


def _output(pin):
    """An output by its name, for a pin no wire tells the direction of (a negated pin with nothing connected)."""
    return bool(re.match(r'^(out\d*|ret_val|done|busy|error|status|eno|q|et|cv)$', pin, re.I))


# templates the SD export writes (a type the instruction fixes is left out there)
TEMPLATES = ('SrcType', 'DestType', 'time_type', 'value_type', 'count_type')

# parts whose single remaining operand is written inline, without a name
INLINE = {'Contact', 'Coil', 'SCoil', 'RCoil', 'ResetIECTimerCoil', 'CuCoil', 'CdCoil', 'PBox', 'NBox'}


class _Net:
    """A FlgNet as parts, operands and wires."""

    def __init__(self, flg):
        self.access = {}             # uid -> operand text
        self.parts = []              # [(uid, element tag, xml element)] in document order
        parts = _kid(flg, 'Parts')
        for p in (parts if parts is not None else []):
            t = _local(p.tag)
            if t == 'Access':
                self.access[p.get('UId')] = operand(p)
            elif t in ('Part', 'Call'):
                self.parts.append((p.get('UId'), t, p))
        self.pin = {}                # (uid, pin) -> ('flow', wire uid) | ('op', text) | ('open', '')
        self.driven = {}             # (uid, pin) -> whether a wire starts at it (an output): a wire lists its source first
        self.rail = None
        wires = _kid(flg, 'Wires')
        for w in (wires if wires is not None else []):
            cons = list(w)
            idents = [c for c in cons if _local(c.tag) == 'IdentCon']
            rail = any(_local(c.tag) == 'Powerrail' for c in cons)
            if rail:
                self.rail = w.get('UId')
            flow = rail or sum(_local(c.tag) == 'NameCon' for c in cons) > 1
            for k, c in enumerate(cons):
                if _local(c.tag) == 'NameCon':
                    key = (c.get('UId'), c.get('Name'))
                    if len(cons) > 1:
                        self.driven[key] = k == 0
                    if idents:
                        self.pin[key] = ('op', self.access.get(idents[0].get('UId'), ''))
                    elif flow:
                        self.pin[key] = ('flow', w.get('UId'))
                    else:
                        self.pin[key] = ('open', '')


def label(flg):
    """The jump label of a FlgNet network: <Labels><LabelDeclaration><Label Name=...>, '' for none."""
    for lb in flg.iterfind('./{*}Labels/{*}LabelDeclaration/{*}Label'):
        return lb.get('Name') or ''
    return ''


def _joins_wires(uid, tag, p, net, lang):
    """An O of a LAD network with nothing but wires on it. A negated pin or an operand has to be read on its pin, and in
    FBD the O itself is logic the text has to hold."""
    return tag == 'Part' and p.get('Name') == 'O' and lang == 'LAD' and _kid(p, 'Negated') is None \
        and not any(u == uid and kind == 'op' for (u, _), (kind, _) in net.pin.items())


def lad_rungs(flg, prefix, lang='LAD'):
    """Rungs of a FlgNet network (see the module doc)."""
    net = _Net(flg)
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb == net.rail:
                ra, rb = rb, ra
            parent[rb] = ra
    order = {}                                                # O input wire -> its number
    flows = {}                                                # uid -> {pin: wire uid}
    for (uid, pin), (kind, w) in net.pin.items():
        if kind == 'flow':
            flows.setdefault(uid, {})[pin] = w
    els = []                                                  # [(uid, tag, xml, in wire, out wire, pins)]
    for uid, tag, p in net.parts:
        fl = flows.get(uid, {})
        if _joins_wires(uid, tag, p, net, lang):
            for pin, w in fl.items():
                union(fl.get('out', w), w)
                if pin != 'out':
                    order[w] = int(pin[2:] or 0)              # in1, in2, ...: the order of the branches
            continue
        spec = instructions.lookup(instructions.sd_name(p.get('Name'))) if tag == 'Part' else None
        rin_name = (spec and spec.rung_pin(0, fl)) or next((n for n in RUNG_IN if n in fl), None)
        rout_name = (spec and spec.rung_pin(1, fl)) or next((n for n in RUNG_OUT if n in fl), None)
        rin, rout = fl.get(rin_name), fl.get(rout_name)
        others = {n: w for n, w in fl.items() if n not in (rin_name, rout_name)}
        els.append([uid, tag, p, rin, rout, others, (rin_name, rout_name)])
    node = {}                                                 # find(wire) -> 'powerrail' | wN, named on first use

    def name(w):
        return name_of(find(w), rail, node)
    prod, cons = {}, {}
    for e in els:
        if e[3] is not None:
            cons.setdefault(find(e[3]), []).append(e)
        if e[4] is not None:
            prod.setdefault(find(e[4]), []).append(e)
    for n in prod:                                            # at a junction: in the order of the O inputs
        prod[n].sort(key=lambda e: order.get(e[4], 0))
    pinned = {find(w) for e in els for w in e[5].values()}
    # an output wire that leads nowhere ends the rung
    for e in els:
        if e[4] is not None and not cons.get(find(e[4])) and find(e[4]) not in pinned \
                and len(prod.get(find(e[4]), [])) == 1:
            prod.pop(find(e[4]), None)
            e[4] = None
    rail = find(net.rail) if net.rail else None
    seen = set()
    written = set()                                           # nodes a rung has written
    written_order = {}                                        # those nodes -> their number, along each rung in turn
    rungs = []
    count = [0]
    made = {}                                                 # uid -> Element

    def simple(n):
        return n != rail and n not in pinned and len(prod.get(n, [])) == 1 and len(cons.get(n, [])) == 1

    def element(e):
        if e[0] not in made:
            count[0] += 1
            made[e[0]] = _element('%s%d' % (prefix, count[0]), e, net, name)
        return made[e[0]]

    def behind(e, taken):
        """The node at e's rung-in, and the producer a rung through e goes on back through (None: it starts there)."""
        n = find(e[3]) if e[3] is not None else None
        if n is None or n == rail or n in written:
            return n, None
        return n, next((x for x in prod.get(n, []) if x[0] not in taken), None)

    def back(e):
        """Items from the start of the rung up to e: through the first producer not yet written, up to a node
        an earlier rung wrote."""
        items = [e]
        while True:
            n, p = behind(e, seen)
            if p is None:
                return n, items
            if not simple(n):
                items.insert(0, ('node', n))
                written.add(n)
            items.insert(0, p)
            seen.add(p[0])
            e = p

    def fwd(e):
        """Items after e: through the first consumer not yet written."""
        items = []
        while True:
            n = find(e[4]) if e[4] is not None else None
            if n is None:
                return items, None
            c = next((x for x in cons.get(n, []) if x[0] not in seen), None)
            if c is None or n in written:
                return items, n
            if not simple(n):
                items.append(('node', n))
                written.add(n)
            items.append(c)
            seen.add(c[0])
            e = c

    def start_of(e):
        """The node a rung through e would start on: where back(e) would end, without writing anything."""
        taken = seen | {e[0]}
        while True:
            n, p = behind(e, taken)
            if p is None:
                return n
            taken.add(p[0])
            e = p

    def inner_first(branches):
        """The branches, those starting on the node written last first: it is the innermost. Else in their order."""
        return sorted(branches, key=lambda x: -written_order.get(start_of(x), -1))

    def rung(e):
        """The rung through e, then the branches hanging from it, depth first (the order of the SD export)."""
        seen.add(e[0])
        start, head = back(e)
        tail, end = fwd(e)
        written.update((start, end))
        r = [start, head + tail, end]
        rungs.append(r)
        for n in [start] + [it[1] for it in r[1] if isinstance(it, tuple)] + [end]:
            if n is not None:
                written_order.setdefault(n, len(written_order))
        for it in r[1] + [('node', end)]:                     # the branches that end on it; those that only
            if isinstance(it, tuple):                         # start on it come with the rungs they end in
                for x in inner_first(prod.get(it[1], [])):
                    if x[0] not in seen:
                        rung(x)
            else:
                for w in it[5].values():
                    for x in prod.get(find(w), []):
                        if x[0] not in seen:
                            rung(x)

    ends = [e for e in els if e[4] is None or (not cons.get(find(e[4])) and find(e[4]) not in pinned)]
    for e in ends + els:
        if e[0] not in seen:
            rung(e)
    out = []
    for start, items, end in rungs:
        its = []
        for it in items:
            if isinstance(it, tuple):
                its.append(('node', name_of(it[1], rail, node)))
            else:
                its.append(element(it))
        out.append(Rung(name_of(start, rail, node) if start is not None else 'open',
                        its, name_of(end, rail, node) if end is not None else None))
    return out


def name_of(n, rail, node):
    if n == rail:
        return 'powerrail'
    if n not in node:
        node[n] = 'w%d' % (len(node) + 1)
    return node[n]


def _element(eid, e, net, name):
    uid, tag, p = e[0], e[1], e[2]
    pins = {pin: v for (u, pin), v in net.pin.items() if u == uid}
    templates, more = {}, {}
    card = None
    name_ = p.get('Name')
    instr = instructions.sd_name(name_)
    if name_ == 'SCALE' and _kid(p, 'Instance') is not None:     # the F-box of this name has an instance, the legacy SCALE (S_Scale) none
        instr = name_
    spec = instructions.lookup(instr)
    for tv in _kids(p, 'TemplateValue'):
        if tv.get('Name') in TEMPLATES or (spec and spec.reads(tv.get('Name'))):
            templates[tv.get('Name')] = (tv.text or '').strip()
        elif tv.get('Type') == 'Operation':               # a Switch relation: CASE0 EQ, in .s7dcl CASE0 := "=="
            templates[tv.get('Name')] = RELATIONS.get((tv.text or '').strip(), (tv.text or '').strip())
        elif tv.get('Name') == 'Card' and (tv.text or '').strip().isdigit():
            card = int(tv.text.strip())
        elif tv.get('Type') == 'Type':
            more[tv.get('Name')] = (tv.text or '').strip()
    flow = e[5]
    negated = {n.get('Name').lower(): n.get('Name') for n in _kids(p, 'Negated') if n.get('Name')}
    if name_ in ('Contact', 'Coil') and negated.pop('operand', None):
        instr = 'I_' + name_

    def value(pin):
        """What feeds the pin; a negated pin reads NOT and is taken off negated."""
        kind, v = pins.get(pin, ('open', ''))
        v = 'wire#' + name(flow[pin]) if pin in flow else v if kind == 'op' else ''
        return ('NOT ' + v).strip() if negated.pop(pin.lower(), None) else v

    def direction(pin):
        driven = net.driven.get((uid, pin))
        return '=>' if driven or (driven is None and (pin in RUNG_OUT or _output(pin))) else ':='

    def rung_negated():
        """The negated pins no parameter told: the rung runs through them, or nothing is connected."""
        return [(x, direction(x), 'NOT') for x in negated.values()]

    def with_unlisted(params, listed):
        """params with what is wired on a pin the instruction's own list leaves out (an operand on a call's EN):
        inputs first, as TIA draws EN, outputs last. The pins the rung runs through are told by the rung."""
        extra = [(x, direction(x), value(x)) for x, (kind, _) in pins.items()
                 if kind != 'open' and x not in listed and x not in e[6]]
        return [x for x in extra if x[1] == ':='] + params + [x for x in extra if x[1] == '=>']
    if tag == 'Call':
        ci = _kid(p, 'CallInfo')
        params = []
        order = {'Input': 0, 'InOut': 1, 'Output': 2}                          # as the SD export lists them
        for prm in sorted(_kids(ci, 'Parameter'), key=lambda x: order.get(x.get('Section'), 1)):
            n = prm.get('Name')
            params.append((n, '=>' if prm.get('Section') == 'Output' else ':=', value(n)))
        params = with_unlisted(params, {prm.get('Name') for prm in _kids(ci, 'Parameter')})
        params += rung_negated()
        inst = _kid(ci, 'Instance')
        if inst is not None and inst.get('Scope') == 'LocalVariable':
            return Element(eid, 'CALL', '#' + '.'.join(_name(c.get('Name')) for c in _kids(inst, 'Component')),
                           params, templates)
        if inst is not None:
            return Element(eid, 'CALL', None, params, templates,
                           call='.'.join(c.get('Name') for c in _kids(inst, 'Component')))
        return Element(eid, 'CALL', None, params, templates, call=ci.get('Name'))
    rest = [pin for pin in pins if pin not in e[6]]
    inst = _kid(p, 'Instance')
    instance = None
    if inst is not None:
        instance = ('#' if inst.get('Scope') == 'LocalVariable' else '') + \
            '.'.join(_name(c.get('Name'), inst.get('Scope') == 'GlobalVariable' and k == 0)
                     for k, c in enumerate(_kids(inst, 'Component')))
    sized = _card_pins(name_, card) if card is not None else None
    one_operand = name_ in INLINE or instr.endswith(('Coil', 'Contact')) or (spec is not None and spec.form != 'box')
    if (one_operand and rest in (['operand'], ['bit'], ['label'])) \
            or (len(rest) == 1 and instructions.unnamed_pin(instr, rest[0])):
        params = [(None, None, value(rest[0]))]
    elif sized:
        params = with_unlisted([(sd, d, value(x)) for sd, x, d in sized], {x for _, x, _ in sized})
    elif name_ in PINS:
        table = [_pin(s) for s in PINS[name_]]
        known = {x.lower() for x, _, _ in table}
        params = [(sd, d, value(next((r for r in rest if r.lower() == x.lower()), x))) for x, d, sd in table]
        params += [(x, direction(x), value(x)) for x in rest if x.lower() not in known]
    else:                                     # operands in the order of their wires (the declaration order),
        rest.sort(key=lambda x: (x in flow, x if x in flow else ''))          # pins fed by logic after them
        params = [(instructions.sd_pin(instr, x), direction(x), value(x)) for x in rest]
    params += rung_negated()
    return Element(eid, instr, instance, params, templates, expression=_text(p, 'Equation') or None,
                   no_eno=p.get('DisabledENO') == 'true', more=more)


# ---------------------------------------------------------------- interface

def _type(dt):
    """SimaticML data type -> .s7dcl: '"X"' -> '_.X', 'Array[0..3] of "X"' -> 'Array[0..3] of _.X', Struct ->
    STRUCT."""
    return re.sub(r'\bStruct$', 'STRUCT', re.sub(r'"([^"]+)"', r'_.\1', dt or ''))


def _attrs(m, typ, section, safety=False):
    """The member attributes as the pragmas the SD export writes: only where they differ from what TIA shows without
    one (Setpoint: iface.setpoint_default)."""
    al = _kid(m, 'AttributeList')
    a = {x.get('Name'): x.text for x in _kids(al if al is not None else m, 'BooleanAttribute')}
    out = {}
    if a.get('ExternalWritable') == 'false':
        out['S7_Access'] = 'ReadOnly := External'
    if a.get('ExternalAccessible') == 'false':
        out['S7_Visibility'] = 'Hidden := External'
    elif a.get('ExternalVisible') == 'false':
        out['S7_Visibility'] = 'Unlisted := External'
    default = setpoint_default(typ, section, safety)
    if a.get('SetPoint') == ('false' if default else 'true'):
        out['S7_Setpoint'] = 'False' if default else 'True'
    return out


def _comment(m, lang):
    c = _kid(m, 'Comment')
    if c is None or c.get('Informative') == 'true':
        return None
    texts = [(t.get('Lang'), t.text or '') for t in _kids(c, 'MultiLanguageText')]
    return next((t for l, t in texts if l == lang), None) or next((t for _, t in texts if t), None)


def _subelements(m, here, lang, itf):
    """The elements of an array with their own start value or comment: Subelement Path="1" -> 'x[1]', as the SD
    export's start values and initializers name them. Not those of a member inside an array of struct:
    no real export holds one, so their path is not settled."""
    if not re.match(r'Array\s*\[', m.get('Datatype') or ''):
        return
    for sub in _kids(m, 'Subelement'):
        value, comment = _text(sub, 'StartValue') or None, _comment(sub, lang)
        if value is not None or comment:
            itf.start['%s[%s]' % (here, sub.get('Path'))] = (value or '()', comment)


def _overrides(section, path, lang, itf):
    """The members inside a UDT or FB instance of a global DB: the export writes a start value or comment only
    where the instance sets its own; these become start values, as the SD export lists them ('"x".q := ();' with
    its comment). The members of a struct in the UDT are Member elements of the struct."""
    for m in _kids(section, 'Member'):
        here = path + _name(m.get('Name'))
        value, comment = _text(m, 'StartValue') or None, _comment(m, lang)
        if value is not None or comment:
            itf.start[here] = (value or '()', comment)
        _subelements(m, here, lang, itf)
        for sec in _kids(m, 'Sections'):
            for s in _kids(sec, 'Section'):
                _overrides(s, here + '.', lang, itf)
        if m.get('Datatype') == 'Struct':
            _overrides(m, here + '.', lang, itf)


def _members(owner, parent, section, lang, itf, db, path='', safety=False):
    for m in _kids(owner, 'Member'):
        comment = _comment(m, lang)
        typ = _type(m.get('Datatype'))
        value = _text(m, 'StartValue') or None
        name = m.get('Name')
        here = path + _name(name)
        if db:                                            # a global DB: start values, as the SD export lists them
            if value is not None:
                itf.start[here] = (value, None)
            value = None
        _subelements(m, here, lang, itf)                  # also in an FB or UDT, as its initializer
        for sec in _kids(m, 'Sections'):
            for s in _kids(sec, 'Section'):
                _overrides(s, here + '.', lang, itf)
        mem = Member(name, typ, comment or None, value, section, attrs=_attrs(m, typ, section, safety),
                     retain={'Retain': True, 'SetInIDB': s7dcl.SET_IN_IDB}.get(m.get('Remanence'), False))
        parent.children[mem.name] = mem
        _members(m, mem, section, lang, itf, db, here + '.', safety)   # Struct members, not those of a UDT or FB
    return parent


def parse_interface(el, lang, db=False, safety=False):
    itf = Interface()
    secs = None
    for x in el.iter():
        if _local(x.tag) == 'Sections':
            secs = x
            break
    if secs is None:
        return itf
    for sec in _kids(secs, 'Section'):
        name = sec.get('Name')
        if name == 'Return':
            continue
        _members(sec, itf.root, SECTIONS.get(name, name.upper()), lang, itf, db, safety=safety)
    return itf


# ---------------------------------------------------------------- block

def parse_block(src, lang=None):
    lang = lang or s7dcl.LANG
    tag = next(s7dcl._blocks)
    root = ET.fromstring(src.xml.lstrip('\ufeff').encode('utf-8'))
    blk = next((c for c in root if _local(c.tag) in KINDS), None)
    if blk is None:
        raise ValueError('%s: not a SimaticML block export' % src.label)
    kind = KINDS[_local(blk.tag)]
    al = _kid(blk, 'AttributeList')
    name = _text(al, 'Name') or src.name
    plang = _text(al, 'ProgrammingLanguage')
    if _local(blk.tag) == 'SW.Blocks.InstanceDB':
        itf = Interface()                                 # as in the SD export: the FB's interface is not repeated
    else:
        itf = parse_interface(al, lang, db=kind == 'DATA_BLOCK', safety=plang.startswith('F_'))
    decl = '"%s"' % name
    ret = None
    for x in al.iter():
        if _local(x.tag) == 'Section' and x.get('Name') == 'Return':
            ret = next((m.get('Datatype') for m in _kids(x, 'Member')), None)
    if kind == 'FUNCTION':
        decl += ' : %s' % _type(ret or 'Void')
    if _local(blk.tag) == 'SW.Blocks.InstanceDB':
        decl += ' : %s' % _text(al, 'InstanceOfName')     # unquoted: a quote would say a block of the project (render_lad)
    props = {}
    title = _mltext(blk, 'Title', lang)
    comment = _mltext(blk, 'Comment', lang)
    if _text(al, 'AutoNumber') == 'false' or kind == 'ORGANIZATION_BLOCK':
        props['S7_BlockNumber'] = _text(al, 'Number')
    if title:
        props['S7_BlockTitle'] = title
    if comment:
        props['S7_BlockComment'] = comment
    if _text(al, 'SetENOAutomatically') == 'true':
        props['S7_GenerateENOforSCL'] = 'TRUE'
    if _text(al, 'IsIECCheckEnabled') == 'true':
        props['S7_IECCheck'] = 'TRUE'
    if _text(al, 'MemoryLayout'):
        props['S7_Optimized'] = 'TRUE' if _text(al, 'MemoryLayout') == 'Optimized' else 'FALSE'
    if plang and kind != 'DATA_BLOCK':
        props['S7_PreferredLanguage'] = LANGS.get(plang, plang)
    if plang.startswith('F_'):
        props['S7_Safety'] = 'TRUE'
    if kind == 'DATA_BLOCK' and _text(al, 'IsRetainMemResEnabled'):
        props['S7_StandardRetain'] = _text(al, 'IsRetainMemResEnabled').upper()
    if _text(al, 'HeaderVersion'):
        props['S7_Version'] = _text(al, 'HeaderVersion')
    if kind == 'ORGANIZATION_BLOCK' and _text(al, 'SecondaryType'):
        props['Event class'] = _text(al, 'SecondaryType')       # the SD export of an OB has none
    cus = [cu for ol in _kids(blk, 'ObjectList') for cu in _kids(ol, 'SW.Blocks.CompileUnit')]
    nets = [network(cu, k, tag, lang) for k, cu in enumerate(cus, 1)]
    return Block(object_name(src.name, name), src.label, itf, nets, kind, decl, props,
                 auto_number=_text(al, 'Number') if _text(al, 'AutoNumber') == 'true' else None)


def network(cu, k, tag, lang):
    """The k-th network of a block from its CompileUnit; tag: the block's number, which keeps the element ids apart."""
    cal = _kid(cu, 'AttributeList')
    lang_ = _text(cal, 'ProgrammingLanguage')
    lang_ = LANGS.get(lang_, lang_)
    ns = _kid(cal, 'NetworkSource')
    src_, st, sl = ((_kid(ns, x) if ns is not None else None) for x in ('FlgNet', 'StructuredText', 'StatementList'))
    net = Network(k, lang_, _mltext(cu, 'Title', lang), _mltext(cu, 'Comment', lang), '',
                  source=('xml', _plain(cu, lang=lang)), raw=('xml', cu, lang))
    if src_ is not None:
        net.label = label(src_)
        net.rungs = lad_rungs(src_, 'b%dn%d_' % (tag, k), lang_)
        net.body = rungs_text(net.rungs)
        if lang_ != 'LAD':
            net.rungs = None                          # shown as text: its label first, as the SD export
            net.body = ('Label(%s)\n' % net.label if net.label else '') + net.body
    elif st is not None:
        net.body = scl_text(st, lang)
    elif sl is not None:
        net.body = stl_text(sl, lang)
    elif lang_ == 'LAD':
        net.rungs = []                                # an empty network: <NetworkSource />
    else:
        net.body = ''.join(ns.itertext()) if ns is not None else ''
    return net


def _negated_gate(it, heads_rung):
    """(the operand its rung starts at or None, its line) of an AND gate whose rung-in or output is negated, as TIA's
    FBD text writes it: 'RUNG #a', 'NOT A( in2 := #b ) NOT'; None for anything else. No real export shows another
    part, or a rung-in fed by a wire: those, and a named pin, read as the rest ('in2 := NOT #x')."""
    if it.instr != 'A':
        return None
    in1 = next((v for n, _, v in it.params if n == 'in1'), '')
    operand = in1[4:] if in1.startswith('NOT ') else in1
    heads = heads_rung and operand and operand != 'NOT' and wire_of(in1) is None
    negated_in, negated_out = bool(heads and in1.startswith('NOT ')), ('out', '=>', 'NOT') in it.params
    if not negated_in and not negated_out:
        return None
    rest = ['%s %s %s' % p for p in it.params if p != ('out', '=>', 'NOT') and not (heads and p[0] == 'in1')]
    return operand if heads else None, '    %sA( %s )%s' % ('NOT ' if negated_in else '', ', '.join(rest), ' NOT' if negated_out else '')


def rungs_text(rungs):
    """The rungs as the LAD text of a .s7dcl network."""
    out = []
    for r in rungs:
        first = next((x for x in r.items[:1] if not isinstance(x, tuple)), None)
        gate = _negated_gate(first, r.start == 'open') if first is not None else None
        out.append('RUNG %s' % (gate[0] if gate and gate[0] else 'wire#%s' % r.start))
        for it in r.items:
            if isinstance(it, tuple):
                out.append('    wire#%s' % it[1])
                continue
            line = gate if it is first else _negated_gate(it, False)
            if line:
                out.append(line[1])
                continue
            pragmas = []
            tpl = [kv for kv in it.templates.items() if not re.match(r'CASE\d+$', kv[0])]
            if tpl:
                pragmas.append('S7_Templates := "%s"' % ', '.join('%s := %s' % kv for kv in tpl))
            pragmas += ['%s := "%s"' % kv for kv in it.templates.items() if re.match(r'CASE\d+$', kv[0])]
            if it.expression is not None:
                pragmas.append('S7_Expression := "%s"' % it.expression)
            if it.instr == 'Calculate' and not it.no_eno:
                pragmas.append('S7_GenerateENO := TRUE')
            if pragmas:
                out.append('    { %s }' % '; '.join(pragmas))
            head = it.instr if it.instr != 'CALL' else (it.instance or '"%s"' % it.call)
            if it.instr != 'CALL' and it.instance:
                head = '%s.%s' % (it.instance, it.instr)
            params = ['%s %s %s' % p if p[0] else p[2] for p in it.params]     # an unnamed one: the operand
            if len(it.params) == 1 and it.params[0][0] is None:
                out.append('    %s( %s )' % (head, it.params[0][2]))
            elif not it.params:
                out.append('    %s()' % head)
            else:
                out.append('    %s(' % head)
                out += ['        %s,' % s for s in params]
                out.append('    )')
        out.append('END_RUNG' + (' wire#%s' % r.end if r.end else ''))
    return '\n'.join(out)
