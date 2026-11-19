"""Slide-in and global screen rules. TiaBridge imports a slide-in from <hmi>/slideins and the global elements and the
screen overview from <hmi>/global, their export folders, after these rules: they read each document there
(docs/agent/openness-v20.md section 2, Slide-ins and global screens). HMI imports of objects TIA could not make ended TIA
rather than refusing them: connections, an item in the global elements, a screen of a taken number [PROBE] (2026-11-12,
V20 Update 7). A document of another object through these imports was not tried.

  slidein.not-slidein  error: a document in the slide-ins folder whose object is no Hmi.Screen.ScreenSlidein.
  global.not-global    error: a document in the global folder whose object is neither Hmi.Screen.ScreenGlobalElements
                       nor Hmi.Screen.ScreenOverview.
  global.screen-item   error: a screen item in the global elements. TIA ended on the import of a text field there: "The
                       HmiScreenItemData object is not allowed in screen Global screen." [PROBE] (2026-11-12). Other
                       items were not tried; the alarm window and alarm indicator, which the global elements hold in
                       TIA, count as invisible to Openness (docs/agent/wincc-comfort-openness.md 7.1).
"""
from ..findings import error

SLIDEIN_ROOT = 'Hmi.Screen.ScreenSlidein'
# the global screens' objects, with the name TiaBridge gives each (its list and import name them so)
GLOBAL_ROOTS = {'Hmi.Screen.ScreenGlobalElements': 'ScreenGlobalElements', 'Hmi.Screen.ScreenOverview': 'ScreenOverview'}
GLOBAL_ELEMENTS = 'Hmi.Screen.ScreenGlobalElements'


def _not_kind(d, roots, rule, folder, what):
    tag = d.obj.tag if d.obj is not None else 'no object'
    return error(d.path, None, rule,
                 'The %s folder holds %s, not %s: TiaBridge imports it as %s, which was not tried with another '
                 'object, and HMI imports of objects TIA could not make ended its process. Move it to the folder of its '
                 'kind.' % (folder, tag, ' or '.join(roots), what))


def check(repo, ctx):
    for d in repo.slideins:
        if d.obj is None or d.obj.tag != SLIDEIN_ROOT:
            yield _not_kind(d, (SLIDEIN_ROOT,), 'slidein.not-slidein', 'slideins', 'a slide-in')
    for d in repo.screen_globals:
        if d.obj is None or d.obj.tag not in GLOBAL_ROOTS:
            yield _not_kind(d, tuple(GLOBAL_ROOTS), 'global.not-global', 'global', 'global elements or the screen overview')
            continue
        if d.obj.tag != GLOBAL_ELEMENTS:
            continue
        for it in d.obj.iter():
            if it.get('CompositionName') == 'ScreenItems':
                name = it.findtext('AttributeList/ObjectName') or it.tag
                yield error(d.path, name, 'global.screen-item',
                            'The global elements hold the screen item %s (%s). TIA ended its process on the import '
                            'of a text field there ("The HmiScreenItemData object is not allowed in screen Global '
                            'screen."), and no item was imported there: remove it, and change the alarm window and '
                            'alarm indicator of the global elements in TIA.' % (name, it.tag))
