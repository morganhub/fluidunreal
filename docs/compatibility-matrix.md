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
| The clip really deforms the skeleton in PIE | `proven` | U07, 2026-09-21. The distance between the two feet changes by 5 to 9 cm while the character walks; no displacement of the whole body can change it. With no clip it stays constant and the check fails by name (negative control). P3's own proof of this was wrong: its window overlapped the walk, so it measured the actor translating |
| The capsule rests slightly above the floor | `proven` | P3. Bottom at 2.15 cm for a half height of 88: the movement component parks it there, so the tolerance is 3 cm and the reason is written down |
| The mesh stands on the floor, facing the way it walks | `proven` | U07, U08. A `Character` carries its mesh at the capsule's centre: left there, the mesh stood 88 cm above the floor while `stands_on_floor`, which read the capsule, passed. The mesh is lowered by the half height and turned by the facing measured on the skeleton (foot to toe: 92°, so -90°); the lowest reference bone then sits at its bundle height plus the capsule's 2.15 cm, and the facing error while walking is 2° |
| The bed's scene is the same in every project | `proven` | U07, U08. `new_level` saved `SmokeBed.umap` into the project and, on the next run, failed on the existing path, so the bed was built in whatever map was open. `EditorLoadingAndSavingUtils.new_blank_map(False)` gives a blank map that is never saved |
| Nothing moves the character but the input | `proven` | U07. Without a PlayerStart, PIE spawned its default pawn at the origin, inside the capsule, and threw the character to (187, -191) before any input; `character_moves` counted it. A PlayerStart behind the camera, other pawns hidden without collision (never destroyed), and more than 5 cm of sideways drift fails the check. The prop is picked up before the capsule meets it: at 50 cm the capsule touched it first and slid 17.6 cm |
| The clip advances on the PIE component | `proven` | P6 then U07. The player's position goes from 0.84 s to 1.18 s over the window and `is_playing` is true. The 0.0 cm the bed read before came from its reader, not from playback: `get_delta_transform_from_ref_pose` is a local translation, and a bone that only rotates keeps it constant. The five pose-ticking settings tried first changed nothing; they are kept because they are harmless under `-nullrhi` |
| 14 checks written to JSON before the editor quits | `proven` | U07: **14 measured and passed, 0 failed, 0 not measured**. Stand, walk until the clip wraps, stand again; the prop is carried on the right hand bone (the bundle has no grip, stated as a limit). `is_playing` is true with no clip at all on 5.8.2, so idle is read from the clip assigned and the feet holding still. Without the clip, `walk_clip_found`, `walk_plays_looping` and `walk_clip_moves_bones` fail by name and the run exits 1 |
| A clip that travels, seen from the bed | `proven` | Every bone, spine and forehead included, moved the same 10 cm relative to the standing actor in 0.34 s: the reference walk's own travel. No check of the fourteen is about it; the audit's `root_motion_travel` is |
| Fallback: Functional Test Blueprint via `Automation RunTests` | `excluded` | Not needed: P3 passed |
| An Unreal project the user already has | `proven` | 2026-09-21. Import, smoke test and frame into a copy of another project: its files are untouched, and the one file the engine added (`Config/DefaultInput.ini`, which that project lacked) is reported by name. Refused before a task exists: another engine series, `PythonScriptPlugin` disabled, `Content/Fluid` a link, content there the kit did not index |
| The editor killed mid-import | `proven` | U12. Killed with the kit's own `kill_worker` while the staging was on disk: exit 5, retry refused, `task reconcile` removed the staging, nothing published, the retry imported `v001` |
| The whole loop through both kits | `proven` | U14. fluidblend 0.6.1 bakes and exports; accepted, imported, audited with a technical pass, played, shot; the `reexport_unreal` request ran in fluidblend as written and its bundle was accepted |

## Rendering

| Item | Level | Proof |
| --- | --- | --- |
| Off-screen frame with `-RenderOffScreen` | `proven` | U08, 2026-09-21. A `SceneCapture2D` placed in the PIE world renders into a render target (`RTF_RGBA8`, `SCS_FINAL_COLOR_LDR`, manual exposure) exported to PNG by `RenderingLibrary.export_render_target`. Eight captures are thrown away before each kept one |
| `take_high_res_screenshot` for the frame | `excluded` | U08's first run. Its second call rendered the editor's world, warmer light and a second character in reference pose, instead of the PIE one: a green 27.7 %, as lot 0's 69 % had been. It shoots whichever viewport it finds. Looked at; kept in `docs/reviews/` |
| `rendered_share` >= 1 %, with a frame without the character as the negative control | `proven` | U08: 2.1 % from 3.2 m, in one box of 219 by 268 pixels; the frames were opened and described. Hiding the character from both frames reads 0 and fails (control). A box wider than 60 % of the frame, or a share over 40 %, is refused: the guard caught a 22 % run whose box spanned 481 pixels |
| Lumen, Nanite and virtual shadow maps disabled in the test bed | `not_run` | P4 rendered, but the `.ini` was not verified line by line against the series |

## Root motion

| Item | Level | Proof |
| --- | --- | --- |
| `root_bone` clip: travel matches `stride_m * repetitions` within 2 cm | `proven`, by re-declaration | U06 controls: the reference walk declared `root_bone` with its recipe's 0.6 m passes at 57.5 cm (the stride scaled to the 46 frames of 48 actually read), and declared with 0.5 m fails. No clip exported as travelling by fluidblend has been imported yet |
| `in_place` clip: travel under 1 cm | `proven` able to fail; the passing case `not_run` | **P5 was wrong.** It read bone 0, a joint the importer adds, and got 0.0 cm. Read on the bones that carry the body, the reference walk declared in place travels **57.5 cm** and fails. No clip that really is in place has been imported yet |
| Bone 0 is the importer's proxy, and carries nothing | `proven` | U06. Bone 0 is `CustomRig_Vitruvian_ProxyTrueRootJoint`. A deform-only export has no single root: 75 bones hang from the proxy, and the audit takes the median of their horizontal travel |
| Control on the reader | `proven` | U06. The largest excursion of any of those bones within the clip: 60 cm on the walk. A reader returning constants reads zero there, and the travel is then `not_run`. P5's control was misread: its thigh's 57.5 cm was taken for a swing, and it was the travel |
| The reference walk's declaration | **false**, found 2026-09-21 | Declared `in_place`; the GLB's top-level bones travel 0.59 to 0.60 m over 48 frames, read without Unreal. Cause, in fluidblend 0.6.0: `animation.bake` writes its manifest without `root_motion`, and the default is `in_place` |
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
