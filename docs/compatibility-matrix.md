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
| Unreal Engine | **5.8.2** (`5.8.2-56702186+++UE5+Release-5.8`), embedded Python 3.11.8 |
| Git / Git LFS | present |

## Foundations

| Item | Level | Proof |
| --- | --- | --- |
| Unreal series **locked on 5.8** | `proven` | P1, 2026-09-21. `LOCKED_UNREAL_SERIES = "5.8"`, observed 5.8.2 |
| `UnrealEditor-Cmd.exe` found by the registry then the default install | `proven` | P1, under `Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\` |
| Embedded Python | `proven` | P1. **3.11.8**, not the 3.13 the engine-side kit runs on. The runtime must stay 3.11-compatible |
| `-run=pythonscript -script=<file>` runs a probe and returns 0 | `proven` | P1, 11.7 s cold |
| Interchange and PIE classes exposed to Python | `proven` | P1. `AssetImportTask`, `AssetToolsHelpers`, `InterchangeManager`, `InterchangeGenericAssetsPipeline`, `EditorAssetLibrary`, `AnimationLibrary`, `AutomationLibrary`, `LevelEditorSubsystem`, `EditorLevelLibrary`, `SkeletalMeshSocket`, `DataAssetFactory`, `register_slate_post_tick_callback` all present |
| `GLTFImportOptions` | `excluded` | P1: absent in 5.8. glTF import goes through Interchange; the legacy options class no longer exists |
| `GLTFImporter` plugin | `excluded` | P1: **does not exist in 5.8**, and requesting it aborts the editor at startup. Only `GLTFExporter` ships. `Interchange`, `InterchangeEditor` and `InterchangeAssets` are enabled by the engine itself, so the `.uproject` requests only the Python plugins |
| Enabled-plugin list read from Python | `not_run` | P1 returned an empty list: no working API was found. The kit reads the `.uproject` instead |

## Import

| Item | Level | Proof |
| --- | --- | --- |
| GLB skeletal mesh + animation imported by Interchange from Python | `proven` | P2, 2026-09-21, 5.5 s: `Skeleton`, `SkeletalMesh`, `AnimSequence`, plus a `PhysicsAsset` and a `MaterialInstanceConstant` |
| Bone count | `proven`, with a caveat | P2. **189 imported for the bundle's 188**: the importer adds `<node>_ProxyTrueRootJoint` at the root. The audit compares the bundle's bones, not the engine's total |
| Bone names are rewritten | `proven` | P2. Unreal cannot hold a dot: `DEF-big_toe.02.L` arrives as `DEF-big_toe_02_L`. Every lookup maps `.` to `_`; comparing raw names silently misses |
| Animation length within one frame | `proven` | P2. 47 frames / 1.958 s against the bundle's 48 / 2.0 s: one frame of glTF sampling, stated |
| Scale measured against the reference pose, within 1 cm | `proven` | P2. Five bones from the toe to the forehead, all within 1 mm: forehead 169.285 cm expected against 169.285 observed, spine 90.035 against 90.036. The hundredfold conversion is exact and Z is up in both |
| Negative control on the scale check | `proven` | P2 re-run on a bundle whose reference pose was falsified by 10 cm: **all five checks failed**. The measurement is real, not a tautology |
| Reference pose read through a spawned component | `proven` | P2. `SkeletalMeshComponent.get_bone_location` **does not exist** in 5.8; bones are exposed as sockets, so `get_socket_location(<bone>)` is what works |
| Materials and PhysicsAsset suppressed by the pipeline | `not_run` | P2. The pipeline attaches through `task.options` only (`pipelines` and `override_pipelines` are not properties of `AssetImportTask`), and a `MaterialInstanceConstant` and a `PhysicsAsset` were created anyway. The knob has not been found; the kit either accepts them or finds it, but does not claim otherwise |
| glTF animation import is clean | `not_run` | P2. The import succeeds, but the engine logs `Ensure condition failed: NodeUid` in `InterchangeGltfAnimation.cpp:1016` and warns that the skinned node is not root. Non-fatal, recorded, not explained |
| Skin weights limited to 4 influences per vertex | `proven` (harmless) | The exporter already writes 4. See `sources.md` |
| Reference bundle to import | `proven` | Generated 2026-09-21 by `scripts/lot0/make_fixture_bundle.py`: 188 deform bones, 5 reference bones, Khronos passed, skeleton fidelity 2.6 um, licence carried. See `fixtures/README.md` |

## Test bed

| Item | Level | Proof |
| --- | --- | --- |
| PIE started from Python and stepped headless under `-nullrhi` | `proven` | P3, 2026-09-21, 180 ticks at 1/60 s through `register_slate_post_tick_callback` |
| Which starter actually simulates | `proven` | P3. **`LevelEditorSubsystem.editor_request_begin_play()`**. `editor_play_simulate()` leaves the pawn at the origin with zero velocity for 180 ticks: it looks alive and measures a statue |
| The measured actor lives in the PIE world | `proven` | P3. The editor actor never moves; `UnrealEditorSubsystem.get_game_world()` then `GameplayStatics.get_all_actors_of_class` gives the one that does |
| A single clip plays on a component | `proven` | P3. `SkeletalMeshComponent.play_animation(anim, True)`; there is no `anim_to_play` property in 5.8. The PIE duplicate does not inherit it and has to be re-armed |
| Gravity, movement and collision | `proven` | P3. The capsule rests on the floor, walks from x=0 to x=355.9 under `add_movement_input(..., force=True)`, and is stopped by the wall at x=400. Without `force=True` the input is dropped and nothing moves |
| The clip really deforms the skeleton in PIE | `proven` | P3. A named deform bone moves between ticks 30 and 45. Reading bone index 1 on tick 1 gives an empty name: the mesh is not up yet |
| The capsule rests slightly above the floor | `proven` | P3. Bottom at 2.15 cm for a half height of 88: the movement component parks it there, so the tolerance is 3 cm and the reason is written down |
| The clip advances on the PIE component | **`not_run`, and lot 0 was wrong about it** | The kit's bed reads exactly 0.0 cm of bone travel over fifteen samples: `play_animation` succeeds on the PIE component but the clip does not advance. P3 reported this as passing because its measuring window overlapped the window in which the character was walking, so it measured the actor translating rather than the skeleton deforming. `game.smoke_test` stays unavailable until this is solved |
| 14 checks written to JSON before the editor quits | `proven`, partly | P3: **10 measured and passed, 0 failed, 4 not measured by this bed** (idle state and prop attachment). A check that was not measured is listed, never counted as a pass |
| Fallback: Functional Test Blueprint via `Automation RunTests` | `excluded` | Not needed: P3 passed |

## Rendering

| Item | Level | Proof |
| --- | --- | --- |
| Off-screen frame with `-RenderOffScreen` | `proven` | P4. `AutomationLibrary.take_high_res_screenshot` writes a real PNG of the bed, once the view is aimed at the bed's `CameraActor`. It is latent: sleeping in a loop waiting for the file stops the engine ticking and nothing is ever written |
| `rendered_share` >= 1 %, with a frame without the character as the negative control | **`not_run`** | P4. The number came back at 69 % three times. **Looked at both PNGs**: the second frame shows a different scene entirely, so the share measures the view changing, not the character. Destroying the auto-spawned default pawn ends the PIE session and the second capture falls to another viewport. The probe now refuses any share above 40 % instead of reporting a green number |
| Lumen, Nanite and virtual shadow maps disabled in the test bed | `not_run` | P4 rendered, but the `.ini` was not verified line by line against the series |

## Root motion

| Item | Level | Proof |
| --- | --- | --- |
| `root_bone` clip: travel matches `stride_m * repetitions` within 2 cm | `not_run` | P5 **cannot run on the current fixture**: its baked walk is in place. A travelling clip has to be added before this is claimed |
| `in_place` clip: travel under 1 cm | `proven` | P5. The root travels 0.0 cm over the clip, read with `AnimationLibrary.get_bone_pose_for_frame` |
| The root bone is bone 0, not the first animation track | `proven` | P5. The first track was `def-thigh_l`, a thigh that swings **57.5 cm** in a walk: reading it as root travel would have called an in-place clip a travelling one |
| Negative control on the zero | `proven` | P5. The same call on that thigh returns 57.5 cm, so the root's 0.0 is a real zero and not a broken reader |
| `object` case (animated node, no bone) qualified | `not_run` | P5. Absent from this fixture. Converted or refused with a `handoff.request`; never guessed |

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
