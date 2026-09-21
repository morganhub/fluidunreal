# Environment

## The engine

Series **5.8**, locked by lot 0 on the reference machine (observed 5.8.2). Another series is
reported `incompatible` and nothing runs.

```powershell
fluidunreal doctor --project . --json
fluidunreal doctor --project . --no-probe      # find the editor without starting it
fluidunreal capabilities --project .           # read the last diagnostic, probe nothing
```

The editor is found in this order: `config/local.json → unreal_editor_executable`, the
`FLUIDUNREAL_EDITOR` environment variable, the registry under
`HKLM\SOFTWARE\EpicGames\Unreal Engine`, then `Program Files\Epic Games\UE_*`. The version comes
from `Engine/Build/Build.version`, a JSON file, so learning the series costs no process.

## What each status means

| Status | What it says |
| --- | --- |
| `available` | seen working. For `unreal.python` that means the probe line was really read |
| `unverified` | found, but not exercised. `--no-probe` produces this, and so does a probe that answered nothing |
| `not_installed` | absent |
| `not_configured` | present but the project does not point at it |
| `incompatible` | there, and the wrong thing: a foreign series, or a project asking for a plugin the engine does not have |

**A clean exit proves nothing.** Lot 0 watched the editor start, return zero and run nothing at all,
for fifteen minutes. `available` is claimed from output that was read, never from a return code.

## Shader compilation

The first open of a project compiles shaders: minutes, once per derived-data cache. That is a fact
about the machine, recorded as `warmup_seconds`, and **never** reported as a performance figure.
`config/local.json → unreal_startup_timeout_s` defaults to 600 seconds. A junctioned cache inside
the project root is refused by the path guard; `ddc_path` must be a plain absolute path outside it.

## Things lot 0 measured that the kit depends on

- The `GLTFImporter` plugin **does not exist in 5.8**. A `.uproject` requesting it aborts the editor
  at startup before any script runs. glTF import lives in Interchange, which the engine enables by
  itself, so the test bed asks only for the Python plugins.
- The engine's embedded Python is **3.11**, not the 3.13 the kit runs on. Anything sent into the
  editor stays 3.11-compatible.
- `GLTFImportOptions` is gone on this series; the Interchange classes are what exist.

## The dependency lock

`fluidunreal doctor --write-lock dependencies.lock.json` records what was observed. It is only ever
written on that explicit flag. A later `doctor` compares and **reports** the drift; it never
replaces the lock silently. Machine paths stay in `state/diagnostics/capabilities.json`, which is
not committed.

## Shared with fluidblend

The Khronos glTF validator lives in `%LOCALAPPDATA%\fluidblend\tools\`, shared by both kits, so it
is installed once. Without it a wrapped GLB's validity is `not_run`, never `passed`.
