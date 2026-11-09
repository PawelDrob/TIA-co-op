# Changelog

## 0.1.0

The first public release. Every tool is experimental: it works, and it may still change.

### The tools

- **[TiaBridge](TiaBridge/README.md):** the MCP server `tia`, through which an agent reads and changes an offline TIA
  Portal V20 project: PLC blocks, data types, DBs, tag tables, library types, HMI screens and text lists. It keeps a git
  repo per project with the exports, and archives the project before the first write.
- **[TiaChangeReports](TiaChangeReports/README.md):** one HTML page of what changed between two files, folders or git
  revisions of exports: LAD drawn as TIA does, SCL line by line, HMI screens before and after.
- **[TiaHmiGenerator](TiaHmiGenerator/README.md):** writes WinCC Comfort screens from reference exports, checks them and
  previews them in a browser before the import.
- **[TiaArchiveCompare](TiaArchiveCompare/README.md):** a window that compares two archives, projects or commits of a
  git repo and opens the report.
- **[TiaAgentStatus](TiaAgentStatus/README.md):** shows what agents do to your TIA projects: a dashboard, a status line,
  and a watcher for [herdr](https://herdr.dev), a terminal workspace for agents.
- **For agents:** the skill `tia-change` and the guides in `docs\agent\`, the rules and the standard workflow an agent
  follows on a TIA project.

PLC blocks: `.s7dcl` is the supported format, SimaticML (xml) experimental. What the tools do not cover:
[Limitations](README.md#limitations).

### The download

`TIA-Archive-Compare-0.1.0.zip` on this release holds TIA Archive Compare with everything it needs, Python included:
unblock it, unpack it and start it, with no clone. The program is not signed: if the zip was not unblocked first,
Windows SmartScreen warns the first time. [How to use it](TiaArchiveCompare/README.md#from-the-download).

### Requirements

Windows and TIA Portal V20 with the TIA Openness option; tested with Claude Code only. All of them:
[Requirements](README.md#requirements).
