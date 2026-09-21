# fluidunreal acceptance report - generated automatically

Generated on 2026-09-21 12:43 UTC by `pytest --acceptance-report`. Unreal Engine: `C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe`.

Statuses: `passed` = real test passed; `failed` = failure; `not_run` = missing dependency, not counted as validated.

| Scenario | Title | Status | Duration | Notes |
| --- | --- | --- | --- | --- |
| U01 | Diagnose the machine and lock the engine series | passed | 0.14 s |  |
| U02 | Initialize a project, and re-run the initialization | passed | 0.09 s |  |
| U03 | Accept a bundle published by fluidblend | passed | 0.18 s |  |
| U04 | Wrap a third-party GLB into a bundle | passed | 0.35 s |  |
| U05 | Import a bundle into Unreal and publish it as a version | passed | 25.63 s | 188 deform bones, one animation, published as v001 in 24.92s; the importer's proxy root and its extra assets are reported, not claimed away |
| U06 | Audit the imported asset: scale, axes, length, root motion | passed | 41.31 s | five reference bones within a millimetre, 188 deform bones, 47 frames against 48, root travel 0.0 cm with a control bone at 57.5 cm |
| U13 | Hand a fix back to fluidblend as a request it accepts | passed | 0.07 s | four templates, each validated by fluidblend's own validate_request |
