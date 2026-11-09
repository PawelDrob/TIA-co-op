"""The preview's drawing code for a self-contained page: simaticml.js and render.js (ES modules in static/) as one
classic script, so that a report draws screens with the preview's own code and the two cannot drift apart.

  bundle() -> str   defines const X (simaticml.js) and const R (render.js), each the object of its exports
"""
import os
import re

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
MODULES = (('X', 'simaticml.js'), ('R', 'render.js'))     # render.js imports simaticml.js as X


def module(path, name):
    """An ES module as a classic script: const name = (() => {...; return {exports};})(). Its imports are dropped:
    the modules come in dependency order and bind the names the imports would."""
    with open(path, encoding='utf-8') as f:
        src = f.read()
    exports = re.findall(r'^export (?:async )?(?:function\*?|const|let|class) (\w+)', src, flags=re.M)
    src = re.sub(r'^import .*$', '', src, flags=re.M)
    src = re.sub(r"^'use strict';$", '', src, flags=re.M)
    src = re.sub(r'^export ', '', src, flags=re.M)
    return 'const %s = (() => {\n%s\nreturn {%s};\n})();' % (name, src, ', '.join(exports))


def bundle():
    return "'use strict';\n" + '\n'.join(module(os.path.join(STATIC, f), n) for n, f in MODULES) + '\n'
