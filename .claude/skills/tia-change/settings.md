# Project texts and settings

Kinds `project_texts`, `alarm_classes`, `diagnostics_settings` and `supervisions`: the files `full_export` writes in `project\texts`, `project\alarmclasses`, `project\diagnostics` and `plc\[<device>\]supervisions`, each imported over the project's own (the PLC's for supervisions). What TIA does with them: openness-v20.md, "Settings parts through import". Supervision settings and PLC alarm texts are not imported: change them in TIA.

## The middle

1. **Edit** the file step 4's `full_export` wrote. Project texts: the `.xlsx` of the language. An alarm class's display name is a project text: change it in the alarm classes' `.xml`, where the export writes `<DisplayName>` without `Culture`: add `Culture="<language>"` to it, as tried with the reference language, `en-US`, of a project with that one language (its row in the project texts was not tried). Alarm classes and diagnostics settings: the `.xml` beside the `.dat`, which `import` takes in its place. Done when the edit is in the file.
2. **Ask, for project texts and alarm classes.** TIA imports them with no undo. Tell the user what goes in, that it has no undo, and which archive is the way back, holding the project as it was when made: `import` without `no_undo` refuses and names it. A PLC or classic HMI whose online state does not read offline refuses them too: pass on what the refusal says is left (wait or go offline, or, for a device TIA gives no state for, change them in TIA). Done when the user said yes; without a yes they stay out.
3. `import`, with `no_undo: true` for those two only on that yes. Done when every item is ok and the result's `noUndo`, where it has one, is passed to the user.
4. `compile` the scopes `next` names. Done when each has 0 errors.
5. `full_export` with `parts` of the parts changed, and diff against your edit. Done when every difference left is the export's own: `CreationDate`, and after a display-name edit the empty `<DisplayName />` the export writes beside the edited one.
