"""The environment and the flags of a git call in a repo named by path. A parent (a hook, another git-aware tool) can
leave GIT_CONTEXT in the environment, and git prefers it to -C: it would read and write the parent's repo. NO_WINDOW:
the server runs with no console, and git would open a window of its own."""
import os
import subprocess

# Every name git reads a repo from, as git rev-parse --local-env-vars lists them (a test holds this list to git's).
# Left by a parent, git prefers them to -C: it would act on the parent's repo.
GIT_CONTEXT = ('GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_OBJECT_DIRECTORY',
               'GIT_DIR', 'GIT_WORK_TREE', 'GIT_IMPLICIT_WORK_TREE', 'GIT_GRAFT_FILE', 'GIT_INDEX_FILE', 'GIT_NO_REPLACE_OBJECTS',
               'GIT_REPLACE_REF_BASE', 'GIT_PREFIX', 'GIT_SHALLOW_FILE', 'GIT_COMMON_DIR')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def git_env():
    return {k: v for k, v in os.environ.items() if k not in GIT_CONTEXT}
