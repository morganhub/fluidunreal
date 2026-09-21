<#
.SYNOPSIS
  Lot 0: run the five feasibility proofs and record their raw output.

.DESCRIPTION
  Nothing here is part of the kit. These are throwaway probes whose only job is to produce evidence
  before a single line of src/ is written. Every proof writes a JSON report and keeps the engine log
  beside it under docs/lot0/. A proof that cannot run is recorded as not_run with its reason: it is
  never counted as a pass, and never skipped silently.

.PARAMETER Bundle
  Folder holding a fluidblend hand-off bundle (handoff-bundle.json plus its GLB). Produced by
  `fluidblend run game.export` with `export_preset: "unreal"` on the Vitruvian fixture.

.PARAMETER Editor
  Path to UnrealEditor-Cmd.exe. Discovered from the registry and the default install when omitted.

.PARAMETER Only
  Run a subset, e.g. -Only P1,P2.

.EXAMPLE
  pwsh -File scripts/lot0/run.ps1 -Bundle "D:\studio\exports\shot010\export-shot010-hero-unreal-001"
#>
[CmdletBinding()]
param(
    [string]$Bundle,
    [string]$Editor,
    [string[]]$Only = @('P1', 'P2', 'P3', 'P4', 'P5'),
    [int]$StartupTimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $PSCommandPath
$repo = Resolve-Path (Join-Path $here '..\..')
$outDir = Join-Path $repo 'docs\lot0'
$testBed = Join-Path $here 'TestBed\TestBed.uproject'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Find-Editor {
    if ($Editor) { return $Editor }
    $candidates = @()
    foreach ($root in @('HKLM:\SOFTWARE\EpicGames\Unreal Engine', 'HKLM:\SOFTWARE\WOW6432Node\EpicGames\Unreal Engine')) {
        if (Test-Path $root) {
            foreach ($key in Get-ChildItem $root) {
                $dir = (Get-ItemProperty $key.PSPath).InstalledDirectory
                if ($dir) { $candidates += Join-Path $dir 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe' }
            }
        }
    }
    $candidates += Get-ChildItem 'C:\Program Files\Epic Games' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe' }
    $found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $found) {
        throw "UnrealEditor-Cmd.exe not found. Install Unreal Engine 5 or pass -Editor <path>."
    }
    return $found
}

function Get-EngineVersion([string]$editorPath) {
    $buildVersion = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $editorPath))) 'Build\Build.version'
    if (-not (Test-Path $buildVersion)) { return $null }
    $data = Get-Content $buildVersion -Raw | ConvertFrom-Json
    return [pscustomobject]@{
        Series = "$($data.MajorVersion).$($data.MinorVersion)"
        Full   = "$($data.MajorVersion).$($data.MinorVersion).$($data.PatchVersion)"
        Branch = $data.BranchName
    }
}

function Invoke-Proof {
    param(
        [string]$Name,
        [string]$Script,
        [string[]]$ExtraArgs = @(),
        [hashtable]$Env = @{},
        [switch]$Commandlet
    )
    $report = Join-Path $outDir "$Name.json"
    $log = Join-Path $outDir "$Name.log"
    $stdout = Join-Path $outDir "$Name.stdout.txt"
    Remove-Item $report, $log, $stdout -ErrorAction SilentlyContinue

    $arguments = @($testBed)
    if ($Commandlet) {
        $arguments += @('-run=pythonscript', "-script=$Script")
    }
    else {
        $arguments += @("-ExecCmds=py `"$Script`"")
    }
    $arguments += @(
        '-unattended', '-nopause', '-nosplash', '-NoSound',
        '-stdout', '-FullStdOutLogOutput', "-abslog=$log"
    ) + $ExtraArgs

    $previous = @{}
    foreach ($key in $Env.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key)
        [Environment]::SetEnvironmentVariable($key, $Env[$key])
    }
    [Environment]::SetEnvironmentVariable('FLUIDUNREAL_LOT0_OUT', $report)

    Write-Host "== $Name ==" -ForegroundColor Cyan
    Write-Host ($editorPath + ' ' + ($arguments -join ' '))
    $started = Get-Date
    $process = Start-Process -FilePath $editorPath -ArgumentList $arguments -PassThru `
        -RedirectStandardOutput $stdout -NoNewWindow
    if (-not $process.WaitForExit($StartupTimeoutSeconds * 1000)) {
        $process.Kill($true)
        Write-Warning "$Name timed out after $StartupTimeoutSeconds s: recorded as not_run"
    }
    $elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

    foreach ($key in $Env.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key]) }

    $probe = Select-String -Path $stdout, $log -Pattern 'FLUIDUNREAL_PROBE=' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    [pscustomobject]@{
        Proof        = $Name
        ExitCode     = $process.ExitCode
        Seconds      = $elapsed
        ReportWritten = Test-Path $report
        Report       = $report
        Log          = $log
        Probe        = if ($probe) { $probe.Line.Trim() } else { $null }
    }
}

