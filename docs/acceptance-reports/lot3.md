# fluidunreal acceptance report - generated automatically

Generated on 2026-09-21 21:15 UTC by `pytest --acceptance-report`. Unreal Engine: `C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe`.

Statuses: `passed` = real test passed; `failed` = failure; `not_run` = missing dependency, not counted as validated.

| Scenario | Title | Status | Duration | Notes |
| --- | --- | --- | --- | --- |
| U01 | Diagnose the machine and lock the engine series | passed | 0.12 s |  |
| U02 | Initialize a project, and re-run the initialization | passed | 0.1 s |  |
| U03 | Accept a bundle published by fluidblend | passed | 0.15 s |  |
| U04 | Wrap a third-party GLB into a bundle | passed | 0.34 s |  |
| U05 | Import a bundle into Unreal and publish it as a version | passed | 22.65 s | 188 deform bones, one animation, published as v001 in 21.95s; the importer's proxy root and its extra assets are reported, not claimed away |
| U06 | Audit the imported asset: scale, axes, length, root motion | passed | 48.94 s | five reference bones within a millimetre, 188 deform bones, 47 frames against 48; the walk declared in place travels 57.5 cm over 75 top bones, and the audit fails it for that |
| U07 | Play the character headless in the test bed and report 14 checks | passed | 19.6 s | 14 checks measured and passed; the clip wrapped 1 time(s), the distance between the feet varied by 9.4 cm, the prop stayed on the hand over 204 cm |
| U08 | Render one frame off-screen and measure the share the character covers | passed | 45.69 s | the character and its shadow cover 2.11% of a 640x360 frame, in one region [274, 77, 409, 357]; the frames were opened and looked at when this scenario was written (docs/reviews) |
| U09 | Replay an operation_id, and refuse it with other parameters | passed | 0.18 s | asset.import replayed: same result, no editor, no task folder, no revision, no version; journal `replayed`. replace_existing under the same id -> exit 3; bundle.accept likewise |
| U10 | Supply an escaping path or a command as a parameter | passed | 0.02 s | 13 requests refused before execution: 9 paths -> PERMISSION_REQUIRED (exit 2), 4 identifiers -> VALIDATION_FAILED (exit 4); no task folder, no task event |
| U11 | Refuse a run over its time or disk budget before anything starts | passed | 0.03 s | 720 s estimated (nothing measured: stated defaults) over max_task_minutes=1 -> exit 6; 32 MiB needed on a drive with 5 MiB free -> exit 6; 32 MiB over max_new_disk_gib=0.01 -> exit 6; no task folder, no task event, no editor |
| U12 | Kill the editor mid-import: unknown, refused, reconciled, nothing published | passed | 41.52 s | editor killed with a staging folder on disk: exit 5, retry refused, reconcile removed the staging and published nothing, the retry then imported v001 |
| U13 | Hand a fix back to fluidblend as a request it accepts | passed | 0.07 s | four templates, each validated by fluidblend's own validate_request |
| U14 | Blender to Unreal and back: export, import, audit, play, shoot, re-export | passed | 124.45 s | fluidblend baked and exported; accepted, imported, audited (technical pass), played (14 checks) and shot; the reexport_unreal request ran in fluidblend as written and its bundle was accepted |
