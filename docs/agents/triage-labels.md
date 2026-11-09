---
type: Standard
title: Triage labels for agent skills
description: Maps the canonical triage roles of the engineering skills to the strings this repo's issue tracker records.
tags: [agents]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-03T15:43:12-05:00 }
---

# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table. "Apply" means setting the ticket's `Status:` line: a ticket holds one state at a time.

The category roles `bug` and `enhancement` go on a `Category:` line in the ticket head.

The states beyond these roles (`claimed`, `in-review`, `done`, and the wayfinder ones) are in [issue-tracker.md](issue-tracker.md).