$editorPath = Find-Editor
$version = Get-EngineVersion $editorPath
Write-Host "Editor : $editorPath"
Write-Host "Version: $(if ($version) { $version.Full } else { 'unknown (Build.version unreadable)' })"

if ($Only -contains 'P2' -or $Only -contains 'P3' -or $Only -contains 'P4' -or $Only -contains 'P5') {
    if (-not $Bundle) { throw 'P2 to P5 need -Bundle <folder containing handoff-bundle.json>' }
    if (-not (Test-Path (Join-Path $Bundle 'handoff-bundle.json'))) {
        throw "no handoff-bundle.json in $Bundle"
    }
}

$results = @()
if ($Only -contains 'P1') {
    $results += Invoke-Proof -Name 'P1' -Script (Join-Path $here 'p1_probe.py') -Commandlet
}
if ($Only -contains 'P2') {
    $results += Invoke-Proof -Name 'P2' -Script (Join-Path $here 'p2_import.py') -Commandlet `
        -Env @{ FLUIDUNREAL_LOT0_BUNDLE = (Resolve-Path $Bundle).Path }
}

# P3 to P5 need what P2 imported: read the asset paths back out of its report.
$mesh = $null; $anim = $null
$p2Report = Join-Path $outDir 'P2.json'
if (Test-Path $p2Report) {
    $p2 = Get-Content $p2Report -Raw | ConvertFrom-Json
    $mesh = ($p2.assets | Where-Object { $_.class -eq 'SkeletalMesh' } | Select-Object -First 1).path
    $anim = ($p2.assets | Where-Object { $_.class -eq 'AnimSequence' } | Select-Object -First 1).path
}

foreach ($proof in @(
        @{ Name = 'P3'; Script = 'p3_pie.py'; Extra = @('-nullrhi') },
        @{ Name = 'P4'; Script = 'p4_screenshot.py'; Extra = @('-RenderOffScreen') },
        @{ Name = 'P5'; Script = 'p5_rootmotion.py'; Extra = @('-nullrhi') }
    )) {
    if ($Only -notcontains $proof.Name) { continue }
    if (-not $mesh -or -not $anim) {
        Write-Warning "$($proof.Name) not_run: P2 imported no SkeletalMesh/AnimSequence to work on"
        $results += [pscustomobject]@{ Proof = $proof.Name; ExitCode = $null; Seconds = 0
            ReportWritten = $false; Report = $null; Log = $null; Probe = 'not_run: nothing imported' }
        continue
    }
    $results += Invoke-Proof -Name $proof.Name -Script (Join-Path $here $proof.Script) `
        -ExtraArgs $proof.Extra -Env @{
            FLUIDUNREAL_LOT0_BUNDLE = (Resolve-Path $Bundle).Path
            FLUIDUNREAL_LOT0_MESH   = $mesh
            FLUIDUNREAL_LOT0_ANIM   = $anim
            FLUIDUNREAL_LOT0_SHOTS  = $outDir
        }
}

$summary = Join-Path $outDir 'summary.json'
$results | ConvertTo-Json -Depth 5 | Set-Content -Path $summary -Encoding utf8
Write-Host ''
$results | Format-Table Proof, ExitCode, Seconds, ReportWritten -AutoSize
Write-Host "Raw output: $outDir"
Write-Host 'A proof without a report is not_run. It is never counted as a pass.' -ForegroundColor Yellow
