# Guides

* [TiaAgentStatus internals](tia-agent-status.md) - The bridge's state files and how the dashboard, the status line and the herdr watcher read them, tell live bridges from orphans, and judge a TIA as hung; and the report run the dashboard's button starts.
* [TiaArchiveCompare internals](tia-archive-compare.md) - The window and runner that export two TIA archives through background TIA sessions and write the change report, with their event contract, commands, steps, bridge seam and cache.
* [TiaBridge internals](tia-bridge.md) - How the MCP server is built, its files and tools, the rules it enforces (archive gate, save rules, guards), its error contract and the project repo it writes.
* [TiaChangeReports internals](tia-change-reports.md) - How the change report reads two states of a project (SIMATIC SD, SimaticML, HMI XML), what it compares, how LAD is diffed and drawn, and what the page holds.
* [TiaHmiGenerator internals](tia-hmi-generator.md) - How WinCC Comfort screens are generated with hmixml, what the validator checks, how the preview server works, and how the screen object catalogue is built.
