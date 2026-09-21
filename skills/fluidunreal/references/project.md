# Project

```powershell
fluidunreal init --path "D:\Projects\My Game" --project-id my-game --dry-run
fluidunreal init --path "D:\Projects\My Game" --project-id my-game
fluidunreal inspect --project . --json
```

`init` is idempotent. A re-run creates nothing, keeps the creation date, and reports any file that
differs as a conflict rather than overwriting it. `--strict` turns a conflict into exit 3.
`--dry-run` writes nothing at all.

## Layout

```
project.json              the manifest: project_id, ue{uproject, engine_series, content_root}, sources, budgets
config/local.json         machine paths; not committed, not part of any revision
config/permissions.json   read by the kit, never written by it
bundles/<bundle_id>/      what was accepted, protected once it is in
imports/                  reports of what was imported
requests/fluidblend/      typed requests handed back to the sibling kit
reviews/{bundles,assets,game,handoff}/<operation_id>/
licenses/  checkpoints/  state/{tasks,locks,plans,diagnostics,approvals}
ue/FluidUnrealTestBed/    the kit's test bed, pinned by sha256
```

## The Unreal project

Two ways. By default `init` lays down the kit's test bed: a Blueprint-only `.uproject` plus two
`.ini` files, whose scene is built in code at test time. No `.uasset` or `.umap` is ever committed,
here or in your project.

The other way is `--ue-project <absolute path to a .uproject>`, for a project you already have. It
must be a real path: a symlink or a junction would let a write escape the root that was recorded.
The kit then writes under `Content/Fluid/**` and nowhere else.

Before every engine operation, and before a task exists, the kit checks that project and refuses
with the reason (exit 3) when:

- its `EngineAssociation` names another series than the locked one;
- `PythonScriptPlugin` is not enabled. The line to add is given; the kit never edits your
  `.uproject`;
- `Content/Fluid` is a link;
- anything under `Content/Fluid` was not written by the kit: a file no `FLUID_CONTENT.json` lists,
  or a staging folder left by an interrupted import (`task reconcile` removes it).

While the editor runs, files outside `Content/Fluid` and the engine's working folders are compared
before and after, by size and time, and any change is a warning in the result, by name. The kit
writes nothing there; the engine sometimes does: it added `Config/DefaultInput.ini` to a project
that had none. The test bed builds in a blank map that is never saved, and the frame's temporary
files under `Saved/` are removed.

The template is pinned. A modified test bed is not the one lot 0 proved anything about, so a hash
mismatch is reported and the run refuses; it is never repaired behind your back.

## Budgets and disk

`budgets.max_task_minutes` defaults to 45 and `max_new_disk_gib` to 20, sized for an engine that
compiles shaders. Both are checked before an editor starts, not after: `fluidunreal plan` shows the
estimate and where each of its numbers came from (see [recovery.md](recovery.md)). `Saved/`,
`Intermediate/`, `DerivedDataCache/`, `Binaries/` and `Build/` are **reported** by `inspect` and
counted against nothing: a first shader compile is gigabytes, and it is not something the kit
produced.

## The link to fluidblend

`sources.fluidblend_project` is an absolute path, recorded so the kit can phrase an exact command
when it hands a fix back. It is read and never written. Each kit is the only writer of its own root.
