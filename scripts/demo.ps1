<#
.SYNOPSIS
  Build a demo project you can open in the Unreal editor, with the reference character imported.

.DESCRIPTION
  Runs the real chain against the real engine: accept the reference bundle, import it as a version,
  audit what the engine wrote, play it in the kit's test bed. Then prints the .uproject to open and
  what to look at inside it.

  Nothing here is a shortcut: it is the same CLI, the same requests, the same checks. If a step
  refuses, it refuses here too, with its reason.

.PARAMETER Path
  Where to create the project. Replaced if it already exists and -Force is passed.

.EXAMPLE
  pwsh -File scripts/demo.ps1 -Path "C:\Tafor\Projet\fluidunreal-demo"
#>
[CmdletBinding()]
param(
    [string]$Path = "$PWD\fluidunreal-demo",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$kit = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$bundle = Join-Path $kit 'fixtures\vitruvian-walk-unreal'

if (-not (Test-Path (Join-Path $bundle 'handoff-bundle.json'))) {
    throw "the reference bundle is missing: run `git lfs pull` in $kit"
}
if ((Test-Path $Path) -and -not $Force) {
    throw "$Path already exists (pass -Force to replace it)"
}
if (Test-Path $Path) { Remove-Item $Path -Recurse -Force }

function Invoke-Kit {
    param([string[]]$Arguments)
    & uv run --project $kit fluidunreal @Arguments
    if ($LASTEXITCODE -ne 0) { throw "fluidunreal $($Arguments[0]) exited $LASTEXITCODE" }
}

Write-Host '== creating the project ==' -ForegroundColor Cyan
Invoke-Kit @('init', '--path', $Path, '--project-id', 'demo-game', '--name', 'fluidunreal demo') | Out-Null

$requests = Join-Path $Path 'requests'
$source = ($bundle -replace '\\', '/')
@{
    'bundle-accept' = @{ operation = 'bundle.accept'; operation_id = 'accept-vitruvian-001'
        target = @{}; parameters = @{ source_path = $source } }
    'asset-import'  = @{ operation = 'asset.import'; operation_id = 'import-vitruvian-001'
        target = @{ bundle_id = 'fx-export-unreal' }; parameters = @{} }
    'asset-audit'   = @{ operation = 'asset.audit'; operation_id = 'audit-vitruvian-001'
        target = @{ bundle_id = 'fx-export-unreal'; asset_id = 'vitruvian' }; parameters = @{} }
    'game-smoke'    = @{ operation = 'game.smoke_test'; operation_id = 'smoke-vitruvian-001'
        target = @{ bundle_id = 'fx-export-unreal'; asset_id = 'vitruvian' }; parameters = @{} }
}.GetEnumerator() | ForEach-Object {
    $payload = @{ schema_version = '1.0'; project_id = 'demo-game'; dry_run = $false } + $_.Value
    $payload | ConvertTo-Json -Depth 6 |
        Set-Content -Path (Join-Path $requests "$($_.Key).json") -Encoding utf8
}

foreach ($step in @('bundle-accept', 'asset-import', 'asset-audit', 'game-smoke')) {
    Write-Host "== $step ==" -ForegroundColor Cyan
    Invoke-Kit @('run', '--project', $Path, '--operation', (Join-Path $requests "$step.json"))
}

$uproject = Join-Path $Path 'ue\FluidUnrealTestBed\FluidUnrealTestBed.uproject'
Write-Host ''
Write-Host 'Open this in Unreal Engine:' -ForegroundColor Green
Write-Host "  $uproject"
Write-Host ''
Write-Host 'In the Content Browser, look under Content/Fluid/vitruvian/v001/:'
Write-Host '  SK_vitruvian              the skeletal mesh'
Write-Host '  SKEL_vitruvian            its skeleton, 188 deform bones plus the importer proxy root'
Write-Host '  A_vitruvian_walk-baked    the walk; open it to scrub the timeline'
Write-Host ''
Write-Host 'What the kit measured, without opening anything:'
Write-Host "  $Path\reviews\assets\audit-vitruvian-001\audit-report.json"
Write-Host "  $Path\imports\import-vitruvian-001\import-report.json"
Write-Host "  $Path\reviews\game\smoke-vitruvian-001\smoke-report.json"
Write-Host ''
Write-Host 'The audit fails the walk on purpose: it is declared in place and travels 0.58 m per loop.' -ForegroundColor Yellow
Write-Host 'The test bed is not your game and draws nothing: the kit never claims it works in a game.' -ForegroundColor Yellow
