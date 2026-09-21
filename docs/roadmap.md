# Roadmap

What is done, what comes next, and what is not planned. Nothing here is claimed before it is proven:
a line moves to "done" with a named scenario or proof, as in
[compatibility-matrix.md](compatibility-matrix.md).

## Done

| Lot | Version | What it proved |
| --- | --- | --- |
| 0 — feasibility | 0.0.1 | Unreal Engine 5.8.2 driven from Python headless: import (P2), Play-In-Editor (P3), an off-screen frame (P4), root motion (P5), playback in PIE (P6). The series is locked on 5.8 |
| 1 — host | 0.1.0 | Contracts, project, CLI, runner, `doctor`, `bundle.accept` and `bundle.wrap`: U01 to U04 |
| 2 — engine | 0.2.0 | `asset.import` as a version, `asset.audit` measured: U05, U06 |
| 3 — test bed | 0.3.0 to 0.3.2 | `handoff.request`, `game.smoke_test` (fourteen checks), `game.screenshot`, an existing Unreal project, recovery (`task`, `resume`, `plan`), budgets, the whole loop through both kits: U07 to U14 |
| 4 — refinement, started | 0.3.3 | A human clicked the chain; what they saw (the walk snapping back, the arms held out) is now measured and asserted |

## Next: lot 4, continued

- The chain on a real request, with a character that is not the reference one. Each defect found
  becomes an assertion; each visual review is kept in `docs/reviews/` with the images looked at.
- Calibrate the disk estimate for an import (a stated factor of 4 today, not a measurement).

## Belongs to fluidblend, not here

This kit reports these; the fix is made where the clip is made.

- The walk recipe does not swing the arms: they hold the rest pose, an A-pose on the reference
  character. `game.smoke_test` warns about it.
- A clip for a `Character` that moves by its movement component should be in place. The Rigify walk
  travels its stride in every deform bone once exported with `export_def_bones`, and Unreal cannot
  extract root motion from the importer's proxy root. Either an in-place variant, or the root bone
  exported as a deform bone.
- The reference fixture keeps the false in-place declaration of fluidblend 0.6.0 on purpose: it is
  the case that proves the audit catches one. Bundles from 0.6.1 on declare the walk as it is.

## P2, on request

`game.package` (cook and package), `retarget.mannequin` (UE5 Mannequin through the IK Retargeter),
a live mode in an open editor (a community MCP server would be studied first), FBX as a fallback to
GLB, a shared `fluidcore` package for the two kits. Each is listed by `fluidunreal ops --all` and
refused by name until then.

## Not planned

Building the user's game, gameplay Blueprints, C++ or Widgets; MetaHuman, Nanite, Lumen, Chaos,
Niagara; any frame-rate or GPU claim; macOS and Linux.
