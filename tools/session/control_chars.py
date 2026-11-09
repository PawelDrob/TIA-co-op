"""Finds control characters in tickets and notes. Only reports: it changes no file.

A Python string escape turns a Windows path into control characters: \\f in C:\\docs\\foo becomes a form feed, \\07 in issues\\07-x a
bell. A finding names the file and line and, when it can tell, the path it should be: a form that exists on disk, the only form
there is, or in a word that looks like a path a letter escape (\\f, \\b ...) followed by more letters, for a tab with a folder before
it too. Otherwise it lists the forms a path could have had (could be), or nothing where there is no mark of a path. A real line
break (from \\n) leaves no mark to find.
A tab counts only inside a path, a carriage return only away from a line's end.
"""
import itertools
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

LETTERS = {'\x07': 'a', '\x08': 'b', '\x09': 't', '\x0b': 'v', '\x0c': 'f', '\x0d': 'r'}
CONTROL = re.compile('[\x00-\x09\x0b-\x1f\x7f-\x9f]')
WORD_END = re.compile('[ \u00a0`"\'|()<>\\[\\]]')    # not \\s: that holds control characters
DRIVE = re.compile(r'^[A-Za-z]:')
EXTENSION = re.compile(r'\.[A-Za-z0-9]{1,8}(:\d+)?$')
TRAILING = '.,;:!?'
MAX_FORMS = 36
FORMS_SHOWN = 6


@dataclass
class Finding:
    line: int
    column: int
    char: str
    should_be: str = ''                             # the path, when it can tell
    could_be: list = field(default_factory=list)    # the forms it could be, when it cannot


def forms(char, following):
    """What was written to give this character, the letter first. An octal escape takes up to three digits, so before another
    octal digit only the long form leaves that digit outside it."""
    number = '%o' % ord(char)
    numbers = [number.zfill(width) for width in range(len(number), 4)]
    if following and following in '01234567':
        numbers = numbers[-1:]
    letter = LETTERS.get(char)
    return (['\\' + letter] if letter else []) + ['\\' + n for n in numbers]


def word_at(line, column):
    """The word around the character at this index: (start, end) of the run with no space, quote or bracket in it."""
    start = column
    while start > 0 and not WORD_END.match(line[start - 1]):
        start -= 1
    end = column + 1
    while end < len(line) and not WORD_END.match(line[end]):
        end += 1
    while end > column + 1 and line[end - 1] in TRAILING:
        end -= 1
    return start, end


def looks_like_a_path(word):
    if '://' in word:
        return False
    return bool(re.search(r'[\\/]', word) or DRIVE.match(word) or EXTENSION.search(word))


def is_path_tab(word, offset):
    before, after = word[:offset], word[offset + 1:]
    if not before or not after or not (after[0].isalnum() or after[0] in '-_'):
        return False
    if before.endswith(':') and not re.fullmatch(r'[A-Za-z]:', before):    # Status:<tab>done
        return False
    return looks_like_a_path(word)


def tab_inside_a_path(word, offset):
    """Whether what stands before a tab is a folder. A tab beside a path looks the same: M<tab>tools/x.py, tools/x.py<tab>found."""
    before = word[:offset]
    return bool(re.search(r'[\\/]', before) or DRIVE.match(before)) and not EXTENSION.search(before)


def letter_then_letters(word):
    """Whether each control character in the word has a letter escape and a letter after it, and each tab a folder before it."""
    return all(c in LETTERS and word[i + 1:i + 2].isalpha() and (c != '\t' or tab_inside_a_path(word, i))
               for i, c in enumerate(word) if CONTROL.match(c))


def rebuilt(word, exists):
    """(should_be, could_be) of a word holding control characters."""
    slots = [forms(c, word[i + 1:i + 2]) if CONTROL.match(c) else [c] for i, c in enumerate(word)]
    candidates = [''.join(p) for p in itertools.islice(itertools.product(*slots), MAX_FORMS)]
    for candidate in candidates:
        if exists(candidate):
            return candidate, []
    if not looks_like_a_path(word):
        return '', []
    if len(candidates) == 1 or letter_then_letters(word):
        return candidates[0], []
    return '', candidates


def find(text, exists=lambda path: False):
    """The findings in a text. exists(path) answers whether a candidate path is on disk."""
    found = []
    for number, line in enumerate(text.split('\n'), 1):
        if line.endswith('\r'):
            line = line[:-1]
        for match in CONTROL.finditer(line):
            start, end = word_at(line, match.start())
            word = line[start:end]
            offset = match.start() - start
            if match.group() == '\t' and not is_path_tab(word, offset):
                continue
            finding = Finding(number, match.start() + 1, match.group())
            if offset > 0 and offset < len(word) - 1:
                finding.should_be, finding.could_be = rebuilt(word, exists)
            found.append(finding)
    return found


def exists_from(*folders):
    """exists(path) for a path that is absolute or lies under one of these folders."""
    def exists(path):
        try:
            return any(os.path.exists(os.path.join(folder, path)) for folder in folders)
        except (ValueError, OSError):
            return False
    return exists


def scan(root, paths=None):
    """(file, finding) for each of the named files, by default every .md under root. Reads only."""
    root = Path(root)
    found = []
    for path in sorted(root.rglob('*.md')) if paths is None else [Path(p) for p in paths]:
        try:
            text = path.read_bytes().decode('utf-8', 'replace')
        except OSError:
            continue
        found += [(path, f) for f in find(text, exists_from(path.parent, path.parent.parent, root, root.parent))]
    return found


def describe(path, finding):
    """One line of a report."""
    where = f'{path}:{finding.line}:{finding.column}: control character U+{ord(finding.char):04X}'
    if finding.should_be:
        return f'{where}, should be {finding.should_be}'
    if finding.could_be:
        return f'{where}, could be ' + ' or '.join(finding.could_be[:FORMS_SHOWN])
    return where
