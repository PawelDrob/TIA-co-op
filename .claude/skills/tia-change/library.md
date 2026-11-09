# Library types

The guide: openness-v20.md, section 3; for the documents, s7dcl-format.md.

You create and edit types. A release waits for the user's approval, asked per level.

## The middle: a new type

1. Write its document in the repo: `library\types\<folder>\<name>\<name>.s7dcl`, with no meta file. Done when the guide's checklist passes.
2. `library_create_type`, with `target_folder` for its test instance and `library_folder`. Then `compile` by name, what it contains first. Done with 0 errors.
3. Edit through `export` and `import` kind `library_type`, then `library_release_type`, contained types first. Done when released; a reviewed change can start on it from there.

## The middle: a reviewed change

1. `library_edit_type`: it starts the change and writes its report. Done when you have read the report.
2. `export` kind `library_type`, edit, `import` kind `library_type`. Done when every item is ok.
3. `compile`. It shows "incompatible changes" in the containing types, even for a comment; the release and the update clear that. Done with no other errors.
4. `library_release_type`, then `library_update_usages`, then `compile`. Done with 0 errors.
5. `library_review`: it compares what is in work with what is released and writes its verdicts. Done when every type has one.
6. **Ask.** Show the user the flagged types and their diffs, and ask per level which to approve (`toApprove` groups them): types that differ only in `S7_Setpoint` are one option per level, every other type its own option. Done when the user has answered for each level.
7. `library_approve` exactly the types the user approved, then `library_release_chain`, which releases approved types only. Done when the chain answers.
8. Repeat from 5 until nothing of the change is in work unreleased. Types TIA does not put in work (faceplate types) keep their version. Done when the report's status says the change has ended, and you have quoted what the results name.
