TIA Archive Compare @VERSION@

Shows what changed between two versions of a TIA Portal project. The guide, with what the report does not show, is
TiaArchiveCompare\README.md in this folder.

Start: double-click "TIA Archive Compare.exe". For a shortcut on the Desktop, right-click it and choose
Send to > Desktop (create shortcut); on Windows 11, choose Show more options first.

Needs TIA Portal V20 with the TIA Openness option, and your Windows account in the Siemens TIA Openness group
(sign out of Windows and back in after IT adds you). Comparing two commits of a git repo needs Git on the PATH
instead. This folder holds everything else, Python @PYTHON@ included: nothing to install.

The tool keeps its settings, cache and work copies in %LOCALAPPDATA%\TIA Compare, and its reports in
Documents\TIA Compare. If TIA Portal is not in C:\Program Files\Siemens\Automation\Portal V20, name its folder in
TiaBridge\settings.json here, as the guide says. To remove the tool, delete this folder, and
%LOCALAPPDATA%\TIA Compare for its cache.

Licenses: LICENSE and NOTICE for the tool. TiaArchiveCompare\window\python\LICENSE.txt for Python and the
libraries built into it; the *.dist-info folders in its Lib\site-packages for Pillow and PyYAML.
