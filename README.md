# fluidunreal

**Unreal Engine 5 imports, with proof.** The engine-side twin of
[fluidblend](https://github.com/morganhub/fluidblend): it takes a hand-off bundle (a GLB plus a
hashed, typed manifest), imports it into an Unreal project through the editor on the command line,
**measures** what the engine really wrote, plays it in its own test bed, renders one frame, and
publishes its evidence. Windows 11 only.

Status: **lot 0 done, on Unreal Engine 5.8.2.** Four of the five feasibility proofs pass against the
real engine; the fifth, the off-screen frame, renders but its coverage measurement is refused as
untrustworthy and stays `not_run`. Raw output in [docs/lot0/](docs/lot0/), findings in
[docs/compatibility-matrix.md](docs/compatibility-matrix.md). No line of `src/` is written yet:
lot 1 starts from these measurements.

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
