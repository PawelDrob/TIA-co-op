$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in 'Mcp.ps1', 'Tia.ps1', 'Repo.ps1', 'Rules.ps1', 'Guards.ps1', 'Bridge.ps1', 'Tools\Objects.ps1', 'Tools\Session.ps1', 'Tools\Safety.ps1') {
    . (Join-Path $here "..\$f")
}

Describe 'safety_login' {
    function Get-TiaSoftware { 'plc' }
    function Read-SafetyPassword { $script:prompted++; $script:typed }
    function Get-SafetyAdministration { $script:admin }

    function Reset-Fakes([bool]$PasswordSet = $true, [bool]$LoggedOn = $false) {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); maxResponseChars = 20000 }
        $script:Bridge.projectName = 'P'
        $script:prompted = 0
        $script:typed = New-Object System.Security.SecureString
        foreach ($c in 'secret-123'.ToCharArray()) { $script:typed.AppendChar($c) }
        $script:admin = New-Object psobject -Property @{ IsSafetyOfflineProgramPasswordSet = $PasswordSet; IsLoggedOnToSafetyOfflineProgram = $LoggedOn; got = $null }
        $script:admin | Add-Member ScriptMethod LoginToSafetyOfflineProgram { param($p)
            $this.got = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))
            $this.IsLoggedOnToSafetyOfflineProgram = $true }
    }

    It 'asks for the password in a window, logs on with it, and never returns or logs the password' {
        Reset-Fakes
        $d = Invoke-BridgeTool 'safety_login' { param($a) Invoke-SafetyLoginTool $a } (New-Object psobject)
        $script:prompted | Should Be 1
        $script:admin.got | Should Be 'secret-123'
        $d.result.ok | Should Be $true
        $d.result.loggedOn | Should Be $true
        $d.text | Should Not Match 'secret'
        Get-Content $d.result.log -Raw | Should Not Match 'secret'
    }

    It 'refuses without a password entered, and does not call TIA' {
        Reset-Fakes
        $script:typed = $null
        $r = Invoke-SafetyLoginTool (New-Object psobject)
        $r.ok | Should Be $false
        $r.refused | Should Match 'No password entered'
        $script:admin.got | Should BeNullOrEmpty
    }

    It 'does not ask when no password is set or when already logged on' {
        Reset-Fakes -PasswordSet $false
        (Invoke-SafetyLoginTool (New-Object psobject)).note | Should Match 'no password'
        Reset-Fakes -LoggedOn $true
        (Invoke-SafetyLoginTool (New-Object psobject)).note | Should Match 'Already logged on'
        $script:prompted | Should Be 0
    }

    It 'refuses a PLC without safety administration' {
        Reset-Fakes
        $script:admin = $null
        (Invoke-SafetyLoginTool (New-Object psobject)).refused | Should Match 'no safety administration'
    }
}

Describe 'safety login in the dispatch' {
    It 'points a compile that lacks the safety login to safety_login' {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); maxResponseChars = 20000 }
        $d = Invoke-BridgeTool 'compile' { param($a) throw 'The requested action cannot be performed because permission to modify the safety program is missing either on F-CPU or project level.' } (New-Object psobject)
        $d.result.ok | Should Be $false
        $d.result.hint | Should Match 'safety_login'
    }

    It 'runs in a background session in write mode and in export only (compile of the copy)' {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects') }
        $script:Bridge.background = @{ write = $true }
        Get-BackgroundRefusal 'safety_login' (New-Object psobject) | Should BeNullOrEmpty
        $script:Bridge.background = @{ write = $false }
        Get-BackgroundRefusal 'safety_login' (New-Object psobject) | Should BeNullOrEmpty
    }

    It 'points a plain session to the password argument, not to a window' {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); maxResponseChars = 20000 }
        $script:Bridge.background = @{ write = $false; plain = $true; processId = 0; steps = (New-Object System.Collections.ArrayList) }
        $d = Invoke-BridgeTool 'compile' { param($a) throw 'The requested action cannot be performed because permission to modify the safety program is missing either on F-CPU or project level.' } ([pscustomobject]@{ scope = 'plc' })
        $d.result.hint | Should Match 'safety_login with the password'
    }
}

