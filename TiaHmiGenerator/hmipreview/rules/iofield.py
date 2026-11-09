"""I/O field rules. Generated documents only.

  iofield.format-pattern  warning: a format pattern with a decimal point on a tag not known to hold a floating point
                          number. TIA's HMI compile refused one such field, whose cause nobody has established, so
                          this warns and refuses nothing: docs/agent/wincc-comfort-openness.md section 4.2. Nothing on
                          a Real or LReal tag is a choice against noise, as those were not tried either.
"""
from ..findings import warning
from ..model import attribute, object_name, objects, parent_map

_FLOATING = ('Real', 'LReal')


def _process_tag(field):
    """The name of the tag on the field's ProcessValue, None when it has none."""
    for p in field.findall('ObjectList/Hmi.Screen.Property'):
        if attribute(p, 'Name') == 'ProcessValue':
            return p.findtext('ObjectList/Hmi.Dynamic.TagConnectionDynamic/LinkList/Tag/Name')
    return None


def _message(pattern, tag, dtype):
    of_type = 'of type %s' % dtype if dtype else 'whose type is not in the tag tables of this repo'
    return ("FormatPattern %s on tag '%s' %s: the HMI compile may refuse it. Seen once, 99.99 on an Int tag with "
            "ShiftDecimalPoint 0: \"The format pattern of I/O field ... is invalid\", while 9999 compiled. Why is not "
            "known, and no other pattern or tag type was tried, so this is no refusal." % (pattern, tag, of_type))


def check(repo, ctx):
    for d in repo.generated:
        parents = parent_map(d.tree)
        for e in objects(d.tree):
            if e.tag != 'Hmi.Screen.IOField' or attribute(e, 'DataFormat', 'Decimal') != 'Decimal':
                continue
            pattern, tag = attribute(e, 'FormatPattern', ''), _process_tag(e)
            dtype = repo.tag_types.get(tag)
            if tag and '.' in pattern and dtype not in _FLOATING:
                yield warning(d.path, object_name(e, parents), 'iofield.format-pattern', _message(pattern, tag, dtype))
