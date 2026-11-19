"""Shared by the rule groups of the export folders TiaBridge imports from (slidein, globalscreen): no rule group itself,
as rules.checks() leaves out a module whose name starts with _.
"""
from ..findings import error


def not_kind(d, roots, rule, folder, what):
    """The error on document d of an export folder whose object is none of roots."""
    tag = d.obj.tag if d.obj is not None else 'no object'
    return error(d.path, None, rule,
                 'The %s folder holds %s, not %s: TiaBridge imports it as %s, which was not tried with another '
                 'object, and HMI imports of objects TIA could not make ended its process. Move it to the folder of its '
                 'kind.' % (folder, tag, ' or '.join(roots), what))
