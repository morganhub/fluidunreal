# Changelog

Format: one entry per released version. Dates are those of the development machine.
This project follows semantic versioning from 1.0.0 onwards; before that, the interface may change.

## 0.3.0 — 2026-09-21 — the hand-off closes the loop; the test bed is held back

- **`handoff.request`.** When the import or the audit shows something that belongs in Blender, the
  kit writes a complete fluidblend request and prints the exact command, rather than touching a
  source it does not own. The catalogue of templates is closed, and every request is validated with
  fluidblend's own `validate_request` before it is written: what is handed over is something that
  kit accepts, not something this one believes it should. U13 covers all four templates.
- **`game.smoke_test` is built, runs, and stays unavailable.** Nine of its ten measurable checks
  pass against the real 5.8.2: the world loads, the character spawns in the PIE world with the
  bundle's 188 bones, rests on the floor, walks 326 cm, is stopped by the wall, and passes within a
  centimetre of the prop.

  The tenth reads exactly 0.0 cm of bone travel over fifteen consecutive samples while the
  character stands still. `play_animation` returns successfully on the PIE component and the clip
  does not advance. **Lot 0 reported that check as passing and was wrong**: its measuring window
  overlapped the window in which the character was walking, so it measured the actor translating
  rather than the skeleton deforming. `walk_plays_looping` is `not_run` for the same reason, since
  a successful API call is not playback.

  An operation that cannot pass is not shipped as available. `docs/compatibility-matrix.md` and the
  test-bed reference say so.
- The runtime gained an explicit deferred path: an operation that finishes on the editor's tick
  says so, instead of a handler blocking on a wait that stops the ticking it waits for.

## 0.2.0 — 2026-09-21 — lot 2, import and audit

The engine backend, proven against Unreal Engine 5.8.2. U05 and U06 pass.

- **`asset.import`.** One dedicated editor per operation, driven through an envelope that names
  every path the runtime may touch. The bundle imports through Interchange, the kit reads back what
  the editor created, compares it to what the bundle claimed, and only then publishes
  `/Game/Fluid/<asset_id>/vNNN/` with deterministic names. A failed check publishes nothing.
- **`asset.audit`.** Measurements with their space, unit and tolerance. Five reference bones land
  within a millimetre of the bundle's metres, and falsifying that pose by ten centimetres fails all
  five. The root bone is bone 0, and a control bone that must move is read the same way: without
  it, a root travel of zero proves nothing. A measurement that could not be taken is `not_run`.
- **Versions.** `FLUID_CONTENT.json` lists every file of a version with its hash, and the revision
  points at that, so a `.uasset` edited by hand is caught. A second import makes `v002` and leaves
  `v001` verifiable.
- **Unknown beats wrong.** An editor that writes no result leaves an unknown write state, not a
  failure: calling it failed would guess in the direction that loses work.

Three defects found by running it rather than reading it: a failure while recording the worker left
the editor orphaned; `delete_directory` left the staging folder on disk; and the root motion
measurement was reading the first animation track, which is a thigh. The control bone is what
exposed the last one, by reporting the same 57.5 cm as the root.

## 0.1.1 — 2026-09-21 — the editor's generated credentials stay out

A secret scanner flagged an AndroidFileServer token in the test bed's
`Config/DefaultEngine.ini`. The editor writes it the first time it opens a project, and the file
was tracked, so it was committed and then pinned with the token already in it.

The token opens nothing: it authenticates a debug file-transfer server to an Android build of that
throwaway project, over USB, with `bIncludeInShipping` false. There is no Android target, no build,
no service. The defect was tracking a file the editor writes into.

- The lot 0 bed is materialised from the pinned template into an ignored working copy, refreshed on
  every run. Nothing the editor writes is committed.
- `AndroidFileServer` is disabled in both `.uproject` files, so no token is generated. Verified by
  re-running P1: it passes and leaves the config clean.
- Two tests refuse the class of mistake: no tracked file may carry a generated credential, and the
  lot 0 bed may not be tracked.

The token is still in the history of `aa01702` and `fa5f7f3`. Removing it there needs a history
rewrite and a force push.

## 0.1.0 — 2026-09-21 — lot 1, the host side

Everything that happens without starting the editor, and the refusals that keep the rest honest.

- **Contracts.** `Target` and `OperationRequest` subclass fluidblend's rather than copying them,
  so the envelope stays one definition; `bundle_id` is this kit's extension and the sibling kit
  still refuses a target it cannot read. A `Measurement`'s `passed` is three-valued: an unmeasurable
  check that defaults to false reads as a defect, and one that defaults to true is a lie.
- **Project.** `init` is idempotent and keeps the creation date rather than restamping it. An
  existing Unreal project must be a real absolute path: a symlink or junction would let a write
  escape the recorded root. `inspect` reports `Saved`, `Intermediate` and `DerivedDataCache` sizes
  without counting them against the disk budget.
- **Test bed.** Laid down by `init`, pinned by sha256. It asks only for the Python plugins: lot 0
  proved that requesting `GLTFImporter` on 5.8 kills the editor before any script runs, and that
  Interchange is enabled by the engine itself.
- **Doctor.** Finds the editor through the registry and the default install, reads the series from
  `Engine/Build/Build.version` without launching anything, and hashes the binary. `available` is
  never claimed from an exit code: lot 0 watched the editor start, return zero and run nothing.
- **Bundles.** `bundle.accept`, `bundle.wrap` and `bundle.inspect`, with a stdlib GLB reader that
  parses only the JSON chunk. A bundle without a readable licence is refused: it is a
  redistribution format.
- **Runner.** The twelve-step flow trimmed to this kit, with fluidblend's exit codes and file
  formats unchanged, so one reader understands both projects. Operations that need the editor are
  refused by name with the lot they land in.
- Acceptance scenarios **U01 to U04 pass**. The engine backend, the test bed run and the hand-off
  request are lots 2 and 3, and the catalogue says so.

## 0.0.1 — 2026-09-21 — lot 0, feasibility on Unreal Engine 5.8.2

No kit yet. Five throwaway probes run against the real engine so that nothing is designed on a
guess. Raw output in `docs/lot0/`, findings in `docs/compatibility-matrix.md`.

- **Locked series: 5.8** (observed 5.8.2). Embedded Python is **3.11.8**, not the 3.13 the engine
  runs on: the runtime has to stay 3.11-compatible.
- The `GLTFImporter` plugin **no longer exists** in 5.8 and requesting it aborts the editor at
  startup; glTF import lives in Interchange, which the engine enables itself.
- The GLB imports in 5.5 s. **Scale is measured, not assumed**: five deform bones land within 1 mm
  of the bundle's reference pose, and falsifying that pose by 10 cm fails all five.
- Unreal rewrites dots to underscores in bone names and adds a proxy root joint, so the audit maps
  names and counts the bundle's bones rather than the engine's total.
- Headless Play-In-Editor is driveable from Python: 10 checks measured and passed, 0 failed, 4 not
  measured by that bed. Only `editor_request_begin_play` actually simulates.
- The off-screen frame renders, but its coverage number does not survive being looked at: it read
  69 %, and the two frames turned out to show different scenes. Refused, and left `not_run`.
- An in-place clip's root travels 0.0 cm, and the same call on a thigh returns 57.5 cm, so the zero
  is a real zero.
