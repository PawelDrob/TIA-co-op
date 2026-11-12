<!-- Showcase video 1: a generated change report. -->
<!-- Showcase video 2: an agent making an FB and an HMI screen for that FB. -->

# TIA Portal with agents

Agents change offline TIA Portal projects through files in a git repo per project, and you see what they changed.

## What the repository provides

Every tool is experimental: it works, and it may still change.

| Tool | What it does |
|---|---|
| [TiaBridge](TiaBridge/README.md) | MCP server through which an agent reads and changes a TIA project: PLC blocks, library types, HMI screens. |
| [TiaChangeReports](TiaChangeReports/README.md) | One HTML page of what changed between two exports: LAD drawn as TIA does, SCL line by line, HMI screens before and after. |
| [TiaHmiGenerator](TiaHmiGenerator/README.md) | Writes WinCC Comfort screens from reference exports, checks them and previews them in a browser before the import. |
| [TiaArchiveCompare](TiaArchiveCompare/README.md) | A window that compares two archives, projects or commits of a git repo and opens the report. |
| [TiaAgentStatus](TiaAgentStatus/README.md) | Shows what agents do to your TIA projects: dashboard, status line, and a watcher for [herdr](https://herdr.dev), a terminal workspace for agents. |

One clone holds them all, as they call each other. The rules and the standard workflow for agents come with it: the skill
`tia-change` and the guides in `docs\agent\`.

TIA Archive Compare also comes as a download on each GitHub release, to use without a clone:
[How to use](TiaArchiveCompare/README.md#from-the-download).

What each release holds: [CHANGELOG.md](CHANGELOG.md).

Changing this repository: [CONTRIBUTING.md](CONTRIBUTING.md) and [tools/README.md](tools/README.md).

## Limitations

- TIA Portal V20 only. For export, a background session of the bridge and TIA Archive Compare also take an older project or
  archive, upgraded in a copy.
- WinCC Comfort and Advanced, not Unified.
- Offline only: downloads and online work stay with you.
- PLC blocks: `.s7dcl` is the supported format, SimaticML (xml) experimental. OBs and know-how protected blocks exist only
  as SimaticML.
- Openness does not carry faceplate type contents, master copy contents, the content of external source files, 14 screen
  controls such as the alarm view, HMI alarms, recipes, logs and user administration, or F-system blocks.
- The hardware configuration is not exported.
- The bridge of release 0.1.0 can hang a TIA with a window: TIA waits for an answer that bridge gives only at its next
  call. The bridge in this repository answers at once. Another program attached to the same TIA can still hang it so, a
  bridge of release 0.1.0 among them: run one bridge per TIA. Stopping that program has freed TIA, though once not
  within 30 s. One hang with a single bridge, an import that never returned, is not explained yet.
- Not certified for functional safety. Keep your own backups. See [NOTICE](NOTICE).
- Tested with Claude Code only.

## Requirements

- Windows, with Windows PowerShell 5.1.
- TIA Portal V20 with the TIA Openness option (tested on Update 7), and your own licenses.
- Your Windows user in the group **Siemens TIA Openness**.
- [uv](https://docs.astral.sh/uv/) and [git](https://git-scm.com/downloads/win). uv brings Python 3.12 or later.
- Optional, per tool: in its README.

## Setup

Clone this repository, then run this in its folder:

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup/setup.ps1
```

Details: [Setup](docs/user/setup.md).

## License

MIT: [LICENSE](LICENSE). Disclaimers and third-party parts: [NOTICE](NOTICE).
