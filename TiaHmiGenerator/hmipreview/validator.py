"""validate(repo) -> findings. Runs every rule module under hmipreview/rules on the repo model."""
from dataclasses import dataclass

from . import model, rules


@dataclass(frozen=True)
class Context:
    for_import: bool = False      # import-only rules (open planned item is an error, staleness)
    override: bool = False        # import with override: staleness passes


def validate(repo_path, for_import=False, override=False, overlay=None, device=None):
    """Findings for one HMI device (model.select_device) of the project repo at repo_path, as it is on disk, or with
    the files of overlay ({repo-relative path: bytes}, see model.load) in place of the disk. Sorted by document,
    object, rule."""
    return check_repo(model.load(repo_path, overlay, device), for_import, override)


def check_repo(repo, for_import=False, override=False):
    """Findings for a loaded model.Repo (the preview server validates the repo it has cached)."""
    ctx = Context(for_import, override)
    found = list(repo.load_findings)
    for check in rules.checks():
        found.extend(check(repo, ctx))
    return sorted(found, key=lambda f: (f.document, f.object or '', f.rule, f.message))
