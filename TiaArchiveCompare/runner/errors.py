"""Errors in plain words for the window; the Siemens text (type, message, details, inner chain) for the log.

`err` is TiaBridge's error object (ConvertTo-BridgeError: type, message, details, inner, tiaDisconnected), a refusal
text, or None. The patterns follow TiaBridge's Get-BackgroundFailureHint (Tools\\Background.ps1).
"""
import re

_PLAIN = [
    (r'MissingProducts|option package|Optionspaket|support package|\bHSP\b',
     'TIA Portal on this PC lacks software the project uses (an option package or HSP; the log names it). '
     'Install it, or compare on a PC that has it.'),
    (r'LicenseNotFound|licen[cs]e|Lizenz',
     'No valid licence for TIA Portal or a package the project uses (Automation License Manager).'),
    (r'already open|already in use|is locked|being used by another|bereits ge.ffnet|gesperrt|wird verwendet'
     r'|and locked there',
     'The project is open in TIA Portal. Close it there, or pick an archive of it.'),
    (r'UMAC|\bUMC\b|user management|Benutzerverwaltung|project is protected|protected project|project protection'
     r'|Projektschutz',
     'The project is protected with user management (UMC); the project user and password are needed.'),
    (r"Siemens TIA Openness|EngineeringSecurity|Openness access",
     "Your Windows user may not use TIA Openness. Ask IT to add you to the group 'Siemens TIA Openness', "
     "then sign out and in again."),
    (r'TIA Portal V2[1-9]|newer version|neueren Version',
     'The project is from a newer TIA Portal than this PC has.'),
    (r'ProcessExited|NonRecoverable|ObjectDisposed|does not answer any more',
     'TIA Portal ended unexpectedly or stopped answering.'),
    # TIA also says: The specified path' C:\...' (159 character) is too long. A maximum of 143 characters is allowed.
    (r'path\W.{0,400}too long|PathTooLong|Pfad\W.{0,400}zu lang',
     "A file path in TIA's copy of the project is too long for Windows or TIA, which allows 143 characters (the log "
     "names it): the project holds a very long file or folder name, or the Windows user name or the work folder "
     "(--data-root) is long."),
    (r'Unable to retrieve the project|Retrieve failed',
     'TIA could not unpack the archive (the log has its text). The file may be damaged or incomplete: copy it '
     'again, or archive the project again.'),
]


def _text(err):
    if err is None:
        return ''
    if isinstance(err, str):
        return err
    parts = [str(err.get('type', '')), str(err.get('message', ''))]
    parts += [str(d) for d in err.get('details') or ()]
    for i in err.get('inner') or ():
        parts += [str(i.get('type', '')), str(i.get('message', ''))]
    return '\n'.join(parts)


def is_protected(err):
    return bool(re.search(_PLAIN[3][0], _text(err), re.IGNORECASE))


def plain(err, fallback='TIA Portal reported an error (the log has its text).'):
    """One sentence for the user."""
    if isinstance(err, dict) and err.get('tiaDisconnected'):
        return _PLAIN[6][1]
    text = _text(err)
    for pattern, words in _PLAIN:
        if re.search(pattern, text, re.IGNORECASE):
            return words
    return fallback


def siemens(err):
    """The error as TIA gave it, for the log: type: message, then details and the inner chain."""
    if err is None:
        return ''
    if isinstance(err, str):
        return err
    s = '%s: %s' % (err.get('type', '?'), err.get('message', ''))
    for d in err.get('details') or ():
        s += ' | detail: %s' % d
    for i in err.get('inner') or ():
        s += ' | inner %s: %s' % (i.get('type', '?'), i.get('message', ''))
    return s


_NOT_EXPORTED = [
    (r'Inconsistent',
     'not compiled (inconsistent): compile the project and archive it again, or tick "Compile"'),
    (r'know-how', 'know-how protected: TIA does not export its code'),
    (r'is not permitted|F-system|F_SYSTEM|fail-safe system', 'F-system block: TIA does not export it'),
]


def why_not_exported(err):
    """Why an object did not export, in plain words (the Siemens message kept in brackets when unknown)."""
    text = _text(err)
    for pattern, words in _NOT_EXPORTED:
        if re.search(pattern, text, re.IGNORECASE):
            return words
    msg = err.get('message') if isinstance(err, dict) else text
    return 'TIA did not export it (%s)' % (msg or 'no reason given').strip()
