# TiaHmiGenerator

Experimental.

Writes WinCC Comfort screens as SimaticML and shows them before they go into TIA.

## What it does

- `hmixml`: the library a project's generator calls to write screens, templates, pop-ups and text lists, copied from
  reference exports.
- `hmipreview`: validates them, draws them in a browser, writes PNGs, and lists what changed.
- `catalogue`: every object of the WinCC Comfort toolbox with its options, for the generator and the preview.

## What it does not

- Import: [TiaBridge](../TiaBridge/README.md) does, and refuses on validator errors.
- Build faceplate type contents: you build the type in TIA.
- Write WinCC Unified.
- Simulate a runtime: the preview is a view of the screens.
- Translate: a text it sets is written in every language of the project. Translate in TIA. Generating and importing that
  screen again replaces the translations.
- Keep what Openness does not export: importing over a screen deletes its alarm view or system diagnostics view. List such
  screens in `hmi\handbuilt.json` of the project repo, and do not import over them.
- Measure text in a font other than Tahoma.

## How to use

Run [first setup](../docs/user/setup.md), then ask the agent, naming a screen built in TIA to start from:

> Make a screen for the FB Pump in the style of the screen Motors, and show me the preview before you import it.

The preview yourself, from this folder:

```
..\.venv\Scripts\python.exe -X utf8 -m hmipreview serve <project repo>
```

It answers at <http://127.0.0.1:8765/>, on this machine only. Edge or Chrome is needed for PNGs.
