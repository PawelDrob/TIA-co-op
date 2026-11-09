# Contributing

## Setup

You need Windows, [uv](https://docs.astral.sh/uv/) and [git](https://git-scm.com/downloads/win). In the clone's folder:

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1
```

It makes the Python environment, turns on the commit checks and names what is missing. [The setup guide](docs/user/setup.md) has the rest. If you only work on code that needs no TIA, the two steps that matter are `uv sync` and `git config core.hooksPath .githooks`. A worktree needs its own `uv sync`.

**A second clone** on the same Windows user. The first clone holds the server `tia` for your Windows user. A second clone gets it for its own folder only, and in other folders `tia` stays the first clone's. `claude mcp list` then marks `tia` with `[Conflicting scopes]` and advises removing the others. Expect that and leave it. To make the second clone the one for all folders, run `claude mcp remove --scope user tia`, then run setup again. The status line stays the first clone's too, as it is per user; to make it the second clone's, remove `statusLine` from `~\.claude\settings.json`, then run setup again in that clone. The allow rules on the projects root are per Windows user as well: when one clone moves to a new `--projects-root`, another clone still on the old folder loses them. Run setup in that clone to bring them back.

## How a change gets in

[`AGENTS.md`](AGENTS.md) holds the rules for agents and people alike, and [`CODING_STANDARDS.md`](CODING_STANDARDS.md) what review reads for.

The work runs on three skills in `.claude/skills/`: `/ticket` works one ticket in a worktree, `/audit` is the gate into `main` and `/coordinate` runs sessions over a map. `tools/session/session.py` starts and watches the sessions, and `tools/dashboard/` shows tickets and review pages ([its guide](docs/user/development-dashboard.md)).

## Reports and tickets

An issue arrives on one of the three forms in `.github/ISSUE_TEMPLATE/`: Report a problem, Question or Feature request. Where it needs work, triage makes a local ticket ([their format](docs/agents/issue-tracker.md)) naming the issue's number, and the work runs on that ticket. A reply goes on GitHub only when the maintainer has approved it.

## Tests

No suite needs TIA. The commit hook runs those a commit touches. From Git Bash:

| What | Command |
|---|---|
| Every suite, as CI does | `sh .githooks/pre-commit --all` |
| What a branch touches, since a ref | `sh .githooks/pre-commit main` |

The head of `.githooks/pre-commit` lists the suites and when each runs, and its body holds each command. To run one Python suite, from a Windows terminal in the clone:

```
<clone>\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tools/setup/tests -t .
```

**PowerShell tests** run on Pester 3.4, which Windows includes. From a Windows terminal:

```
powershell -NoProfile -File TiaBridge\Tests\run.ps1 [test file]
powershell -NoProfile -File TiaBridge\Tests\parse.ps1
```

`run.ps1` picks Pester 3 when a newer one is installed too. If yours has no Pester 3: `Install-Module Pester -RequiredVersion 3.4.0 -Scope CurrentUser -Force -SkipPublisherCheck`.

**Scripts stay ASCII.** Windows PowerShell 5.1 reads a file with no BOM as ANSI, so `parse.ps1` refuses anything else.

**The archive compare window's check runs by hand,** so the hook leaves it out: it opens windows on the desktop, some of them visible, takes the keyboard focus and overwrites the clipboard. [Its README](TiaArchiveCompare/window/README.md) has the command. On a PC in use, run it only on a hidden desktop: make one with the Windows call `CreateDesktop` and start the check with that desktop's name in `lpDesktop` of `STARTUPINFO`. A hidden desktop shares the clipboard, so keep nothing you need on it.

## The download of TIA Archive Compare

A pushed tag `v<version>` makes `.github/workflows/release.yml` build `TIA-Archive-Compare-<version>.zip`, check it and attach it to the release of that tag, made as a draft when there is none: push the tag, then fill in that draft, with the version's entry of `CHANGELOG.md` as its notes, and publish it. A release made first, with its tag, gets the zip some minutes after. The tag must name the version of `TiaArchiveCompare/runner/__init__.py` and `TiaBridge/Mcp.ps1`. Run by hand from the Actions tab (**Run workflow** shows once `release.yml` is on the default branch of the repo on GitHub, or of a fork), the workflow is a dry run, on a tag too: the zip stays with the run. The same build, from a Windows terminal in the clone (it needs uv, git and Windows PowerShell):

```
<clone>\.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.package.build [--out <folder>] [--no-check] [--visible]
```

It writes `dist\TIA-Archive-Compare-<version>.zip` and then checks it, unpacked with no Python on the `PATH`; the head of `TiaArchiveCompare/package/check.py` lists the steps. The check's window opens on a hidden desktop of its own unless `--visible`. `<clone>\.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.package.check <zip>` runs the check alone. What goes in, and why: [the internals](docs/dev/tools/tia-archive-compare.md#download).

## Integration runs on a real TIA

Manual, and the only runs that need TIA. You need TIA Portal V20 with the TIA Openness option and its Windows group, plus a project with a PLC and a WinCC Comfort HMI device under the licenses TIA asks for. Use a project you can lose. Test objects are named `zz...`. Each script says at its top what it does to the project and what it leaves.

| Script | Runs on |
|---|---|
| `TiaBridge/Tests/Smoke.ps1` | The project open in a TIA with a window, with its archive as the way back: the tools under `connect` |
| `TiaBridge/Tests/LibrarySmoke.ps1` | The same, not saved: the library tools. Close the project without saving afterwards |
| `TiaBridge/Tests/BackgroundSmoke.ps1` | A throwaway copy of a closed project, with a repo of its own and no window: a background session. `-SafetyLogin` opens a password window, so run it only with a person at the screen |

Each starts its own bridge. It refuses beside a live bridge bound to a TIA under the projects root of this tree's or the main working tree's settings, as a second bridge on one TIA has hung it. Stop any other bridge yourself. None of them runs `library_left_behind`, `project_open` or `project_close`, nor `full_export` under `connect`.
