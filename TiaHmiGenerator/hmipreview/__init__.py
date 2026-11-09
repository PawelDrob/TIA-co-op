"""hmipreview - validator (and later preview server) for generated WinCC Comfort SimaticML documents.

Entry point: validate(repo_path, for_import=False, override=False) -> list[Finding].
link_states(repo, doc) -> list[Link]: the links of one document with exists / planned / unknown (inspect panel).
"""
from .findings import ERROR, WARNING, Finding
from .links import Link, link_states
from .validator import validate

__all__ = ['validate', 'Finding', 'ERROR', 'WARNING', 'link_states', 'Link']