Describe 'safety_login with the password passed in' {
    function Get-TiaSoftware { 'plc' }
    function Read-SafetyPassword { $script:prompted++; $null }
    function Get-SafetyAdministration { $script:admin }

    function Reset-Fakes([bool]$Plain = $true, [string]$Throw = '') {
        Initialize-BridgeContext @{ projectsRoot = (Join-Path $TestDrive 'projects'); maxResponseChars = 20000 }
        $script:Bridge.projectName = 'P'
        $script:Bridge.repo = Join-Path $TestDrive 'projects\cache-1'
        $script:Bridge.background = @{ write = $false; plain = $Plain; processId = 0; steps = (New-Object System.Collections.ArrayList) }
        $script:prompted = 0
        $script:admin = New-Object psobject -Property @{ IsSafetyOfflineProgramPasswordSet = $true; IsLoggedOnToSafetyOfflineProgram = $false; got = $null; throw = $Throw }
        $script:admin | Add-Member ScriptMethod LoginToSafetyOfflineProgram { param($p)
            $this.got = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))
            if ($this.throw) { throw $this.throw }
            $this.IsLoggedOnToSafetyOfflineProgram = $true }
    }

    # Runs the tool through the dispatch, with stderr captured: @{ d; stderr }
    function Invoke-Captured($Arguments) {
        $sw = New-Object System.IO.StringWriter
        $old = [Console]::Error
        [Console]::SetError($sw)
        try { $d = Invoke-BridgeTool 'safety_login' { param($a) Write-BridgeLog "handler got $($a.password)"; Invoke-SafetyLoginTool $a } $Arguments }
        finally { [Console]::SetError($old) }
        @{ d = $d; stderr = $sw.ToString() }
    }

    It 'logs on with it in a plain session, without a window, and the password is in no result, log or stderr line' {
        Reset-Fakes
        $c = Invoke-Captured ([pscustomobject]@{ password = 'Pw-4711!' })
        $script:admin.got | Should Be 'Pw-4711!'
        $script:prompted | Should Be 0
        $c.d.result.ok | Should Be $true
        $c.d.result.loggedOn | Should Be $true
        $c.d.text | Should Not Match '4711'
        Get-Content (Join-Path $script:Bridge.repo $c.d.result.log) -Raw | Should Not Match '4711'
        $c.stderr | Should Match 'handler got \*\*\*'
        $c.stderr | Should Match 'passed in by the caller'
        $c.stderr | Should Not Match '4711'
    }

    It 'hides the password where a Siemens error quotes it' {
        Reset-Fakes -Throw 'The password Pw-4711! is not correct.'
        $c = Invoke-Captured ([pscustomobject]@{ password = 'Pw-4711!' })
        $c.d.result.ok | Should Be $false
        $c.d.result.error.message | Should Be 'The password *** is not correct.'
        $c.d.text | Should Not Match '4711'
        Get-Content (Join-Path $script:Bridge.repo $c.d.result.log) -Raw | Should Not Match '4711'
        $c.stderr | Should Not Match '4711'
    }

    It 'refuses the argument outside a plain session, and an empty one, without calling TIA' {
        Reset-Fakes -Plain $false
        (Invoke-SafetyLoginTool ([pscustomobject]@{ password = 'x1' })).refused | Should Match 'plain background session'
        $script:Bridge.background = $null
        (Invoke-SafetyLoginTool ([pscustomobject]@{ password = 'x1' })).refused | Should Match 'plain background session'
        Reset-Fakes
        (Invoke-SafetyLoginTool ([pscustomobject]@{ password = '' })).refused | Should Match 'empty'
        $script:admin.got | Should BeNullOrEmpty
        $script:prompted | Should Be 0
    }
}

Describe 'Hide-Secrets' {
    It 'hides passwords anywhere and a user name as a whole word, in nested results' {
        $s = @(Get-SecretValues ([pscustomobject]@{ umc_user = 'anna'; umc_password = 'pa$$'; path = 'x' }))
        $s.Count | Should Be 2
        $r = Hide-Secrets @{ a = 'user anna, pw pa$$'; b = @('annabel', @{ c = 'xpa$$x' }); d = [pscustomobject]@{ e = 'anna' }; n = 3; z = $null; l = @() } $s
        $r.a | Should Be 'user <umc user>, pw ***'
        $r.b[0] | Should Be 'annabel'
        $r.b[1].c | Should Be 'x***x'
        $r.d.e | Should Be '<umc user>'
        $r.n | Should Be 3
        $r.z | Should BeNullOrEmpty
        @($r.l).Count | Should Be 0
        @(Get-SecretValues ([pscustomobject]@{ password = '' })).Count | Should Be 0
    }
}
