// TIA Archive Compare.exe, at the top of the download: starts the window with the Python beside it,
//   TiaArchiveCompare\window\python\pythonw.exe -X utf8 -m TiaArchiveCompare.window <its own arguments>
// from its own folder, and waits for it. A Windows program, as pythonw.exe is: no console at any moment. Its arguments
// go on as they came, so a file dropped on it lands in the Before box as with the shortcut of a clone.
// PYTHONHOME and PYTHONPATH of the user's environment are taken away, and the user's site-packages turned off, so a
// Python installed on the PC cannot change the one of the download; the runner the window starts inherits that.
// Built by build.py with Windows PowerShell's Add-Type, which puts the version in for @VERSION@.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("TIA Archive Compare")]
[assembly: AssemblyProduct("TIA Archive Compare")]
[assembly: AssemblyVersion("@VERSION@")]
[assembly: AssemblyFileVersion("@VERSION@")]

public static class Launcher
{
    const string Title = "TIA Archive Compare";

    [STAThread]
    public static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string python = Path.Combine(root, @"TiaArchiveCompare\window\python\pythonw.exe");
        if (!File.Exists(python))
        {
            MessageBox.Show("The Python of this download is missing: " + python + "\n\nUnpack the whole zip again.",
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var start = new ProcessStartInfo(python, "-X utf8 -m TiaArchiveCompare.window" + OwnArguments());
        start.UseShellExecute = false;
        start.WorkingDirectory = root;
        start.EnvironmentVariables.Remove("PYTHONHOME");
        start.EnvironmentVariables.Remove("PYTHONPATH");
        start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        try
        {
            using (Process window = Process.Start(start))
            {
                window.WaitForExit();
                return window.ExitCode;
            }
        }
        catch (Exception e)
        {
            MessageBox.Show("The window could not be started: " + e.Message, Title, MessageBoxButtons.OK,
                            MessageBoxIcon.Error);
            return 1;
        }
    }

    // The command line after this program's own name, as it came, with its leading space: no quoting is undone and
    // done again. The name is quoted, or ends at the first space or tab.
    static string OwnArguments()
    {
        string line = Environment.CommandLine;
        int i = 0;
        if (line.StartsWith("\""))
        {
            int close = line.IndexOf('"', 1);
            i = close < 0 ? line.Length : close + 1;
        }
        else
        {
            while (i < line.Length && line[i] != ' ' && line[i] != '\t') i++;
        }
        string rest = line.Substring(i).TrimStart(' ', '\t');
        return rest.Length == 0 ? "" : " " + rest;
    }
}
