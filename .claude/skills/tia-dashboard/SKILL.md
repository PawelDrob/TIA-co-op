---
name: tia-dashboard
description: "Start, open or show the TIA dashboard: the local page of what agents do to the user's TIA projects. Use also when the user asks where to see that."
---

The TIA dashboard is a local page, `http://127.0.0.1:<port>/`, port 8771 unless the user names another. What it shows: [the guide](../../../docs/user/tia-agent-status.md), "What the dashboard shows". Its icon and its options: [the README](../../../TiaAgentStatus/README.md), "How to use". `<main>` is the main working tree of the clone this file is in: the folder above `git -C "<this file's folder>" rev-parse --path-format=absolute --git-common-dir`. It runs from there, as a worktree goes away at its close, and it reads the projects root of first setup there.

## Steps

1. **Look first.** `curl.exe -s -m 10 http://127.0.0.1:<port>/`. A page holding `<h1>TIA CO-OP DASHBOARD</h1>`, or `<h1>TIA dashboard</h1>` of an older build, is one running: go to step 3, it is the user's and runs on. Another answer is some other program on that port: tell the user and offer another `--port`. No answer: step 2. Done when you know which of the three it is.
2. **Start it,** only when nothing answered. The same line in Git Bash and in PowerShell, there with `& ` before it:
   ```
   "<main>\.venv\Scripts\python.exe" -X utf8 -c "import os, subprocess as s; s.Popen([r'<main>\.venv\Scripts\pythonw.exe', '-X', 'utf8', r'<main>\TiaAgentStatus', 'dashboard', '--port', '<port>'], stdin=s.DEVNULL, stdout=s.DEVNULL, stderr=open(os.path.join(os.environ['TEMP'], 'tia-dashboard-<port>.err'), 'w'), creationflags=s.CREATE_NO_WINDOW)"
   ```
   It returns at once, and the dashboard runs on with no window and none of the shell's handles, so a caller that reads the output to its end gets that end. Its stderr is `%TEMP%\tia-dashboard-<port>.err`: what stops a start lands there, where by hand it comes up in a box on the user's desktop. `, '--root', r'<dir>'` after `'<port>'` only for a projects root the user names; other options the same way, as the how-to gives them, when the user asks. Then look as in step 1 with `-m 2`, until it answers or 20 seconds have passed: the first page waits for the first round. Done when it answers, or the user has why not:
   - a reason at the end of the `.err` file: give it;
   - none, and a process listens on the port (Stop has the line): it is still starting. Look once a minute; after 5 minutes, tell the user it listens and does not answer, with that process's number;
   - none, and nothing listens: tell the user it did not start, with the path of the `.err` file.
3. **Give the address,** `http://127.0.0.1:<port>/`. Done when your message holds it.

## Stop

The icon's menu is the user's. Stop it on the user's word, by the Windows number of the process that listens on the port, never by a process name. In PowerShell: `(Get-NetTCPConnection -LocalPort <port> -State Listen).OwningProcess`, then `taskkill.exe /PID <number>`, which closes its window: the dashboard ends and takes its icon away. When it still listens 5 seconds later (with no icon it has no window to close), `Stop-Process -Id <number>`. Done when nothing listens on the port.
