"""An object's name: as its document declares it, and the file-safe form its file is named by."""
import re


def decl_name(decl):
    """The block's name from the rest of its declaration line ('"Filler"', 'FillerDb : Filler')."""
    # quoted: it may hold a colon. "" for a quote is what the bridge's reader assumes: no real export holds one
    m = re.match(r'\s*(?:"((?:[^"]|"")*)"|([^":]*))', decl or '')
    return m.group(1).replace('""', '"').strip() if m.group(1) is not None else m.group(2).strip()


def decl_type(decl):
    """What the rest of a declaration line says the block is of, as written ('"FillerDb" : "Filler"': '"Filler"', a
    function's return type); '' when it says nothing. A colon in a quoted name is the name's."""
    m = re.match(r'\s*(?:"(?:[^"]|"")*"|[^":]*)\s*:(.*)', decl or '', re.S)
    return m.group(1).strip() if m else ''


def file_safe(name):
    """A name as the file of its export is named: TiaBridge's ConvertTo-SafeFileName, held to it by a test
    (test_export_roots.BridgeFolders). No name stays none, where the bridge writes _: no object has none."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1F]', '_', name)
    s = re.sub('[. \u00a0\u0085]+\\Z', '_', s)
    return re.sub('^(con|prn|aux|nul|com[0-9\u00b9\u00b2\u00b3]|lpt[0-9\u00b9\u00b2\u00b3]|conin\\$|conout\\$)(\\.|\\Z)',
                  r'\1_\2', s, flags=re.I)


def object_name(file_name, declared):
    """What TIA calls the object of a file: the name its document declares, when the file is named by that name. A
    library type's file is named by the type and its document may declare the type's instance, of another name: the
    file's name then, as nothing in the export holds the type's own."""
    return declared if declared and file_safe(declared).lower() == file_name.lower() else file_name
