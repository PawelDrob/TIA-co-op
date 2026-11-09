# Tools for changing this repository

For people changing this repository. The tools for TIA projects are in [the README](../README.md).

| Tool | What it does | How-to |
|---|---|---|
| `setup` | First setup of a clone, also its check. Everyone runs it. | [Setup](../docs/user/setup.md) |
| `dashboard` | One local page of tickets and of the review pages where agents ask you. Its core also serves [TiaAgentStatus](../TiaAgentStatus/README.md). | [Development dashboard](../docs/user/development-dashboard.md) |
| `session` | Starts, watches, prompts and closes agent sessions. | [SESSIONS.md](../.claude/skills/coordinate/SESSIONS.md) |
| `okf` | Checks `docs\` and writes its indexes. | [README](okf/README.md) |
| `hooks` | Tests the commit hook, `.githooks\pre-commit`, on throwaway repos. | [The hook's head](../.githooks/pre-commit) |
| `pointers` | Fails a commit when a skill, a standards file or the README.md of the repo or of a top-level folder names a file that is gone. | [check_pointers.py](pointers/check_pointers.py) |
