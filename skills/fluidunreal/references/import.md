# Import and audit

**Not available yet.** The engine backend is lot 2. `asset.import` and `asset.audit` answer
`UNSUPPORTED_CAPABILITY` and say so; `fluidunreal ops --all --json` lists them. What follows is the
contract they will honour, written from what lot 0 measured, so nothing here is a guess.

Examples: [request-asset-import.json](../assets/request-asset-import.json),
[request-asset-audit.json](../assets/request-asset-audit.json).

## What the import will do

Import into a staging path, read back what the editor actually created, compare it to the bundle,
and only then publish it as `Content/Fluid/<asset_id>/vNNN/`. A failed check publishes nothing and
cleans the staging away. `replace_existing` creates the next version; it never overwrites a
published one.

## What lot 0 measured, and what it costs

| Measured on 5.8.2 | Consequence |
| --- | --- |
| Interchange imports a skinned animated GLB in about five seconds | the import path is Interchange, not the legacy importer |
| bone names lose their dots: `DEF-big_toe.02.L` arrives as `DEF-big_toe_02_L` | every lookup maps `.` to `_`; comparing raw names silently misses every bone |
| the importer adds `<node>_ProxyTrueRootJoint` | 189 bones for the bundle's 188: the audit counts the bundle's, not the engine's total |
| `SkeletalMeshComponent.get_bone_location` does not exist | bones are read as sockets, with `get_socket_location` |
| the animation arrives one frame short | 47 frames against the bundle's 48: glTF sampling, stated and tolerated, not hidden |
| a `MaterialInstanceConstant` and a `PhysicsAsset` are created anyway | the pipeline knob that suppresses them has not been found; the kit will either accept them or find it, and will not claim otherwise |
| the engine logs an ensure in `InterchangeGltfAnimation.cpp` | non-fatal, recorded, unexplained |

## What the audit will measure

Each measurement carries its space, its unit and its tolerance, and `passed` is three-valued.

| Measurement | Against | Tolerance |
| --- | --- | --- |
| `scale_check` | each `reference_pose` bone, its height in centimetres against `head_m × 100` | 1 cm |
| `axis_check` | the highest reference bone really has the greatest Z | — |
| `anim_length` | frames and seconds against `frame_range` and `fps` | 1 frame |
| `root_motion_travel` | the **root** bone, bone 0, against `stride_m × repetitions × 100` | 2 cm |
| `socket_position` | each `grip_*` socket against `grips` | 0.1 cm |
| `bone_count` | the bundle's count, proxy root excluded | exact |

Proven on the real engine: the five reference bones of the fixture land within a millimetre, and
falsifying the reference pose by ten centimetres fails all five. The measurement is real.

**`technical_pass` is not `art_approved`.** It means every measurement that could be taken passed.
A measurement that could not be taken is `not_run`: listed, never counted as a pass, never counted
as a defect either.

## Why the root bone matters

Lot 0 read the first animation track and got `def-thigh_l`, a thigh that swings 57.5 cm during a
walk. Read as root travel, that would have called an in-place clip a travelling one. The root is
bone 0 of the skeleton, and the same call on that thigh still returns 57.5 cm, which is what makes
a root reading of 0.0 cm mean something.
