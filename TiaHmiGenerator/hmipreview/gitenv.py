"""The environment and the flags of a git call in a repo named by path. A parent (a hook, another git-aware tool) can
leave GIT_CONTEXT in the environment, and git prefers it to -C: it would read and write the parent's repo. NO_WINDOW:
the server runs with no console, and git would open a window of its own."""
import os
import subprocess

GIT_CONTEXT = ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE', 'GIT_PREFIX', 'GIT_COMMON_DIR')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def git_env():
    return {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
