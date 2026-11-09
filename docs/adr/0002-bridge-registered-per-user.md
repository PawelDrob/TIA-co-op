---
type: Rationale
title: "ADR 0002: The bridge is registered per user, not by a tracked .mcp.json or a plugin"
description: The MCP server is added per user with claude mcp add, and per folder for a second clone, because a plugin or project server can start a second bridge or fail by the folder it starts from, and a second bridge can hang TIA.
tags: [adr, bridge, setup]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-06T12:16:51-05:00 }
---

# ADR 0002: The bridge is registered per user, not by a tracked .mcp.json or a plugin

First setup (`tools/setup/`) adds the bridge with `claude mcp add --scope user`, which reaches every repo. A second clone adds it with `--scope local`, which holds only in that clone's folder, and the first clone keeps its server. That each folder then starts only one bridge was checked with a small test server registered in place of the bridge at both scopes: `claude mcp list`, which starts every server it lists, started only the local one in the second clone's folder and only the user one elsewhere. The same with the real bridge in a Claude Code session has not been tried yet. A plugin's server beside a user-scope one starts two processes, even when both resolve to the same command, and a second bridge beside an attached one can hang TIA. A tracked `.mcp.json` asks for approval per server in interactive sessions and fails to connect from a subfolder, because its path only resolves from the repo root. A plugin from any marketplace but one added by local path also runs from a cached copy, without the `settings.json` and `.venv` the bridge expects next to it.
