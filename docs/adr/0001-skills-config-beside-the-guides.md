---
type: Rationale
title: "ADR 0001: The skills' config in docs/agents/, beside the guides in docs/agent/"
description: The engineering skills' config stays in docs/agents/ although its name is one letter from the guides' folder docs/agent/, because the setup skill looks for that name and the guides' path is named throughout the bridge.
tags: [adr, agents, docs]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-06T12:16:51-05:00 }
---

# ADR 0001: The skills' config in docs/agents/, beside the guides in docs/agent/

The two folders differ by one letter and stay that way. `docs/agents/` is where `setup-matt-pocock-skills`, the setup skill of the engineering skills plugin `mattpocock-skills`, looks for and writes its config, so under another name a re-run of that skill writes a second copy. The guides' path `docs/agent/` is named in the bridge's refusals, tool texts and code, so moving them costs a change across the tools for a tidier name. Only the generated `index.md` is in both folders, so a mistyped path to a document fails on a missing file instead of reading the wrong one.
