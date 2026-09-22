---
name: fluidunreal
description: >-
  Bring characters, props and animation clips into an Unreal Engine 5 project and prove they
  arrive, play and can be seen: accept a handoff bundle exported by fluidblend (or wrap a
  third-party GLB), import it through the Unreal editor on the command line, audit what the engine
  really wrote (skeleton, animations, scale, root motion, grip sockets), run a headless test bed,
  render one off-screen frame, and diagnose the workstation. Use for Unreal Engine import and
  verification tasks driven by the `fluidunreal` CLI. When the fix belongs in Blender, this kit
  writes a typed request and hands over to the `fluidblend` skill instead of touching the source.
  Check the operation catalogue for unsupported features; never simulate success.
license: MIT
metadata: {version: "0.3.5", lot: "lot 3 (complete)", compatibility: "Windows 11, Unreal Engine 5.8, uv, PowerShell 7"}
---

# fluidunreal — driven Unreal Engine imports

The skill guides, it computes nothing. Every action goes through the kit's `fluidunreal` CLI, which
validates, journals, locks, versions and produces evidence. No improvised Python in the editor.

**Task completion criterion**: the assets exist in the project, the audit measurements were taken,
and the limits are stated. Exit code 0 on its own proves nothing.

**Status: lot 3, complete.** Against Unreal Engine 5.8.2: accept a bundle, import it as a
version, measure what the engine wrote, play it in the kit's test bed (`game.smoke_test`), render
one frame of it (`game.screenshot`), and hand a fix back to fluidblend. **The test bed is not a
game: do not say it works in the game.** The frame is the only visual evidence: open
`ue-frame.png` and say you looked at it before any judgement. A smoke test that passes and an audit
that fails can both be true: read both.

## Calling the CLI

The kit is grafted into a project through `scripts/install-skill.ps1 -Target <project> -Client both`
(copies to `.claude/skills/fluidunreal/` and `.agents/skills/fluidunreal/`, never a global install).
It installs beside `fluidblend` without conflict: each kit has its own project root and is the only
writer of it.

```powershell
uv run --project <kit> fluidunreal <subcommand> --project <project>
.\skills\fluidunreal\scripts\fluidunreal.ps1 <subcommand> --project <project>
```

The wrapper resolves the kit root in this order: `$env:FLUIDUNREAL_HOME`, then the `kit-path.txt`
written next to the skill by the installer, then walking up to a `pyproject.toml` that sits beside an
`unreal_runtime/` directory. Add `--json` for structured output.

| Subcommand | What it does |
| --- | --- |
| `doctor`, `capabilities` | probe the machine; read the last probe back |
| `init --path <dir>`, `inspect` | create or complete a project; read its state |
| `ops [--all]` | the operation catalogue, and what is not available |
| `plan --operation <request.json>` | estimate and verdict, nothing executed: exit 0, or 6 over budget |
| `run --operation <request.json> [--dry-run]` | execute a typed request |
| `resume` | rebuild the state from the journal; list every task to reconcile, with its command |
| `task status\|cancel\|reconcile --id <task_id>` | read, stop, or conclude one task (`references/recovery.md`) |
| `approve-plugins --plugins <A,B>` | record the user's approval of plugins the `.uproject` enables. Only on their explicit decision |
| `schema export\|check` | the JSON Schemas |

Every subcommand but `init`, `ops` and `schema` takes `--project <project>`. A relative
`--operation` path is read from that project's root, not from the working directory.

## Decision rules

1. **Anything in Blender is not this kit.** A `.blend`, a rig, a clip to create or retime, an
   expression, a render, a video: refuse, and either write a `handoff.request` (when a template
   covers it) or hand over to the `fluidblend` skill by name. This kit reads bundles and writes
   Unreal content; it never edits a source.
2. **Identify the request**: accept a bundle, import, audit, play, render, or hand back. Check
   `fluidunreal ops --json`: only available operations may execute.
3. **Read before writing**: `project.json`, `config/permissions.json`, the bundle's
   `handoff-bundle.json`, and `fluidunreal inspect --project . --json`.
4. **Check real capabilities** with `fluidunreal doctor --project . --json` before any operation
   that starts the editor. Never assume Unreal is installed, and never assume a version.
5. **Diagnostics are read-only**, and slow the first time: opening a project compiles shaders, for
   minutes. That is a fact about the machine (`warmup_seconds`), never a performance figure.
6. **Plan before writing**: `fluidunreal plan` or `run --dry-run` estimates resources and stop
   conditions without starting the editor.
7. **Execute without per-step confirmation** inside the scope allowed by `config/permissions.json`.
8. **Versions, never overwrites.** Imported content is published as `Content/Fluid/<asset_id>/vNNN/`.
   `replace_existing` creates the next version; it never overwrites a published one. `bundles/**` and
   everything under `Content/` other than `Content/Fluid/**` are protected.
9. **Measure, then look.** `asset.audit` yields `technical_pass`, which is not `art_approved`. A
   measurement that could not be taken is `not_run`, never a pass. Before judging how the character
   looks, **open `ue-frame.png` and say you looked at it**.
10. **On failure, fix within the limits; never repeat an uncertain write.** Exit 5 means unknown
    write state: run `fluidunreal task reconcile` before any new attempt. Three attempts with no
    measured improvement → stop and explain.
11. **Record a resume point at every milestone**: `fluidunreal resume --project .`.
12. **Deliver files + evidence + limits**: published content paths, measurements with their units and
    tolerances, the checks that were `not_run`, and the next useful decision.
