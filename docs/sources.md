# Sources

Everything this kit relies on, with its licence and the date it was checked. A line that says
`unverified` has not been read on its source page: it is a lead, not a fact.

## Unreal Engine

| Subject | Source | Licence | Checked | What is taken |
| --- | --- | --- | --- | --- |
| Unreal Engine 5.8 | [State of Unreal 2026](https://www.unrealengine.com/news/state-of-unreal-2026-top-news-from-the-show) | Unreal Engine EULA (the kit ships no engine code) | 2026-09-21 | 5.8 released 2026-06-17 and announced as the last planned major 5.x release, so the locked series is chosen from what lot 0 finds installed, not from a guess about what comes next |
| Scripting the editor with Python | [Scripting the Unreal Editor Using Python](https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-the-editor-using-python) | Epic documentation | 2026-09-21 | `PythonScriptPlugin`, `-run=pythonscript -script=<file>` for a commandlet run, `-ExecCmds="py <file>"` for a full editor with PIE |
| Multi-frame work from Python | [Python in Unreal tips](https://ryandowlingsoka.com/unreal/python-in-unreal/) | community article | 2026-09-21 | `unreal.register_slate_post_tick_callback` is how Python gets a tick; a blocking call never lets the editor advance, which is why the test bed is stepped, not looped |
| Python editor tests | [Write Editor Tests with Python](https://dev.epicgames.com/documentation/en-us/unreal-engine/write-editor-tests-with-python-in-unreal-engine) | Epic documentation | 2026-09-21 | `PythonAutomationTest` plugin, `test_*.py` under `Content/Python`, `@unreal.AutomationScheduler.add_latent_command` for multi-frame steps. This is the **fallback** if proof P3 shows PIE cannot be driven directly |
| Interchange import | [Importing Assets Using Interchange](https://dev.epicgames.com/documentation/en-us/unreal-engine/importing-assets-using-interchange-in-unreal-engine) | Epic documentation | 2026-09-21 | glTF and GLB are supported source formats; the pipeline is chosen per extension. The documented Python sample covers format detection only, so the exact pipeline wiring is what proof P2 exists to settle |
| Interchange reference | [Interchange Import Reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/interchange-import-reference-in-unreal-engine) | Epic documentation | 2026-09-21 | pipeline sections for meshes, animations and materials |
| Skeletal/animation pipeline properties | [InterchangeGenericCommonSkeletalMeshesAndAnimationsProperties](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/InterchangeGenericCommonSkeletalMeshesAndAnimationsProperties) | Epic documentation | 2026-09-21 | `import_only_animations` needs a skeleton to be set; noted for a future "animations onto an existing skeleton" path, which is out of P0/P1 scope |

### Known Interchange risks, to confirm or rule out in lot 0

| Risk | Source | Checked | Consequence if real |
| --- | --- | --- | --- |
| The glTF importer truncates skin weights to 4 influences per vertex | [forum report](https://forums.unrealengine.com/t/interchange-gltf-importer-truncates-skeletal-mesh-bone-influences-to-4-per-vertex/2745391) | 2026-09-21 | harmless here: `game.export` already exports at `export_influence_nb: 4`. Recorded so it is never mistaken for a kit bug |
| GLB import fails on non-unique bone names | [forum report](https://forums.unrealengine.com/t/gltf-import-only-animations-not-working-with-existing-skeleton-but-works-fine-after-reasigning-skeletal-mesh/1906320) | 2026-09-21 | a Rigify deform skeleton has unique names; if P2 hits it anyway, the bundle gains a refusal and a `handoff.request` |
| Animations import with a skeleton root only, no bones, and play nothing | same | 2026-09-21 | exactly what `asset.audit` measures: an animation that moves no bone is a failed check, never a pass |

## From the fluidblend side

| Subject | Source | Licence | Checked | What is taken |
| --- | --- | --- | --- | --- |
| The engine this kit reuses | [morganhub/fluidblend](https://github.com/morganhub/fluidblend) | MIT | 2026-09-21 | the reusable core listed in its `docs/architecture.md`: contracts, paths, atomic writes, hashing, journal, locks, exit codes, budgets, checkpoints, revisions, state, tool paths, glTF validator. Imported, never copied |
| The transfer contract | `fluidblend/schemas/handoff-bundle.json` (0.6.0) | MIT | 2026-09-21 | vendored here with its version; a test fails if the copy drifts from the installed dependency |
| Khronos glTF-Validator | shared `%LOCALAPPDATA%\fluidblend\tools\gltf_validator\` | Apache-2.0 | 2026-09-21 | installed once for both kits; used by `bundle.wrap` on a third-party GLB |

## Leads for P2 work, not used yet

| Subject | Source | Licence | Checked | Status |
| --- | --- | --- | --- | --- |
| Retarget preset to the UE5 Mannequin | Expy-Kit `Unreal_Mannequin` preset, already cited by fluidblend | GPL-3 | 2026-09-21 | `unverified` for this kit; retargeting is out of P0/P1 scope |
| Community MCP servers for Unreal | to inventory, as `mcp-for-blender` was for fluidblend | various | — | `unverified`; a live Unreal mode is P2 and is not attempted before it is studied the same way |

## What is deliberately absent

No engine source, no marketplace content, no `.uasset` or `.umap` in this repository. The test bed
is a `.uproject` plus `.ini` files, and its scene is built in code at test time. Any binary fixture
that ever lands here carries its licence and its sha256 in `fixtures/README.md`.
