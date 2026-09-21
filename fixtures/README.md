# Fixtures

Nothing binary lands here without its licence and its sha256 recorded in this file. No Mixamo asset,
no marketplace content, nothing whose origin cannot be shown.

## `vitruvian-walk-unreal/` — the reference bundle

Status: **generated**, 2026-09-21, from fluidblend 0.6.0 and Blender 5.2.2 LTS on the reference
machine. This is what lot 0 imports and what acceptance scenarios U03, U05, U06, U07 and U08 work on.

Source: fluidblend's own CC0 Vitruvian fixture (`fluidblend/fixtures/vitruvian/character.blend`), a
skinned Rigify character. Licence **CC0-1.0**, carried inside the bundle at
`licenses/vitruvian.md` and reproduced from `fluidblend/licenses/vitruvian.md`.

The fixture is exactly the bundle: the manifest plus the files the manifest names.

| File | Role | Bytes | sha256 (first 16) |
| --- | --- | --- | --- |
| `vitruvian-walk.glb` | model | 8 372 060 | `7c25f927c75d86e6…` |
| `export-report.json` | export_report | 3 378 | `24bbbc69ecbefbe5…` |
| `gltf-validator.json` | khronos_report | 2 502 | `2b874b6bd6e85694…` |
| `licenses/vitruvian.md` | license | 2 228 | `ab998eb171e34406…` |

`handoff-bundle.json` itself: `ee96224898315b26…`. Every hash above is also inside the manifest, and
the generator re-verifies them after copying: a bundle that does not match its own manifest is
refused rather than committed.

**Not byte-reproducible.** The GLB, the export report and the licence come out identical every run;
the validator's report and the manifest do not, because each carries a timestamp. Regenerating
therefore changes two of the hashes above. That is a property of the format, not a fault, and it is
why a consumer verifies a bundle against *its own* manifest rather than against a hash recorded
somewhere else.

### What it carries, and why each field matters

| Field | Value | Why the proofs need it |
| --- | --- | --- |
| `producer.version` | `0.6.0` | below this, the bundle contract does not exist |
| `validation.khronos` | `passed` | the shared Khronos validator ran; `not_run` would be acceptable but stated |
| `validation.reimport_passed` | `true` | Blender re-imported its own GLB consistently |
| `validation.skeleton_fidelity_max_error_m` | 2.6e-06 | the exported skeleton reproduces the scene to 2.6 µm |
| `instances[0].bone_count` | 188 | Rigify deform bones; P2 compares the imported skeleton to this |
| `instances[0].export_def_bones` | `true` | 188 deform bones instead of 1 063 control bones |
| `instances[0].skinned` / `baked` | `true` / `true` | a real skin and a baked clip, not a control rig |
| `instances[0].gltf_node_name` | `CustomRig_Vitruvian` | the node P3 looks for in the engine |
| `instances[0].reference_pose` | 5 bones | `DEF-spine` at 0.900 m, `DEF-forehead.R` at 1.693 m, `DEF-hand.L`, `DEF-foot.L`, `DEF-big_toe.02.L`. P2 measures the scale it really got against these |
| `clips[0].clip_id` | `walk-baked` | the animation P3 plays |
| `clips[0].gltf_animation_name` | `CustomRig_Vitruvian.walk-baked` | the exact name the engine should end up with |
| `clips[0].frame_range` | `[0, 48)` | the GLB's own range after `slide_to_zero`, not the Blender scene's `[1, 49)` |
| `clips[0].root_motion` | `in_place` | **false**: see the note below |
| `warnings` | one | "the GLB carries neither constraints nor drivers": expected, and stated |
| `limits` | none | every node name was confirmed by the control re-import |

### Note on root motion

The bundle declares this clip **in place**, and it is not. Every top-level bone of the GLB travels
0.59 to 0.60 m forward over its 48 frames, read straight from the file without Unreal. The walk the
bake started from travels (`root_motion: root_bone`, with a stride); fluidblend 0.6.0's
`animation.bake` writes its manifest without a `root_motion`, so the default, `in_place`, is what
reaches the bundle.

Proof P5 missed it by reading bone 0, which is a joint the importer adds. `asset.audit` now reads
the bones that carry the body and fails this clip at 57.5 cm. The fixture is kept as it is: it is
the case that proves the audit can catch a false declaration. A correct travelling clip is exercised
by re-declaring it as the walk it was made from (`root_bone`, 0.6 m, the recipe's default stride),
and passes.

U14 does not use this fixture: it runs the same recipe with `--build-only`, which builds a fresh
studio with the fluidblend checkout it finds and prints the bundle it published.

### Regenerating it

```powershell
# From this repository, against a fluidblend checkout at ../fluidblend with its LFS files pulled.
uv run --project ..\fluidblend python scripts\lot0\make_fixture_bundle.py --force
```

The script runs the real chain against the real Blender: install the CC0 character (checking its
pinned sha256), build the shot, create the walk, bake it with `rigid_limbs`, export with
`export_preset: "unreal"`. It refuses to continue if the fixture's hash does not match, if no bundle
was published, or if the copy does not match the manifest.

## `external-glb/` — a third-party GLB for `bundle.wrap`

Status: **to choose** (acceptance scenario U04).

A CC0 character from Quaternius or Kenney, wrapped by `bundle.wrap` into an `external` bundle. To be
recorded here with: source URL, author, licence, download date, sha256, and the exact `bundle.wrap`
command used. A GLB whose licence cannot be shown is not accepted, by the kit or here.

## Git LFS

`*.glb`, `*.uasset`, `*.umap` and `*.png` go through Git LFS (see `.gitattributes`). Check with
`git lfs ls-files` that a binary landed as a pointer and not as raw bytes in a commit.
