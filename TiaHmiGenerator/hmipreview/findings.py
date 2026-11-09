"""Finding: one result of the validator."""
from dataclasses import asdict, dataclass

ERROR = 'error'
WARNING = 'warning'


@dataclass(frozen=True)
class Finding:
    severity: str            # 'error' | 'warning'
    document: str            # repo-relative path with forward slashes ('' for repo-level findings)
    object: str | None       # ObjectName of the screen item, or None for the document / repo
    rule: str                # stable id, '<group>.<rule>' (e.g. 'vocabulary.value')
    message: str
    # What the finding is about besides its object, for the preview's findings page (sentences, folding); () when
    # nothing. Per rule: geometry.overlap, geometry.hidden: the ObjectNames of the other objects of the document;
    # geometry.template-overlap: the template's name, then the ObjectNames of its objects; geometry.outside: the
    # object's x, y, width, height, then the area's kind, width, height; links.planned, links.unknown: (kind, name,
    # note) of the link target, note '' when none.
    about: tuple = ()

    def to_dict(self):
        d = asdict(self)
        d['about'] = list(self.about)
        return d

    def __str__(self):
        return '%-7s %s %s [%s] %s' % (self.severity, self.document or '-', self.object or '-', self.rule,
                                       self.message)


def error(document, obj, rule, message, about=()):
    return Finding(ERROR, document, obj, rule, message, tuple(about))


def warning(document, obj, rule, message, about=()):
    return Finding(WARNING, document, obj, rule, message, tuple(about))
