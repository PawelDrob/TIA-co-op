"""Global screen rules. TiaBridge imports the global elements and the screen overview from <hmi>/global, their export
folder, after these rules: they read each document there (docs/agent/openness-hmi.md section 2, Slide-ins and global
screens). HMI imports of objects TIA could not make ended TIA rather than refusing them: connections, an item in the
global elements, a screen of a taken number [PROBE] (2026-11-12, V20 Update 7). A document of another object through
these imports was not tried.

  globalscreen.not-global    error: a document in the global folder whose object is neither
                             Hmi.Screen.ScreenGlobalElements nor Hmi.Screen.ScreenOverview.
  globalscreen.screen-item   error: a screen item in the global elements. TIA ended on the import of a text field there:
                             "The HmiScreenItemData object is not allowed in screen Global screen." [PROBE] (2026-11-12).
                             Other items were not tried, so every one is refused. The global elements can hold an alarm
                             window and an alarm indicator in TIA (docs/agent/wincc-screen-objects.md,
                             ScreenGlobalElements), which count as invisible to Openness
                             (docs/agent/wincc-comfort-openness.md 7.1).
"""
from ..findings import error
from ._exportfolder import not_kind

# the global screens' objects, with the name TiaBridge gives each (its list and import name them so)
ROOTS = {'Hmi.Screen.ScreenGlobalElements': 'ScreenGlobalElements', 'Hmi.Screen.ScreenOverview': 'ScreenOverview'}
GLOBAL_ELEMENTS = 'Hmi.Screen.ScreenGlobalElements'


def check(repo, ctx):
    for d in repo.screen_globals:
        if d.obj is None or d.obj.tag not in ROOTS:
            yield not_kind(d, tuple(ROOTS), 'globalscreen.not-global', 'global',
                           'global elements or the screen overview')
            continue
        if d.obj.tag != GLOBAL_ELEMENTS:
            continue
        for it in d.obj.iter():
            if it.get('CompositionName') == 'ScreenItems':
                name = it.findtext('AttributeList/ObjectName') or it.tag
                yield error(d.path, name, 'globalscreen.screen-item',
                            'The global elements hold the screen item %s (%s). TIA ended its process on the import '
                            'of a text field there ("The HmiScreenItemData object is not allowed in screen Global '
                            'screen."); other items were not tried, so none goes in: remove it, and change the alarm '
                            'window and alarm indicator of the global elements in TIA.' % (name, it.tag))
