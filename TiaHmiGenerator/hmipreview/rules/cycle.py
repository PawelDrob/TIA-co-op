"""HMI cycle rules. TiaBridge imports a cycle from its export folder, <hmi>/cycles, after these rules: they read each
document there (docs/agent/openness-v20.md section 2, Cycles).

  cycle.not-full    error with for_import, else a warning: a cycle document that is no full export (DocumentInfo/
                    ExportSetting not 'WithDefaults, WithReadOnly'), or that lacks StartAtStartingPoint. A minimal
                    export leaves StartAtStartingPoint out when it is true, and TIA's import of such a file set it
                    false, on all 19 cycles of a project, its system cycles too; a full export went back unchanged
                    [PROBE] (2026-11-12, V20 Update 7). An older repo holds minimal ones: export them again.
  cycle.not-cycle   error: a document in the cycles folder whose object is no Hmi.Cycle.Cycle. Where TIA cannot make
                    an HMI object from a file, its import ended TIA rather than refusing it [PROBE] (2026-11-12).
"""
from ..findings import error, warning

ROOT = 'Hmi.Cycle.Cycle'


def check(repo, ctx):
    for d in repo.cycles:
        if d.obj is None or d.obj.tag != ROOT:
            yield error(d.path, d.name, 'cycle.not-cycle',
                        'The cycles folder holds %s, not a cycle (%s): TiaBridge imports it as a cycle, and TIA ended '
                        'its process on an HMI document it could not make. Move it to the folder of its kind.'
                        % (d.obj.tag if d.obj is not None else 'no object', ROOT))
            continue
        if not d.full:
            setting = "'%s'" % d.export_setting if d.export_setting is not None else 'not recorded'
            what = "ExportSetting is %s, not 'WithDefaults, WithReadOnly'" % setting
        elif d.attr('StartAtStartingPoint') is None:
            what = 'the cycle has no StartAtStartingPoint'
        else:
            continue
        make = error if ctx.for_import else warning
        yield make(d.path, d.name, 'cycle.not-full',
                   '%s. A minimal export leaves out StartAtStartingPoint when it is true, and TIA imports a file '
                   'without it as false: every cycle of a project changed so. Export the cycles again (TiaBridge '
                   'export or full_export, kind hmi_cycle, which writes them full), then edit and import that file. '
                   'Once only: the next change report shows those cycles changed, by export differences alone, '
                   'folded.' % what)
