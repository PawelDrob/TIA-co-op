"""Slide-in rules. TiaBridge imports a slide-in from <hmi>/slideins, its export folder, after these rules: they read each
document there (docs/agent/openness-hmi.md section 2, Slide-ins and global screens). HMI imports of objects TIA could not
make ended TIA rather than refusing them: connections, an item in the global elements, a screen of a taken number
[PROBE] (2026-11-12, V20 Update 7). A document of another object through the slide-ins' import was not tried.

  slidein.not-slidein  error: a document in the slide-ins folder whose object is no Hmi.Screen.ScreenSlidein.
"""
from ._exportfolder import not_kind

ROOT = 'Hmi.Screen.ScreenSlidein'


def check(repo, ctx):
    for d in repo.slideins:
        if d.obj is None or d.obj.tag != ROOT:
            yield not_kind(d, (ROOT,), 'slidein.not-slidein', 'slideins', 'a slide-in')
