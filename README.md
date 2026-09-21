# fluidunreal

**Unreal Engine 5 imports, with proof.** The engine-side twin of
[fluidblend](https://github.com/morganhub/fluidblend): it takes a hand-off bundle (a GLB plus a
hashed, typed manifest), imports it into an Unreal project through the editor on the command line,
**measures** what the engine really wrote, plays it in its own test bed, renders one frame, and
publishes its evidence. Windows 11 only.

Status: **lot 1, host side.** What works today, proven against Unreal Engine 5.8.2: diagnose the
machine and lock the series, create a project with its own test bed, accept a hand-off bundle,
wrap a third-party GLB into one, re-check an accepted bundle. Everything that starts the editor is
declared unavailable and names the lot it lands in.

Acceptance scenarios U01 to U04 pass. Lot 0's five feasibility proofs are recorded in
[docs/lot0/](docs/lot0/), with their findings in
[docs/compatibility-matrix.md](docs/compatibility-matrix.md).

## What works today

```powershell
fluidunreal doctor --project . --json          # what this machine can actually do
fluidunreal init --path "D:\Projects\My Game" --project-id my-game
fluidunreal run --project . --operation requests/bundle-accept.json
fluidunreal inspect --project . --json
```

`bundle.accept` verifies every sha256 the manifest declares, the licence, and the producer's
version before copying anything in. A flipped byte, a missing file, an emptied licence, a producer
older than the contract, or the same identifier with different contents are each refused with their
own reason. `bundle.wrap` turns a third-party GLB into a bundle, describing only what the file
really says, and states that a wrapped GLB has no reference pose so the scale check after import
will be `not_run`.

## What it will do

- **Accept a bundle** (`bundle.accept`) published by fluidblend, or wrap a third-party GLB
  (`bundle.wrap`) — licence required either way.
- **Import** (`asset.import`) through the editor on the command line, into a staging folder, then
  publish it as a new version only once every check on what the importer created has passed.
- **Audit** (`asset.audit`) with measurements that carry their space, unit and tolerance: scale
  against the bundle's reference pose, animation length, root motion travel, socket positions, bone
  count. A measurement that cannot be taken is `not_run`, never a pass.
- **Play** (`game.smoke_test`) a code-built test bed in headless Play-In-Editor: 14 checks, a JSON
  report written before the editor quits.
- **Show** (`game.screenshot`) one off-screen frame and the share of it the character covers, with a
  frame without the character as the negative control.
- **Hand back** (`handoff.request`) a typed fluidblend request when the fix belongs in Blender. This
  kit never edits a `.blend`.

## What it will not do

Build your game, generate gameplay Blueprints, C++ or Widgets. Retarget to the UE5 Mannequin.
Package or cook. Drive an open editor live. Touch MetaHuman, Nanite, Lumen, Chaos or Niagara. Claim
a frame rate or a GPU figure. Run on macOS or Linux. Each of those is refused explicitly, with the
reason, rather than approximated.

## How the two kits talk

Through files: hashed, versioned, one-directional. Each kit is the only writer of its own project
root. fluidblend publishes `handoff-bundle.json`; fluidunreal accepts it, copies it in and verifies
every sha256. When something needs fixing in Blender, fluidunreal writes a fluidblend request and
tells the agent to hand over. There is no live channel between them, and neither writes into the
other's root.

## Lot 0

```powershell
# Needs Unreal Engine 5 installed, and a bundle exported by fluidblend 0.6.0.
pwsh -File scripts/lot0/run.ps1 -Bundle "D:\studio\exports\shot010\<operation_id>"
```

Five proofs: the engine and its Python (P1), an Interchange import of a skinned animated GLB with the
scale measured (P2), a headless PIE session driven from Python (P3), an off-screen frame with its
negative control (P4), and root motion travel against the bundle's stride (P5). Each writes a JSON
report and keeps the engine log beside it. A proof that cannot run is recorded as `not_run` with its
reason. See [docs/compatibility-matrix.md](docs/compatibility-matrix.md) and
[docs/sources.md](docs/sources.md).

## Licence

MIT. See [LICENSE](LICENSE).
