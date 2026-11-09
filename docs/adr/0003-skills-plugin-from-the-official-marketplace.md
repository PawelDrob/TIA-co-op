---
type: Rationale
title: "ADR 0003: The skills plugin is enabled by its official marketplace id"
description: The tracked settings name mattpocock-skills@claude-plugins-official, at the cost of a marketplace and an install command in first setup, because a second id for the same plugin gives everyone already on the official route every skill twice.
tags: [adr, skills, setup]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-06T12:16:51-05:00 }
---

# ADR 0003: The skills plugin is enabled by its official marketplace id

`.claude/settings.json` enables `mattpocock-skills@claude-plugins-official`: the skills plugin from Anthropic's official marketplace, by the id the plugin's own install instructions give. The plugin's author also publishes it in a marketplace of their own, and Claude Code treats two ids for one plugin as two plugins, so naming that one would give every skill twice to anyone who installed it the official way. The cost is two setup steps. A plugin from the author's marketplace would load from the project settings alone, but the official marketplace does not fetch an external plugin from project settings, and a fresh Claude Code config does not have the official marketplace added. So first setup (`tools/setup/`) runs `claude plugin marketplace add anthropics/claude-plugins-official` and `claude plugin install`, and `/plugin` shows an error until they have run. A new version of the skills arrives when the official marketplace moves its entry to it.
