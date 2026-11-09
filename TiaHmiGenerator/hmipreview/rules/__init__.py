"""Rule modules. Every module in this package that defines check(repo, ctx) -> iterable of Finding is a rule
group and runs in module-name order. A new rule group is a new file here; nothing else is edited.

repo is a model.Repo, ctx a validator.Context (for_import, override). Rule ids are '<group>.<rule>'.
"""
import importlib
import pkgutil


def checks():
    found = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith('_'):
            continue
        mod = importlib.import_module('%s.%s' % (__name__, info.name))
        check = getattr(mod, 'check', None)
        if callable(check):
            found.append(check)
    return found
