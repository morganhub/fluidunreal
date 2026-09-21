# Compatibility matrix

What is **proven** on the reference machine, what is **not tested**, and what is **excluded**. A row
moves to `proven` only when a named proof produced output that was read, and that output is kept in
`docs/lot0/`. Nothing here is a plan: a row that says `not_run` means the kit does not claim it.

Levels: `proven` (output read and kept) · `not_run` (the tool or the step was missing; no claim) ·
`excluded` (deliberately out of scope).

## Reference machine

| Item | Value |
| --- | --- |
| OS | Windows 11 Pro 10.0.26200, PowerShell 7 |
| CPU / RAM | i7-9700K (8 threads), 31.9 GiB |
| GPU | GeForce GTX 1080 Ti, 11 GiB, driver 32.0.15.6614 |
| Free disk | C: 301 GiB, D: 286 GiB, W: 3192 GiB |
| Python | 3.13 (uv 0.9.25) |
| Blender | 5.2 LTS (for the fluidblend side of the chain) |
| Unreal Engine | **not installed as of 2026-09-21** — lot 0 is blocked until it is |
| Git / Git LFS | present |

## Foundations

| Item | Level | Proof |
| --- | --- | --- |
| Unreal Engine series locked | `not_run` | P1. The series is whatever P1 finds installed; 5.8 (2026-06-17) is the latest and the last planned major 5.x |
| `UnrealEditor-Cmd.exe` discovered from the registry | `not_run` | P1 |
| Embedded Python version and enabled plugins read | `not_run` | P1 |
| First-open shader compilation time (`warmup_seconds`) | `not_run` | P1. Recorded as a fact about the machine, never as a performance figure |
| Python classes the series exposes (Interchange, PIE, automation) | `not_run` | P1 records which of them exist; the kit uses none it has not seen |

## Import

| Item | Level | Proof |
| --- | --- | --- |
| GLB skeletal mesh + animation imported by Interchange from Python | `not_run` | P2 |
| Bone count equals the bundle's (Rigify deform: 188) | `not_run` | P2 |
| Animation length within one frame of the bundle's clip | `not_run` | P2. One frame of slack is the glTF sampling, and it is stated, not hidden |
| Scale measured against the bundle's reference pose, within 1 cm | `not_run` | P2. Measured, never assumed to be a factor of 100 |
| Reference pose read through a spawned component | `not_run` | P2. The direct skeleton API is not reliably exposed to Python; the fallback is the component |
| Skin weights limited to 4 influences per vertex | `proven` (harmless) | The exporter already writes 4. See `sources.md` |

## Test bed

| Item | Level | Proof |
| --- | --- | --- |
| PIE started from Python and stepped headless under `-nullrhi` | `not_run` | P3 |
| 14 checks written to JSON before the editor quits | `not_run` | P3. A run that writes no report proves nothing |
| Fallback: Functional Test Blueprint via `Automation RunTests` | `not_run` | Only if P3 fails. The output that forced it is recorded here |

## Rendering

| Item | Level | Proof |
| --- | --- | --- |
| Off-screen frame with `-RenderOffScreen` | `not_run` | P4 |
| `rendered_share` >= 1 %, with a frame without the character as the negative control | `not_run` | P4. The negative control is what makes the number mean anything |
| Lumen, Nanite and virtual shadow maps disabled in the test bed | `not_run` | P4 confirms the `.ini` is honoured on the locked series |

## Root motion

| Item | Level | Proof |
| --- | --- | --- |
| `root_bone` clip: travel matches `stride_m * repetitions` within 2 cm | `not_run` | P5 |
| `in_place` clip: travel under 1 cm | `not_run` | P5 |
| `object` case (animated node, no bone) qualified | `not_run` | P5. Converted or refused with a `handoff.request`; never guessed |

## Excluded, by decision

| Item | Why |
| --- | --- |
| Building the user's game, gameplay Blueprints, C++, Widgets | out of scope; the kit imports and proves, it does not author a game |
| Retargeting to the UE5 Mannequin / IK Retargeter | P2 lot, identified, not started |
| Packaging and cooking (`RunUAT BuildCookRun`) | P2 lot |
| Live mode in an open editor | P2 lot; a community MCP server would be studied first, as `mcp-for-blender` was |
| MetaHuman, Nanite, Lumen, Chaos, Niagara, custom materials | out of scope; the kit keeps what the importer produces by default |
| Any frame-rate or GPU claim | never made. Only `wall_time_ms` and the machine are recorded |
| macOS, Linux | Windows 11 only, as with fluidblend |
| FBX | GLB only in P0/P1. FBX is a P2 fallback, and only if P2 of lot 0 asks for it |
