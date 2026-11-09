"""Resolution rules (hmi/panel.json, the declared panel).

The resolution is the declared target panel (hmi/[<device>/]panel.json), else the hardware (the TypeIdentifier
of the selected HMI device in tiabridge.json).

  resolution.unknown-device   neither a declared panel nor a hardware TypeIdentifier in the table (error: nothing
                              can be placed or drawn without the panel size); the message names the panel command
  resolution.ambiguous-device no HMI device chosen: hmi/ holds several device folders and neither --device /
                              device= nor hmiDevice names one, a device named has no folder, or (one-device
                              layout) hmiTypeIdentifier is a map of several devices and hmiDevice names none
                              (error; nothing of a device is read without a device folder)
  resolution.mismatch         the declared panel and the hardware differ in size or orientation (error on
                              hmi/panel.json, naming both): declare the panel again or fix the device in TIA
  resolution.screen-size      a screen or template whose Width/Height differ from the resolution:
                              warning on a TIA export (the table or the identifier is wrong), error on a generated
                              document (the generator must write the device resolution). Pop-ups carry their own
                              size; a document without Width/Height is not checked here (document.incomplete,
                              document.not-full report it).
"""
from ..findings import error, warning
from ..model import GENERATED
from ..resolution import PANEL_COMMAND, parse_type_identifier


def check(repo, ctx):
    if repo.device_problem:
        yield error('tiabridge.json', None, 'resolution.ambiguous-device', repo.device_problem)
        if repo.panel is None:
            return
    res = repo.resolution
    if res is None:
        tid = repo.type_identifier
        if not tid:
            what = "no hmiTypeIdentifier for HMI device '%s'" % repo.device if repo.device else 'no hmiTypeIdentifier'
            msg = ('tiabridge.json has %s (run connect) and %s declares no panel; declare the target panel: %s'
                   % (what, repo.panel_file, PANEL_COMMAND))
        else:
            parsed = parse_type_identifier(tid)
            msg = ("HMI device '%s' (order number %s) is not in the Comfort Panel resolution table and %s declares "
                   "no panel; declare the target panel: %s"
                   % (tid, parsed[0] if parsed else 'none', repo.panel_file, PANEL_COMMAND))
        yield error('tiabridge.json', None, 'resolution.unknown-device', msg)
        return
    if repo.panel is not None and repo.hardware is not None and not repo.panel.same_screen(repo.hardware):
        yield error(repo.panel_file, None, 'resolution.mismatch',
                    'The declared panel %s differs from the HMI device in TIA, %s. Declare the panel again (%s) '
                    'or fix the device in TIA.' % (repo.panel.describe(), repo.hardware.describe(), PANEL_COMMAND))
    for d in repo.exports + repo.generated:
        if d.kind not in ('screen', 'template'):
            continue
        w, h = d.attr('Width'), d.attr('Height')
        if w is None and h is None:
            continue
        if (w, h) != (str(res.width), str(res.height)):
            make = error if d.origin == GENERATED else warning
            yield make(d.path, None, 'resolution.screen-size',
                       '%s %s is %sx%s, the panel %s.' % (d.kind.capitalize(), d.name, w, h, res.describe()))
