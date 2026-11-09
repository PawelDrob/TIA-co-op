$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\Tia.ps1')

if (-not ('FakeSiemens.EngineeringTargetInvocationException' -as [type])) {
    Add-Type -TypeDefinition @"
using System; using System.Collections.Generic;
namespace FakeSiemens {
    public class ExceptionMessageData { public string Text { get; set; } public string DetailText { get; set; } }
    public class EngineeringTargetInvocationException : Exception {
        public EngineeringTargetInvocationException(string m, Exception inner) : base(m, inner) { DetailMessageData = new List<ExceptionMessageData>(); }
        public IList<ExceptionMessageData> DetailMessageData { get; private set; }
    }
    public class EngineeringObjectDisposedException : Exception { public EngineeringObjectDisposedException(string m) : base(m) { } }
}
"@
}

if (-not ('FakeSiemens.NonRecoverableException' -as [type])) {
    Add-Type -TypeDefinition 'namespace FakeSiemens { public class NonRecoverableException : System.Exception { public NonRecoverableException(string m) : base(m) { } } }'
}

function New-SiemensChain {
    $root = [System.InvalidOperationException]::new('Mlc ids do not match')
    $mid = [System.ApplicationException]::new('Import of block(s) failed', $root)
    $ex = [FakeSiemens.EngineeringTargetInvocationException]::new("Error when calling method 'ImportFromDocuments'", $mid)
    $ex.DetailMessageData.Add([FakeSiemens.ExceptionMessageData]@{ Text = 'Block DriveVerticalAxis'; DetailText = '' })
    $ex.DetailMessageData.Add([FakeSiemens.ExceptionMessageData]@{ Text = 'Resource file'; DetailText = 'count 3 vs 4' })
    $ex
}

Describe 'ConvertTo-BridgeError' {
    It 'unwraps the PowerShell MethodInvocationException to the Siemens exception with its details and inner chain' {
        $siemens = New-SiemensChain
        $wrapped = [System.Management.Automation.MethodInvocationException]::new('Exception calling "ImportFromDocuments" with "3" argument(s)', $siemens)
        $e = ConvertTo-BridgeError $wrapped
        $e.type | Should Be 'FakeSiemens.EngineeringTargetInvocationException'
        $e.message | Should Be "Error when calling method 'ImportFromDocuments'"
        $e.details.Count | Should Be 2
        $e.details[0] | Should Be 'Block DriveVerticalAxis'
        $e.details[1] | Should Be 'Resource file: count 3 vs 4'
        $e.inner.Count | Should Be 2
        $e.inner[0].type | Should Be 'System.ApplicationException'
        $e.inner[1].message | Should Be 'Mlc ids do not match'
    }

    It 'accepts the ErrorRecord of a catch block' {
        $siemens = New-SiemensChain
        try { throw [System.Management.Automation.MethodInvocationException]::new('outer', $siemens) }
        catch { $e = ConvertTo-BridgeError $_ }
        $e.type | Should Be 'FakeSiemens.EngineeringTargetInvocationException'
    }

    It 'keeps a plain exception as it is, with empty details and inner lists' {
        $e = ConvertTo-BridgeError ([System.IO.IOException]::new('disk full'))
        $e.type | Should Be 'System.IO.IOException'
        $e.details.Count | Should Be 0
        $e.inner.Count | Should Be 0
    }

    It 'names the script location of a PowerShell error, so a bridge bug can be found from the log' {
        try { $nothing = $null; $nothing.Archive() } catch { $e = ConvertTo-BridgeError $_ }
        $e.type | Should Be 'System.Management.Automation.RuntimeException'
        $e.at | Should Match 'Errors\.Tests\.ps1: line \d+'
    }

    It 'marks a disposed TIA connection anywhere in the chain' {
        $ex = [System.Management.Automation.MethodInvocationException]::new('x', [FakeSiemens.EngineeringObjectDisposedException]::new('The object is disposed'))
        (ConvertTo-BridgeError $ex).tiaDisconnected | Should Be $true
        (ConvertTo-BridgeError ([System.IO.IOException]::new('x'))).tiaDisconnected | Should Be $false
        (ConvertTo-BridgeError $ex).tiaEnded | Should Be $false
    }

    It 'marks a NonRecoverableException as TIA ended (TIA ends its process after it)' {
        $ex = [System.Management.Automation.MethodInvocationException]::new('x', [FakeSiemens.NonRecoverableException]::new('The dependent property ...'))
        $e = ConvertTo-BridgeError $ex
        $e.type | Should Be 'FakeSiemens.NonRecoverableException'
        $e.tiaEnded | Should Be $true
        $e.tiaDisconnected | Should Be $true
    }
}

Describe 'ConvertTo-ResultTree' {
    It 'dumps a compiler result with its recursive messages' {
        $leaf = [pscustomobject]@{ Path = 'DriveVerticalAxis'; State = 'Error'; Description = 'Tag "x" not defined'; ErrorCount = 1; WarningCount = 0; Messages = @() }
        $mid = [pscustomobject]@{ Path = 'Program blocks'; State = 'Error'; Description = ''; ErrorCount = 1; WarningCount = 2; Messages = @($leaf) }
        $res = [pscustomobject]@{ State = 'Error'; ErrorCount = 1; WarningCount = 2; Messages = @($mid) }
        $t = ConvertTo-ResultTree $res
        $t.state | Should Be 'Error'
        $t.errors | Should Be 1
        $t.warnings | Should Be 2
        $t.messages[0].path | Should Be 'Program blocks'
        $t.messages[0].messages[0].description | Should Be 'Tag "x" not defined'
        $t.messages[0].messages[0].errors | Should Be 1
    }

    It 'dumps a document import result, whose messages carry only Message' {
        $res = [pscustomobject]@{ State = 'PartialSuccess'; Messages = @([pscustomobject]@{ Message = 'Block A imported' }, [pscustomobject]@{ Message = 'Block B failed' }) }
        $t = ConvertTo-ResultTree $res
        $t.state | Should Be 'PartialSuccess'
        $t.messages.Count | Should Be 2
        $t.messages[1].description | Should Be 'Block B failed'
    }
}
