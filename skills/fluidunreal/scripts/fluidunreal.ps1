#Requires -Version 7
<#
.SYNOPSIS
  Thin wrapper around the kit `fluidunreal` CLI (no business logic here).
.DESCRIPTION
  Resolves the kit root in this order: $env:FLUIDUNREAL_HOME, the kit-path.txt file next to the
  skill (written by scripts/install-skill.ps1), then walking up from this script to a
  pyproject.toml accompanied by unreal_runtime/. Then runs `uv run --project <kit> fluidunreal`.
.EXAMPLE
  .\fluidunreal.ps1 doctor --project "D:\Projects\Demo Studio" --json
#>
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$ErrorActionPreference = 'Stop'

function Resolve-KitRoot {
    if ($env:FLUIDUNREAL_HOME -and (Test-Path (Join-Path $env:FLUIDUNREAL_HOME 'pyproject.toml'))) {
        return $env:FLUIDUNREAL_HOME
    }
    $marker = Join-Path (Split-Path $PSScriptRoot -Parent) 'kit-path.txt'
    if (Test-Path $marker) {
        $candidate = (Get-Content $marker -Raw).Trim()
        if ($candidate -and (Test-Path (Join-Path $candidate 'pyproject.toml'))) { return $candidate }
    }
    $dir = $PSScriptRoot
    while ($dir) {
        if ((Test-Path (Join-Path $dir 'pyproject.toml')) -and (Test-Path (Join-Path $dir 'unreal_runtime'))) { return $dir }
        $parent = Split-Path $dir -Parent
        if (-not $parent -or $parent -eq $dir) { break }
        $dir = $parent
    }
    return $null
}

$kit = Resolve-KitRoot
if (-not $kit) {
    Write-Error "fluidunreal kit not found: set FLUIDUNREAL_HOME or run scripts/install-skill.ps1 from the kit."
    exit 2
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv not found in PATH (https://docs.astral.sh/uv/)."
    exit 2
}
& uv run --project $kit fluidunreal @Arguments
exit $LASTEXITCODE
