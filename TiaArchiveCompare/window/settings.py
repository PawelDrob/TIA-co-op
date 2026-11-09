"""What the window remembers between starts: the last folders of the two pickers.
File: %LOCALAPPDATA%\\TIA Compare\\window.json (the tool's folder)."""
import json
import ntpath
import os
from dataclasses import dataclass
from typing import Optional

from TiaArchiveCompare.window.model import clean_path


def default_path():
    return os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'TIA Compare', 'window.json')


@dataclass
class Settings:
    before_folder: Optional[str] = None
    after_folder: Optional[str] = None

    @staticmethod
    def load(path):
        """A missing or broken file gives empty settings: remembering folders is a convenience."""
        try:
            with open(path, encoding='utf-8-sig') as f:
                d = json.load(f)
        except (OSError, ValueError):
            return Settings()
        if not isinstance(d, dict):
            return Settings()
        return Settings(*(v if isinstance(v, str) else None for v in (d.get('beforeFolder'), d.get('afterFolder'))))

    def save(self, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'beforeFolder': self.before_folder, 'afterFolder': self.after_folder}, f, ensure_ascii=False)
        except OSError:
            pass


def folder_of(path, is_folder):
    """The folder a picker opens next time: the folder itself for a picked folder, else the file's folder."""
    p = clean_path(path)
    if not p:
        return None
    return p.rstrip('\\') if is_folder else ntpath.dirname(p)
