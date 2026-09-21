# Changelog

Format: one entry per released version. Dates are those of the development machine.
This project follows semantic versioning from 1.0.0 onwards; before that, the interface may change.

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
