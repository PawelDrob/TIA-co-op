# Sample archives for the fake exporter

Not TIA archives: JSON that tells `runner\fake.py` what to do (made-up project "Plant", TiaChangeReports' test plant).
Only with `--exporter fake`. Its docstring lists the keys. The login dialog shows the sample password or login (`hint`).

| File | What happens |
|---|---|
| `Plant_2026-09-01.zap20` | before: plant v1; two uncompiled blocks (one an F-block), a know-how protected one, an F-system block; safety password `safe-1` |
| `Plant_2026-10-28.zap20` | after: plant v2; an uncompiled F-block; TIA asks a question while opening (answered No) |
| `Plant_protected.zap20` | UMC-protected: the window is asked for the login (`engineer` / `umc-1`) |
| `Plant_missing_package.zap20` | opening fails: an option package is missing |
| `Plant_2026-06-30.zap19` | a V19 archive: upgraded in the copy (5.5 min at speed 1) |

With `--hmi` the two Plant archives also export a made-up HMI device `Panel_1` (`samples\hmi\v1`, `samples\hmi\v2`:
a screen changed, one new, a tag table changed).

```
.venv\Scripts\python.exe -X utf8 -m TiaArchiveCompare.runner run --before TiaArchiveCompare\runner\samples\Plant_2026-09-01.zap20 ^
    --after TiaArchiveCompare\runner\samples\Plant_2026-10-28.zap20 --exporter fake --fake-speed 0.1 --compile --safety
```

The example report of the tool's README (`docs\user\assets\archive-compare-example.html`) is this run without `--compile`
and `--safety`; its PNG shows the block Filler (`report.html#Filler`).
