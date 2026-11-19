# Setup window

The window a person double-clicks `Setup.wsf` for (for users: [Setup](../../../docs/user/setup.md#the-setup-window)). Python with
tkinter and ttk from the clone's `.venv`, as the [Archive Compare window](../../../TiaArchiveCompare/window/README.md): no
new dependency and no build step.

It has no rule of its own about what is set up: every check and change is a step of `tools\setup\setup.py`, which
`setup.ps1` runs too ([First setup internals](../../../docs/dev/tools/setup.md)).

- Start: `Setup.wsf` at the clone's top runs `.venv\Scripts\pythonw.exe -X utf8 -m tools.setup.window` in the clone, after
  `uv sync` when there is no `.venv` yet; its arguments go to the window. From a terminal, in the clone:
  `<py> -m tools.setup.window [--page N | --settings]`.
- Unit tests, no window (the hook's first setup tests): `<py> -m unittest discover -s tools/setup/tests -t .`. The model
  on made-up findings; the buttons against the command in a temp clone with a temp home and fake claude, whose files and
  claude calls must come out the same; the dashboards on free ports with `tests\stub_dashboard.py`; `Setup.wsf` under
  `cscript.exe`, which prints what `wscript.exe` shows in a box; the viewer under a registry key of the test's own.
- Check by hand, as it opens windows: `<py> tools\setup\tests\check_window.py --out <folder>`. It runs on a desktop of its
  own (`CreateDesktop`), so it may run on a PC in use: a fresh clone of this tree in a temp folder with a temp home, the
  first double-click through `wscript.exe`, every button pressed (the viewer under a test key, the dashboards on free
  ports), pictures of every page and of the settings, then a second double-click, which must open the settings with no
  console window. It starts no TIA and writes nothing of the real user's.

| File | What |
|---|---|
| `model.py` | The pages, the rows of each page and of the settings, from one read of setup's steps; where the end of the first run is kept. No tkinter |
| `dashboards.py` | Both dashboards: what answers on their ports, start with no console, open. No tkinter |
| `viewer.py` | The block viewer's registration, through its `register.py`. No tkinter |
| `main_window.py` | The window; reads and changes run off its thread, one at a time |
| `snapshot.py` | `--snap`: pictures of every page with no one at the window, for the check |
| `__main__.py` | Start, and a box with the error when it cannot start, as `pythonw` has no console |
