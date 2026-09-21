#Requires -Version 7
<#
.SYNOPSIS
  Grafts the `fluidunreal` skill into a project (Claude Code and/or Codex), on explicit request.
.DESCRIPTION
  Copies skills/fluidunreal into <Target>/.claude/skills/fluidunreal and/or <Target>/.agents/skills/fluidunreal,
  and writes kit-path.txt (the absolute path of the kit) inside the copy. There is no MCP entry to
  merge: this kit has no live mode in P0/P1. Never touches ~/.claude nor ~/.codex: the installation
  is project-local, and both this kit and fluidblend can live side by side in the same project.
.PARAMETER Target
  Root of the target project (existing folder).
.PARAMETER Client
  claude | codex | both (default: both).
.PARAMETER Force
  Replaces an already present but different copy of the skill.
.EXAMPLE
  .\scripts\install-skill.ps1 -Target "D:\Projects\My Game" -Client both
#>
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [ValidateSet('claude', 'codex', 'both')][string]$Client = 'both',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$kit = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $kit 'skills\fluidunreal'
if (-not (Test-Path (Join-Path $source 'SKILL.md'))) { throw "skill source not found: $source" }
if (-not (Test-Path $Target -PathType Container)) { throw "target folder not found: $Target" }
$Target = (Resolve-Path $Target).Path

$destinations = @()
if ($Client -in @('claude', 'both')) { $destinations += (Join-Path $Target '.claude\skills\fluidunreal') }
if ($Client -in @('codex', 'both')) { $destinations += (Join-Path $Target '.agents\skills\fluidunreal') }

function Get-TreeHash([string]$root) {
    $files = Get-ChildItem $root -Recurse -File | Where-Object { $_.Name -ne 'kit-path.txt' } | Sort-Object FullName
    $sb = [System.Text.StringBuilder]::new()
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($root.Length)
        [void]$sb.Append($rel).Append('|').Append((Get-FileHash $f.FullName -Algorithm SHA256).Hash).Append("`n")
    }
    return $sb.ToString()
}

foreach ($dest in $destinations) {
    if (Test-Path $dest) {
        if ((Get-TreeHash $source) -eq (Get-TreeHash $dest)) {
            Write-Host "identical, nothing to do: $dest"
        } elseif ($Force) {
            Remove-Item $dest -Recurse -Force
            Copy-Item $source $dest -Recurse
            Write-Host "replaced (-Force): $dest"
        } else {
            Write-Warning "existing copy differs, kept: $dest (run again with -Force to replace)"
            continue
        }
    } else {
        New-Item -ItemType Directory -Force (Split-Path $dest -Parent) | Out-Null
        Copy-Item $source $dest -Recurse
        Write-Host "installed: $dest"
    }
    Set-Content -Path (Join-Path $dest 'kit-path.txt') -Value $kit -Encoding utf8 -NoNewline
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  uv run --project `"$kit`" fluidunreal doctor --project `"$Target`""
Write-Host "  uv run --project `"$kit`" fluidunreal init --path `"$Target`" --project-id my-game --dry-run"
