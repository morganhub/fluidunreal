# Bundles

A bundle is the only thing this kit lets in from outside. It is a folder holding
`handoff-bundle.json` and the files that manifest names: a GLB, the producer's reports, and the
licence of everything it carries.

## Accepting what fluidblend published

Example: [request-bundle-accept.json](../assets/request-bundle-accept.json).

```powershell
fluidunreal run --project . --operation requests/bundle-accept.json
```

`source_path` is the one path this kit reads from outside its root. It is read-only, and still
checked: a real absolute directory, not a link, not a UNC share, holding a manifest. Everything
afterwards works on the kit's own copy under `bundles/<bundle_id>/`.

What is verified before anything is copied:

| Check | Refusal |
| --- | --- |
| the manifest matches the contract | `VALIDATION_FAILED`, "re-export with fluidblend 0.6.0 or later" |
| the producer is 0.6.0 or newer | `VALIDATION_FAILED` |
| every declared file is there | `VALIDATION_FAILED`, naming the file |
| every file hashes to its recorded sha256 | `VALIDATION_FAILED`, with both hashes |
| the licence file exists and is not empty | `PERMISSION_REQUIRED` |
| it fits `budgets.max_new_disk_gib` | `BUDGET_EXCEEDED` (exit 6) |
| the same `bundle_id` is not already here with different contents | `SCENE_CONFLICT` (exit 3) |

Re-accepting an identical bundle under the same `operation_id` replays the first result and creates
nothing. Reusing that `operation_id` with different parameters is a conflict: use a new one.

## Wrapping a GLB from elsewhere

Example: [request-bundle-wrap.json](../assets/request-bundle-wrap.json). A licence is required, and
the kit will not take a word for it: the file has to exist and be non-empty.

The GLB is read with the standard library. Only the JSON chunk is parsed, so a hostile file cannot
make the kit do work proportional to its contents. What comes out is what is in the file: nodes,
skins, joint count, animation names and durations. Nothing is inferred.

Only `.glb` in P0/P1. An FBX is `UNSUPPORTED_CAPABILITY`, said plainly.

**What a wrapped bundle costs you.** It carries no reference pose, so the scale check after import
will be `not_run`. The kit states that when it wraps, rather than leaving a measurement that
silently never runs. Without the Khronos validator the GLB's validity is `not_run` too.

## Re-checking one

Example: [request-bundle-inspect.json](../assets/request-bundle-inspect.json). It re-verifies every
hash against the manifest and lists which assets of the project came from that bundle.

## What a bundle carries

See [handoff-bundle-example.json](../assets/handoff-bundle-example.json), the real reference
bundle. The parts that matter downstream:

- `instances[].reference_pose`: two to five deform bone heads at rest, in metres. This is what lets
  the audit **measure** the scale the engine really gave, instead of assuming a factor of a hundred.
- `instances[].bone_count`: what the GLB holds. Unreal reports one more after import, because it
  adds a proxy root; the audit reconciles that rather than failing on it.
- `clips[].frame_range`: the GLB's own range after `slide_to_zero`, starting at 0, not the Blender
  scene's.
- `validation.khronos`: `passed`, `failed` or `not_run`. `not_run` is a result, never a pass.

## The limits an accepted bundle reports

Stated on every accept, so they are never discovered later: a Khronos status that is not `passed`,
a producer that ran no control re-import, an instance without a reference pose, an instance that is
not baked, and anything the producer itself listed as a limit.
