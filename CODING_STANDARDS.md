# Coding standards

Read during review. What a check already refuses is not here.

- **Names.** Nothing of a real company, customer, project, plant or person in code, tests, docs or commit messages; tests and examples use made-up samples.
- **Bridge output.** The bridge's stdout belongs to the MCP protocol; diagnostics go to stderr (`Write-BridgeLog`).
- **Tests run headless.** A suite the hook runs needs no TIA, no window and no person. What needs a real TIA is a manual integration script, outside the suites.
- **Tests beside the code.** The bridge's are in `TiaBridge\Tests\`. A finding gets a test that goes red on it before the fix.
- **Docs follow facts.** A change that alters what a tool's `README.md`, `docs\agent\`, `docs\user\` or `docs\dev\` state changes them in the same branch.
- **Dates are ISO** (`2026-10-04`).
- **User guides.** A tool's `README.md` says what it does, what it does not and how to use it; longer how-tos go in `docs\user\`. Building goes in `CONTRIBUTING.md`, internals in `docs\dev\`.

## Change reports

`TiaChangeReports`, and anything else that compares two states of a project.

- **Hiding a real change is the worst failure;** showing something twice is only clutter. Weigh a noise reduction by what it could hide, not by how much it removes. No text heuristic calls two differing texts the same.
- **Ignore only what the export itself writes differently,** never what a user can change, and say so in the report.
- **Real data over guessing.** Prefer what Openness states to what a name suggests.
- **Exports only.** A report tells what the two exports hold, and reads nothing only the bridge writes, its records and logs included.
- **Universal and TIA-styled.** Nothing of one company in its look or its data.
