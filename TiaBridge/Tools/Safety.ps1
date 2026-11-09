# Tools\Safety.ps1 - safety_login: logs the bridge's TIA on to the safety program of a PLC, so a compile of PLC
# software with a safety program runs. The password is typed by the user into a window of the bridge on the user's
# screen and goes as a SecureString straight to Openness (SafetyAdministration.LoginToSafetyOfflineProgram): it
# never reaches a tool result, a log or the agent. A tool that asks the user itself (the archive compare tool)
# passes it as the argument password instead, in a plain background session only; the dispatch hides it.

# How long the password window waits for the user before it gives up.
$script:SafetyPasswordTimeoutMs = 300000

# The password typed into a window on the user's screen as a SecureString, or $null (cancelled, closed, timed out).
# Seam for the tests.
function Read-SafetyPassword([string]$Title, [string]$Text) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = $Title; $form.TopMost = $true; $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false; $form.MinimizeBox = $false
    $form.ClientSize = New-Object System.Drawing.Size(420, 130)
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text; $label.SetBounds(12, 10, 396, 40)
    $box = New-Object System.Windows.Forms.TextBox
    $box.UseSystemPasswordChar = $true; $box.SetBounds(12, 55, 396, 22)
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = 'OK'; $ok.DialogResult = 'OK'; $ok.SetBounds(252, 92, 75, 26)
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'; $cancel.DialogResult = 'Cancel'; $cancel.SetBounds(333, 92, 75, 26)
    $form.Controls.AddRange(@($label, $box, $ok, $cancel))
    $form.AcceptButton = $ok; $form.CancelButton = $cancel
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = $script:SafetyPasswordTimeoutMs
    $timer.Add_Tick({ $form.DialogResult = 'Cancel'; $form.Close() })
    $form.Add_Shown({ $form.Activate(); $box.Focus() | Out-Null; $timer.Start() })
    try {
        if ($form.ShowDialog() -ne 'OK' -or -not $box.TextLength) { return $null }
        $secure = New-Object System.Security.SecureString
        foreach ($c in $box.Text.ToCharArray()) { $secure.AppendChar($c) }
        $box.Clear()
        $secure.MakeReadOnly()
        $secure
    }
    finally { $timer.Dispose(); $form.Dispose() }
}

# The SafetyAdministration service of a PLC, $null without; seam for the tests. The PLC software offers none: it
# comes from a parent (the CPU device item; V20 Update 7, project A, 2026-10-29).
function Get-SafetyAdministration($Plc) {
    $o = $Plc
    for ($i = 0; $o -and $i -lt 4; $i++) {
        if ($o.PSObject.BaseObject -is [Siemens.Engineering.IEngineeringServiceProvider]) {
            $s = Get-TiaService $o ([Siemens.Engineering.Safety.SafetyAdministration])
            if ($s) { return $s }
        }
        $o = $o.Parent
    }
    $null
}

function Invoke-SafetyLoginTool($a) {
    $device = [string]$a.device
    $given = [bool]($a -and $a.PSObject.Properties['password'])
    if ($given) {
        $bg = $script:Bridge.background
        if (-not ($bg -and $bg.plain)) {
            return New-Refusal ('password is for a tool in a plain background session (background_open plain=true), which asks the user itself. ' +
                                'Leave it out: the bridge asks the user in a window.')
        }
        if (-not ([string]$a.password).Length) { return New-Refusal 'password is empty.' }
    }
    $plc = Get-TiaSoftware 'plc' $device
    $admin = Get-SafetyAdministration $plc
    if (-not $admin) { return New-Refusal 'This PLC offers no safety administration (no safety program).' }
    $r = @{ ok = $true }
    $password = $null
    if (-not $admin.IsSafetyOfflineProgramPasswordSet) { $r.loggedOn = $false; $r.note = 'The safety program has no password: no login needed.' }
    elseif ($admin.IsLoggedOnToSafetyOfflineProgram) { $r.loggedOn = $true; $r.note = 'Already logged on to the safety program.' }
    elseif ($given) {
        Write-BridgeLog 'Safety login: password passed in by the caller.'
        $password = ConvertTo-SecurePassword ([string]$a.password)
    }
    else {
        $name = if ($device) { $device } else { 'the PLC' }
        Write-BridgeLog "Safety login: password window on the user's screen ($($script:SafetyPasswordTimeoutMs / 60000) min)."
        $password = Read-SafetyPassword "TiaBridge: safety password" ("Project $($script:Bridge.projectName), $name`n" +
            'Safety program password for the agent''s TIA (not stored, not shown to the agent):')
        if (-not $password) {
            return @{ ok = $false; refused = 'No password entered (cancelled, or the window timed out). Ask the user, then call safety_login again.' }
        }
    }
    if ($password) {
        try { $admin.LoginToSafetyOfflineProgram($password) }
        finally { $password.Dispose() }
        $r.loggedOn = [bool]$admin.IsLoggedOnToSafetyOfflineProgram
        if (-not $r.loggedOn) { $r.ok = $false; $r.note = 'TIA accepted the call but reports no login.' }
    }
    $r.next = 'compile scope plc now runs the safety program too.'
    $r
}

function Register-SafetyTool {
    Register-McpTool -Name 'safety_login' -Handler { param($a) Invoke-SafetyLoginTool $a } -Description (
        'Log on to the safety program of the PLC (needed to compile PLC software with a safety program; without it the compile fails with "permission to ' +
        'modify the safety program is missing"). Opens a password window on the user''s screen and waits up to 5 min: tell the user first. The password goes ' +
        'from that window to TIA only, never to you or a log. Not a write; the login holds until TIA ends, and until then it also allows changes to the safety program: ' +
        'import, delete, library_update_usages, library_release_chain and master_copy_to_project with safety: true (only when the user asked for that safety change). Also in a background session for export only (compile ' +
        'of the copy). password: for a tool that asks the user itself, in a plain background session only (refused elsewhere); never set it yourself.') -Schema @{
        type = 'object'; properties = @{ device = @{ type = 'string'; description = 'PLC device name; needed only when the project has several' }
                                         password = @{ type = 'string'; description = 'plain background session only (a tool, not an agent): the safety password instead of the window; hidden in results and logs' } } }
}