13. **Batch only.** There is no live mode. An Unreal editor already open on the project is a
    conflict (`SCENE_CONFLICT`): report it and ask the user to close it. Never close, save or reload
    their editor on their behalf.

Do not turn "import my character" into permission to build a game, author Blueprints or change the
project's settings.

## Request → mode → reference → commands

| User request | Mode | Reference to read | Commands |
| --- | --- | --- | --- |
| "is Unreal set up?", engine not found, which version | diagnostics | `references/environment.md` | `fluidunreal doctor --project . --json` |
| Create or resume a project, read state, plan | project | `references/project.md` | `fluidunreal init`, `inspect`, `plan`, `resume` |
| "here is a bundle from fluidblend", accept an export | bundles | `references/bundles.md` | `bundle.accept` with `source_path` |
| "import this GLB I downloaded" | bundles | `references/bundles.md` | `bundle.wrap` — licence required, no licence means refusal |
| "put the character in my Unreal project" | import | `references/import.md` | `bundle.accept` → `asset.import` → `asset.audit` |
| "is the scale right?", "does the walk play?" | import | `references/import.md` | `asset.audit`; measurements with units and tolerances |
| "does it work in Unreal?", "show me" | test bed | `references/test-bed.md` | `game.smoke_test` then `game.screenshot`; open `ue-frame.png` |
| "the character is wrong, fix it" (rig, clip, bake, scale) | handoff | `references/handoff.md` | `handoff.request` then hand over to the `fluidblend` skill |
| Stuck task, interrupted run, conflict, budget | recovery | `references/recovery.md` | `fluidunreal task status/cancel/reconcile`, `resume` |
| Anything about a `.blend`, a rig, a clip, a render | — | — | **not this kit**: hand over to the `fluidblend` skill |

## Trigger use cases

| Situation | Exact command |
| --- | --- |
| Check the engine before anything | `fluidunreal doctor --project . --json` |
| Initialize a project with its own test bed | `fluidunreal init --path "D:\Projects\My Game" --project-id my-game --dry-run` then without `--dry-run` |
| Accept what fluidblend published | `fluidunreal run --project . --operation requests/bundle-accept.json` |
| Re-check an accepted bundle | `fluidunreal run --project . --operation requests/bundle-inspect.json` |
| Import and audit in one pass | `fluidunreal run --project . --operation requests/asset-import.json` then `requests/asset-audit.json` |
| See the character | `fluidunreal run --project . --operation requests/game-screenshot.json` then open `reviews/game/<operation_id>/ue-frame.png` |
| Ask Blender for a fix | `fluidunreal run --project . --operation requests/handoff-reexport.json`, then hand the printed `fluidblend run …` command to the `fluidblend` skill |

## Invariants

- The kit installs nothing globally, never writes `config/permissions.json`, builds every external
  command as an argument list, and refuses any path outside the root, UNC, `..`, reparse point or
  protected.
- Only the kit's own runtime is sent into the editor, hashed and journalled before each launch.
  Never a generated script.
- `Saved/`, `Intermediate/` and `DerivedDataCache/` are never versioned and never counted in the
  disk budget, but their size is reported.
- Units: the bundle is in metres, Unreal is in centimetres. The conversion is **measured** against
  the bundle's reference pose, never assumed.

## What this kit does not do

Not yet (P2, listed by `fluidunreal ops --all` and refused by name): packaging or cooking
(`game.package`), retargeting to the UE5 Mannequin (`retarget.mannequin`), a live session in an open
editor, FBX. When asked for anything this kit does not do, say it plainly and stop:

> This kit does not do that. Here is what it does today, and here is what would have to be proven
> first.

Never in scope: building your game, gameplay Blueprints, C++ or Widgets; MetaHuman, Nanite, Lumen,
Chaos, Niagara or custom materials; any frame-rate or GPU claim; macOS or Linux.

## Mandatory stops

Stop, describe the blocker, list the preserved artifacts and the minimal decision expected:

- an Unreal editor open on the project: nothing is launched (`SCENE_CONFLICT`);
- a plugin in the `.uproject` the kit was not proven with (`PERMISSION_REQUIRED`): name it and ask.
  Run `approve-plugins` only when the user has said yes to those names;
- no usable GPU when a visual proof was asked for: `not_run`, never "probably fine";
- a protected path, a system permission or an elevation request;
- an unknown licence for a planned redistribution;
- a concurrent modification or an uncertain write state (exit 3 or 5);
- a time or disk budget exceeded (exit 6);
- three correction attempts without demonstrated improvement.

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | success, dry-run, or idempotent replay | deliver the files and the evidence |
| 1 | known failure | read `errors[]`, fix within the limits |
| 2 | blocked: permission, missing dependency | stop and ask; never work around it |
| 3 | conflict: revision, lock, reused `operation_id` | read the conflict, do not force |
| 4 | invalid request | fix the request against the schema |
| 5 | uncertain write state | `fluidunreal task reconcile` before any retry |
| 6 | budget exceeded | report what was consumed; do not raise the budget alone |

## References

- [environment.md](references/environment.md) — the engine, its Python, the plugins, the lock
- [project.md](references/project.md) — project layout, the test bed, an existing Unreal project
- [bundles.md](references/bundles.md) — accepting a bundle, wrapping a GLB, licences
- [import.md](references/import.md) — importing and auditing, with the measurements
- [test-bed.md](references/test-bed.md) — the 14 checks, the frame, what they do not prove
- [handoff.md](references/handoff.md) — handing a fix back to fluidblend
- [recovery.md](references/recovery.md) — interrupted tasks, conflicts, reconciliation
