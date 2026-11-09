---
name: review-page
description: Review page on the development dashboard. Use to ask a person about pictures, a rendered report or a preview, to put a decision to them, or to read and close a page's answers.
---

A person looks and answers on one page; you read the answers from a file. `<py>` is as in `AGENTS.md`, of your tree. How the dashboard behaves: [its how-to](../../../docs/user/development-dashboard.md).

## Steps

1. **Build one page,** titled with what names your session: its tab label if it has one, else effort and ticket. Building again under that title replaces it and keeps its answers, so a question in the same words stays answered: to ask it anew, take the page down first (step 4). A page built again after answers came in, or a title taken down before, shows as the next round.
   ```
   <py> tools\dashboard\review_page.py --title "<title>" --ask "<question>" --note "<context>" <png or html>::<caption> ...
   ```
   One `--ask` per question, each standing on its own. The png and html files go in the main working tree's `.scratch\<effort>\pages\` by [the tracker doc](../../../docs/agents/issue-tracker.md), never in a worktree, whose `close` refuses stray files. A page about a ticket: put `Review page: <title>` in the ticket's head, so the ticket waits for the person while the page does and links to it ([the tracker doc](../../../docs/agents/issue-tracker.md#asking-the-maintainer)). Done when it prints the page's address.
2. **Say so.** Name the page in your message, as the dashboard lists it by name; no browser opens and no paths are needed. Done when your message holds the title and what you need from it.
3. **Read the answers** in `.scratch\reviews\answers\`, in the main working tree: the file has the name of the page file step 1 printed, with `.json`, since a title's `:` or `/` do not stay in a file name. A blank answer is no answer: ask again, the page still waits for it. Done when each question's answer is acted on or recorded in the ticket.
4. **Take it down,** or it stays on the start page and may count as waiting:
   ```
   <py> tools\dashboard\review_page.py --done "<title>"
   ```
   Done when it prints where the page went.

Whoever acts on the answers takes the page down: you, or your coordinator once your session has ended. Another coordinator's pages are theirs. Answers move only with `--done`: an answer file moved by hand leaves the page waiting again with its old questions.
