---
name: audit
description: Audit a finished ticket branch in a fresh session, then pass it for the coordinator's merge or send findings back.
argument-hint: "<ticket file> <branch> <worktree>"
disable-model-invocation: true
---

The gate into `main`. Run it in a session that wrote nothing of this branch, in the ticket's worktree. Judge from the ticket and the diff: its `## Comments` and the ticket session's report are claims to check, never proof.

## Steps

1. **Read.** The ticket, the tickets it names, `git log main..<branch>` and `git diff main...<branch>` whole. Done when you have read every hunk.
2. **Rebase** onto the current `main`, in the worktree; the ticket session is idle. Resolve conflicts yourself, keeping both sides' intent, and note each for the report. Then `uv sync`. Done when `git merge-base --is-ancestor main HEAD` succeeds.
3. **Run the suites.** `PRE_COMMIT_NO_SKIP=1 sh .githooks/pre-commit main` from Git Bash runs what the hook runs for every folder the branch touches, though an earlier run passed on the same commits: the gate sees its own run. Its pass leaves the stamp by which the merge's run skips. Done when it exits 0 after the rebase and the docs check, when it ran, counts 0 warnings: a warning does not fail it.
4. **Review.** Call the Skill tool with `mattpocock-skills:code-review` (plain `code-review` can reach another skill), fixed point `main`, and the ticket's absolute path as the spec: a worktree has no `.scratch\`. Then what its two axes leave to you. Done when each is checked, every finding with file and line:
   - **Correctness:** read the changed logic for bugs and for cases the tests miss.
   - **Scope:** stray files, debug output, dead code.
   - **Names:** scan the diff and the commit messages by `CODING_STANDARDS.md`.
   - **Visible change** (a report, preview or window looks different): render it on the ticket's reference (`--png` where the tool has it), into the main working tree's `.scratch\<effort>\pages\` by [the tracker doc](../../../docs/agents/issue-tracker.md), and compare with the screenshots the ticket names.
   - **Public text** (what strangers read): the branch adds or changes the wording of a README, the root's or a tool's, `CONTRIBUTING.md`, `CODING_STANDARDS.md`, `AGENTS.md`, `LICENSE` or a notice, `docs\user\`, or what a person reads under `.github\` (issue forms, pull request template). It takes the person's look in step 5. A hunk that only moves a path, fixes a broken link or changes a generated stamp does not, so a sweep piles up no pages. When in doubt whether a hunk changes the wording, it does. Other files stay off the list, among them `docs\agent\` guides, tool descriptions, code comments and `docs\adr\`: they change too often, and an agent is their first reader.
5. **Verdict: pass or findings, nothing between.** Anything you would have fixed is a finding, whatever its size, and a finding stops the merge. What the branch deliberately leaves goes on a named ticket, an existing one or one you open, with a line under `## Comments` naming it; left with no ticket, it is a finding. `Status:` holds one value; everything else goes under `## Comments`.
   - **Findings:** write them there ("audit, <date>: ..."), set `Status: in-review`, report. The coordinator sends them to the ticket session, and you audit again from step 1.
   - **Pass, code-only:** leave `Status: in-review`, write "audit passed" in Comments, and report. The coordinator merges with `merge` of [the sessions file](../coordinate/SESSIONS.md#merge), which closes this session too: running it yourself would end your own turn. When it stops on a rebase conflict or a failed hook, the coordinator sends you back to step 2.
   - **Pass, visible change or public text:** leave it unmerged. Set `Status: in-review`, "audit passed, waiting for a person's look" in Comments, and call the Skill tool with `review-page`, asking whether it may merge: for a visible change your renders next to the ticket's screenshots, for public text an HTML file, in the same `.scratch\<effort>\pages\` of the main working tree, with the new text as it reads and what changed from `main`. After the person agrees, the code-only pass applies. A no or a request to reword is a finding, in the person's words, and goes as under Findings; the audit after the fix asks the person again. After each answer the page comes down; this session does it, or the coordinator when this session has ended.

   Done when the ticket shows the verdict and your last message reports it: verdict, findings, conflicts resolved, what the branch left and on which ticket, then the branch's commit or the page's name.

## Throughout

- `main` reaches the remote on the maintainer's word only.
- The worktree and the branch stay: the coordinator's `merge` removes them with the sessions.
- Questions, TIA, MCP servers and a denied commit go as under Throughout in [`ticket`](../ticket/SKILL.md).
