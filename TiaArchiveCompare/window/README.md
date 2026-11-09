# TIA Archive Compare: window

The window of the archive compare tool (for users: `TiaArchiveCompare\README.md`). Python with tkinter and ttk, from the repo's `.venv`: no new dependency and no build step. Only `--snap` uses Pillow, which the repo has. It never talks to TIA: it starts the runner,
shows its events and sends it commands (the events `runner\run.py` emits).

- Start: a shortcut, made once with `<repo>\.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.window.shortcut [--folder F]` from the repo folder (default: the Desktop). It is `pythonw.exe -X utf8 -m TiaArchiveCompare.window`, starting in the repo folder, so no console opens at any moment: `pythonw.exe` is a program of the Windows subsystem. Each clone makes its own, as a shortcut holds full paths, so none is tracked. A file dropped on the shortcut stands in the Before box, a second one in After. A `.cmd` or `.bat` opens a console first, however short. From a terminal: `<repo>\.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.window` from the repo folder.
- Unit tests of the model and the shortcut file (no window; the shortcut's tests start PowerShell): `<py> -m unittest discover -s TiaArchiveCompare/window/tests -t .`; the hook runs them.
- Check by hand, not in the hook as it opens windows: `<py> TiaArchiveCompare\window\tests\check.py [--out <folder>]`. On a PC in use, run it only on a hidden desktop: make one with the Windows call `CreateDesktop` and start the check with that desktop's name in `lpDesktop` of `STARTUPINFO`. Its windows open on the desktop, most transparent but some dialogs visible, and it takes the keyboard focus. It also overwrites the clipboard, which a hidden desktop shares, so keep nothing you need on it. It runs the window with `--snap` against `tests\stub_runner.py` in every scenario (ok, ok with Show details, ok with HMI, fail, cancel,
  safety password, UMC login (project user, UMC server user), UMC skipped, runner crash, runner hang with Stop now, a dropped file), and against the real runner with its fake exporter (report, safety password, UMC login) and with a wrong TIA folder, which stops before TIA, and on a made-up git repo (two commits, a commit with no exports, no repo, a commit that is not there). It starts no TIA.
- No console, by hand as it opens the real window for seconds, and a console for its control: `<py> TiaArchiveCompare\window\tests\check_no_console.py [--out <folder>]`. It double-clicks by `ShellExecuteEx`, and through `explorer.exe`, and watches every window created or shown and the processes started. Its controls are a `.cmd` of the shape the old `start.cmd` had, on both roads, and one that only exits, which each measure must see. It starts no TIA: its comparison uses the fake exporter.

The runner: `<repo>\.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.runner run --before A --after B [--title T] [--compile [--safety]] [--hmi]
[--no-cache]`, or for two commits of a git repo `run --git REPO --before REV --after REV [--title T]`, started in the folder that holds `TiaArchiveCompare\runner\__main__.py` (searched upwards from this folder);
a `python\python.exe` in this folder is used first: the download's (`package\build.py`; there the shortcut starts the launcher at the download's top). Never `python` from `PATH`: without the `.venv` the window says to run `uv sync`. `--runner <exe>` and `--runner-args "<arguments before --before>"` replace it.

Two commits read only what was exported and committed: a change in TIA that was never exported is not in the report, and it can say "no changes" while the project differs. The report page says so under its title; the window in its list heading, and in its result when there are no changes. A commit with no exports is compared, with a warning in the log; two with none are refused.

| File | What |
|---|---|
| `model.py` | The run's state from the event lines; result, progress and time texts; commands; runner arguments; the repo and two commits of the git mode. No tkinter |
| `runner_process.py` | The runner process: UTF-8 pipes, Stop now (the runner's process tree and the TIA it reported); where the runner is. No tkinter |
| `settings.py` | Last folders of the pickers: `%LOCALAPPDATA%\TIA Compare\window.json`. No tkinter |
| `main_window.py` | The window; its log hides TiaBridge's diagnostic lines unless "Show details" is ticked (Copy log has all). The git mode reads its commits through `runner\gitrepo.py`; that is all it asks of git |
| `ask_dialog.py` | Safety password, UMC login with the "UMC server user" box (masked; the answer goes to the runner's stdin only, never to the log) |
| `clipboard.py` | Copy log: the Windows clipboard, so the text outlives the window. No tkinter |
| `edit_menu.py` | The right-click menu of a text box, which Tk lacks |
| `file_drop.py` | A file dropped on a box: the Windows message, as Tk 8.6 has no file drop. Its callback must not touch Tk (its docstring says why) |
| `shortcut.py` | Makes the shortcut that starts the window. No tkinter |
| `snapshot.py` | `--snap`: a run with no one at the window, with screenshots, `result.txt` and `log.txt` |
| `__main__.py` | Start |
