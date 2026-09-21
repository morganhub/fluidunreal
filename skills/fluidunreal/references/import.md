# Import and audit

**Available**, proven against Unreal Engine 5.8.2 by scenarios U05 and U06.

Examples: [request-asset-import.json](../assets/request-asset-import.json),
[request-asset-audit.json](../assets/request-asset-audit.json).

## What the import does

Import into a staging path, read back what the editor actually created, compare it to the bundle,
and only then publish it as `Content/Fluid/<asset_id>/vNNN/`. A failed check publishes nothing and
cleans the staging away, from the asset registry **and** from disk: `delete_directory` empties the
registry but leaves the folder behind. `replace_existing` creates the next version; it never
overwrites a published one.

The published version writes `FLUID_CONTENT.json`, every file with its hash, and the revision
points at that. A `.uasset` edited by hand in the editor is caught the next time the kit looks.

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

## What the audit measures

Each measurement carries its space, its unit and its tolerance, and `passed` is three-valued.

| Measurement | Against | Tolerance |
| --- | --- | --- |
| `scale_check` | each `reference_pose` bone, its height in centimetres against `head_m × 100` | 1 cm |
| `axis_check` | the highest reference bone really has the greatest Z | — |
| `anim_length` | frames and seconds against `frame_range` and `fps` | 1 frame |
| `root_motion_travel` | the bones hanging from the importer's proxy root, median of their horizontal travel, against `stride_m × repetitions × 100`, or zero for a clip declared in place | 2 cm (1 cm in place) |
| `socket_position` | each `grip_*` socket against `grips` | 0.1 cm |
| `bone_count` | the bundle's count, proxy root excluded | exact |

Proven on the real engine: the five reference bones of the fixture land within a millimetre, and
falsifying the reference pose by ten centimetres fails all five. The measurement is real.

**`technical_pass` is not `art_approved`.** It means every measurement that could be taken passed.
A measurement that could not be taken is `not_run`: listed, never counted as a pass, never counted
as a defect either.

## Why root motion is not read on bone 0

Bone 0 of an imported skeleton is `<node>_ProxyTrueRootJoint`, a joint the importer adds and no clip
animates. Lot 0 read it, got 0.0 cm, and called the reference walk in place. The control meant to
catch a wrong bone was a thigh that read 57.5 cm, taken for a swing. A thigh's head does not swing:
it goes where the pelvis goes. The 57.5 cm was the travel.

A deform-only export has no single root bone. The reference fixture's 188 bones hang from the proxy
in 75 separate chains, and every one of them carries the travel. The audit reads all of them and
takes the median of their horizontal travel from the first frame to the last. Its control is the
largest excursion of any of them within the clip, which a reader returning constants reads as zero.

On the reference fixture it reads 57.5 cm for a clip declared in place, and fails it. That is a real
defect of the fixture, confirmed from the GLB without Unreal (0.59 m over 48 frames): fluidblend
0.6.0 declares every baked clip in place, whatever it does. Declared as the 0.6 m walk it was made
from, the same clip passes, and declared as a 0.5 m walk it fails: those are the controls.

A declared stride covers the whole clip, and the travel is read from the first frame to the last:
one frame short of a loop, and Unreal samples one frame fewer than the bundle declares. The stride
is scaled to the span read (46 frames of 48 on the reference walk). Without that, a correct 0.6 m
walk reads 57.5 cm against 60 and fails by 2.5 cm.
