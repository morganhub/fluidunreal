# Handing a fix back to fluidblend

**Not available yet.** `handoff.request` is lot 3. Example:
[request-handoff-reexport.json](../assets/request-handoff-reexport.json).

## The rule

When the import or the audit shows something wrong that lives in Blender, this kit does not touch
it. A character that is not baked, a Rigify rig exported without its deform bones, a missing clip, a
scale that is off: all of those are fixed where they were made.

`handoff.request` writes a complete, typed **fluidblend** request to
`requests/fluidblend/<operation_id>.json` and prints the exact command to run it. The agent then
hands over to the `fluidblend` skill, and comes back with `bundle.accept` on the new export.

## The closed catalogue

| `kind` | The fluidblend request it writes |
| --- | --- |
| `reexport_unreal` | `game.export` with `export_preset: "unreal"`, for the instances of this bundle |
| `bake_rigid_limbs` | `animation.bake` with `rigid_limbs: true` on the named instance and clip |
| `create_clip` | `animation.create` from a recipe in the catalogue of the sibling kit |
| `look_at_glb` | `game.import_test` with `template: "web"`, so a human can see the GLB in a browser |

Nothing outside that list. A `kind` that is not there is `UNSUPPORTED_CAPABILITY`, said plainly.

The request is validated with the sibling kit's own `validate_request` before it is written, so what
is handed over is something that kit will actually accept. It carries only keys fluidblend
understands: `bundle_id` is this kit's extension and never leaves it.

## When it refuses

- a bundle whose producer is `external`: there is no fluidblend project behind a wrapped GLB;
- `sources.fluidblend_project` not set: the kit cannot phrase a command it cannot point anywhere;
- a `kind` outside the catalogue.

## What it never does

Write into the fluidblend project. Run fluidblend itself. Edit a `.blend`. Each kit is the only
writer of its own root, and the hand-over is a file plus a command, not a call.
