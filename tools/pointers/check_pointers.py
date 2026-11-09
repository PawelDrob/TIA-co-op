"""Fails when a skill, a contributor document or a README points at a file that is not in the repo, or a skill's frontmatter does not parse.

    python -X utf8 tools/pointers/check_pointers.py

Reads the skills under .claude/skills/, AGENTS.md, CODING_STANDARDS.md, CONTRIBUTING.md and the README.md of the repo
or of a top-level folder, whatever the folder's name; a README deeper down is not read. A pointer is a relative Markdown
link (inline or reference style), a word in backticks or a fence that starts with ./ or ../ (read from the document) or
with a tracked top-level folder, or a Markdown file named alone (beside the document or at the root). "In the repo" means
in git's index, so a commit that deletes a file fails here though a document still names it. A path git ignores holds: it
is a local file by design. Placeholders (<name>), globs, web addresses, absolute paths, folders git does not track and
words that leave the repo are left alone.

A skill whose frontmatter does not parse loses all of it with no message, disable-model-invocation too, so each SKILL.md
must parse, with its folder as its name and a description, the flag written true or false, and no key that looks like a
misspelt known one.
"""
import difflib
import os
import posixpath
import re
import subprocess
import sys

import yaml

DOCUMENTS = re.compile(r'^(\.claude/skills/.*\.md|AGENTS\.md|CODING_STANDARDS\.md|CONTRIBUTING\.md|([^/]+/)?README\.md)$')
SKILL = re.compile(r'^\.claude/skills/([^/]+)/SKILL\.md$')
KNOWN_KEYS = ('name', 'description', 'disable-model-invocation', 'user-invocable', 'argument-hint', 'allowed-tools', 'model', 'context', 'agent', 'hooks')
LINK = re.compile(r'\]\(([^)\s]+)(?:\s[^)]*)?\)|^\s*\[[^\]]+\]:\s*(\S+)')
INLINE_CODE = re.compile(r'`([^`\n]+)`')
SKIP_LINK = re.compile(r'^([a-zA-Z][a-zA-Z0-9+.-]*:|#)')
GIT_CONTEXT = ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE', 'GIT_PREFIX', 'GIT_COMMON_DIR')    # a parent's: git prefers them to the folder


def bad_frontmatter(documents):
    """(document, line, message) for each SKILL.md in {document path: text} whose frontmatter a skill cannot run on."""
    found = []
    for path, text in documents.items():
        skill = SKILL.match(path)
        if skill:
            found += [(path, line, message) for line, message in frontmatter_faults(text, skill.group(1))]
    return found


def frontmatter_faults(text, folder):
    lines = [line.strip() for line in text.splitlines()]
    if not lines or lines[0] != '---' or '---' not in lines[1:]:
        return [(1, 'no frontmatter')]
    head = '\n'.join(text.splitlines()[1:lines.index('---', 1)])
    try:
        meta = yaml.safe_load(head)
    except yaml.YAMLError as error:
        mark = getattr(error, 'problem_mark', None)
        return [(mark.line + 2 if mark else 1, ' '.join(str(getattr(error, 'problem', error)).split()))]
    if not isinstance(meta, dict):
        return [(1, 'frontmatter is not a mapping')]
    faults = []
    if meta.get('name') != folder:
        faults.append((1, f'name {meta.get("name")}, in folder {folder}'))
    if not meta.get('description'):
        faults.append((1, 'no description'))
    flag = re.search(r'^disable-model-invocation:\s*([^\s#]*)', head, re.M)    # YAML reads yes and on as true; the text is what counts
    if flag and flag.group(1) not in ('true', 'false'):
        faults.append((1, 'disable-model-invocation is not true or false'))
    for key in meta:
        near = difflib.get_close_matches(str(key), KNOWN_KEYS, n=1, cutoff=0.8)
        if near and key not in KNOWN_KEYS:
            faults.append((1, f'{key}: did you mean {near[0]}?'))
    return faults


def dangling(documents, tracked, ignored=lambda path: False):
    """(document, line, pointer) for each pointer in {document path: text} that names nothing in the tracked paths, unless
    ignored(path) says git ignores it."""
    def holds(path):
        path = posixpath.normpath(path)
        return names_something(path, tracked) or ignored(path)

    found = []
    for path, text in documents.items():
        fenced = False
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith('```'):
                fenced = not fenced
                continue
            code = [line] if fenced else INLINE_CODE.findall(line)
            words = [word.strip('"\'') for part in code for word in part.split()]
            links = [inline or reference for inline, reference in LINK.findall(line)]
            bad = [link for link in links if not link_holds(link, path, holds)]
            bad += [word for word in words if not word_holds(word, path, tracked, holds)]
            found += [(path, number, pointer) for pointer in bad]
    return found


def link_holds(target, document, holds):
    if SKIP_LINK.match(target):
        return True
    return holds(posixpath.join(posixpath.dirname(document), target.split('#')[0]))


def word_holds(word, document, tracked, holds):
    if re.search(r'[<>*$~]|^[a-zA-Z]:', word) or word.startswith(('-', '/')):
        return True
    path = word.replace('\\', '/')
    beside = posixpath.join(posixpath.dirname(document), path)
    if path.startswith(('./', '../')):
        return posixpath.normpath(beside).startswith('../') or holds(beside)
    if '/' not in path:
        return not path.endswith('.md') or holds(path) or holds(beside)
    return path.split('/')[0] not in {t.split('/')[0] for t in tracked} or holds(path)


def names_something(path, tracked):
    return path in tracked or any(t.startswith(path + '/') for t in tracked)


def git_env():
    return {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}


def main():
    root = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True, env=git_env()).stdout.strip()
    out = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True, encoding='utf-8', check=True, env=git_env()).stdout
    tracked = set(out.splitlines())
    documents = {}
    for path in sorted(p for p in tracked if DOCUMENTS.match(p)):
        with open(posixpath.join(root, path), encoding='utf-8') as f:
            documents[path] = f.read()
    faults = [(path, line, f'names {pointer}, which is not in the repo')
              for path, line, pointer in dangling(documents, tracked, lambda path: is_ignored(root, path))]
    faults += bad_frontmatter(documents)
    for path, line, message in faults:
        print(f'{path}:{line}: {message}')
    return 1 if faults else 0


def is_ignored(root, path):
    return subprocess.run(['git', '-C', root, 'check-ignore', '-q', path], capture_output=True, env=git_env()).returncode == 0


if __name__ == '__main__':
    sys.exit(main())
