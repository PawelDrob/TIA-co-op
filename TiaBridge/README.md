# TiaBridge

Experimental.

The MCP server `tia`: an agent changes an offline TIA Portal V20 project through Openness and through files in a git repo.

## What it does

- Exports, imports and compiles PLC blocks, data types, DBs, tag tables, watch tables, HMI screens and text lists, and saves
  the project.
- Keeps a git repo per project under the projects root, with the exports, the logs, your `standards\` and the project's
  notes. Session archives lie in its `archives\` folder, outside git, and only the newest are kept (`archivesKept`, default 10).
- Archives the project before the first write, and names at each save what stays uncompiled or not consistent.
- Creates and edits library types. You approve each release, level by level.
- Makes master copies of project objects or PLC folders, in the project library or a global library, and creates project
  objects from master copies. It lists what a master copy holds, but cannot export those objects' contents: see
  [Limitations](../README.md#limitations).
- Exports a whole project into its repo, and writes a [change report](../TiaChangeReports/README.md) for a commit.
- Opens a project in a TIA with a window when you name it. When you ask, works in a TIA without a window: on a copy, or on
  a project closed in your TIA.
- Refuses to change F-blocks unless you asked for that change. Refuses an import over a know-how protected block whatever
  you ask: remove the protection in TIA first. Deletes one, or replaces it from a master copy, only when you asked for that.

## What it does not

- Download or go online.
- Close a project or lift a guard unless you say so.
- Let an agent log on to a protected project in a session without a window: open that project in TIA. A tool that asks you
  for the login itself can, as the [Archive Compare](../TiaArchiveCompare/README.md) window does.
- Read an OB as `.s7dcl`: OBs and know-how protected blocks go as SimaticML. For PLC blocks `.s7dcl` is the supported format,
  SimaticML experimental.
- Read the contents of a global library's types, only their version metadata. Bring a type into the project library to work on it.
- Export what Openness does not carry, or the hardware configuration: see [Limitations](../README.md#limitations).
- Archive to a path over 143 characters, which TIA refuses.
- Protect unsaved edits: a refused HMI import can end TIA, and they go with it.

## How to use

1. Run [first setup](../docs/user/setup.md).
2. Start a session in the clone's folder.
3. Ask for the change:

   > Open `C:\Projects\Line1\Line1.ap20` and add a 5 s start delay to the FB Pump.

   > In a background session, export the whole project `C:\Projects\Line1\Line1.ap20` into its repo.

   > Show me what changed in the last commit of Line1.

At the first connect, TIA asks whether to allow access: answer **Yes**. The agent follows the skill `tia-change`. It ends
with a commit in the project repo, a change report and what is left for you, such as the download.

If TIA does not respond for more than a minute, look for an open message box in it. With none, another program attached to
that TIA can hang it, a bridge of release 0.1.0 among them: the agent's `tia_status` names other bridges. Save in TIA if it
still answers, then stop that program or end its agent's session; with no other program, end this agent's session. Run
one bridge per TIA. Why, and what is not explained yet:
[the Openness facts](../docs/agent/openness-v20.md).

### Settings

`TiaBridge\settings.json` is optional and stays out of git. Restart the bridge after a change.

| Key | Default | What it does |
|---|---|---|
| `projectsRoot` | `%USERPROFILE%\TIA-Projects` | The folder of the project repos. Set and change it with [first setup](../docs/user/setup.md), which keeps the allow rules on it |
| `tiaRoot` | `C:\Program Files\Siemens\Automation\Portal V20` | Where TIA Portal V20 is installed |
| `archivesKept` | `10` | Session archives kept per project; at least 1 stays |
| `maxResponseChars` | `20000` | The longest result a tool returns; the full one is in the repo's `logs` |
| `useTransactions` | `true` | Whether writes run in a TIA transaction |
| `author` | The Windows user | The author of released library type versions |
| `backgroundRoot` | `<projectsRoot>\_bridge\background` | The scratch folder of background sessions |
| `standardsTemplate` | None | A folder copied into `standards` of a new project repo, never over a file |
