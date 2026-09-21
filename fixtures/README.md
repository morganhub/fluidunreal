# Fixtures

Nothing binary lands here without its licence and its sha256 recorded in this file. No Mixamo asset,
no marketplace content, nothing whose origin cannot be shown.

## `vitruvian-walk-unreal/` — the reference bundle

Status: **to generate** (needs fluidblend 0.6.0 and Blender 5.2 on the machine).

A hand-off bundle produced by fluidblend from its own CC0 Vitruvian fixture: a skinned Rigify
character, baked with rigid limbs, exported with the Unreal preset. It is what lot 0 imports and
what the acceptance scenarios U03, U05, U06, U07 and U08 work on.

Recipe, run inside a scratch fluidblend project:

```powershell
# 1. A game project whose declared target is Unreal.
fluidblend init --path .\studio --profile game --project-id demo-studio --game-engine unreal

# 2. Admit the CC0 Vitruvian character, build the shot, make it walk, bake it.
#    (The exact requests live in fluidblend's skills/fluidblend/assets/.)
fluidblend run --project .\studio --operation requests\shot-build.json
fluidblend run --project .\studio --operation requests\animation-create-walk.json
fluidblend run --project .\studio --operation requests\animation-bake-rigid-limbs.json

# 3. Export with the preset: the bundle is published beside the GLB.
fluidblend run --project .\studio --operation requests\game-export-unreal.json

# 4. Copy the published folder here.
Copy-Item -Recurse .\studio\exports\shot010\<operation_id> .\fixtures\vitruvian-walk-unreal
```

What the bundle must contain for the proofs to mean anything:

| Field | Expected | Why it matters |
| --- | --- | --- |
| `instances[0].bone_count` | 188 | Rigify deform bones; P2 compares the imported skeleton to it |
| `instances[0].export_def_bones` | `true` | without it the Unreal preset refuses the export |
| `instances[0].skinned` / `baked` | `true` / `true` | an unbaked control rig is not what an engine should receive |
| `instances[0].reference_pose` | 2 to 5 bones with `head_m` | P2 measures the scale it really got against these |
| `clips[0].root_motion` | `root_bone` | P5 measures the travel against `stride_m * repetitions` |
| `clips[0].stride_m` | 0.6 | the walk fixture's stride |
| `validation.khronos` | `passed` | the shared validator is installed; `not_run` is acceptable but is stated |
| `files[]` with `role: license` | present | a bundle never travels without the licence of what it carries |

Licence: CC0-1.0, recorded in the bundle itself (`licenses/vitruvian.md`, copied in by fluidblend)
and inherited from `fluidblend/licenses/vitruvian.md`.

## `external-glb/` — a third-party GLB for `bundle.wrap`

Status: **to choose** (acceptance scenario U04).

A CC0 character from Quaternius or Kenney, wrapped by `bundle.wrap` into an `external` bundle. To be
recorded here with: source URL, author, licence, download date, sha256, and the exact
`bundle.wrap` command used. A GLB whose licence cannot be shown is not accepted, by the kit or here.

## Git LFS

`*.glb`, `*.uasset`, `*.umap` and `*.png` go through Git LFS (see `.gitattributes`). Check with
`git lfs ls-files` that a binary landed as a pointer and not as raw bytes in a commit.
