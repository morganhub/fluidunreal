# Test bed and frame

`game.smoke_test` plays the imported character headless and reports fourteen checks, all measured.
`game.screenshot` renders one frame of the same bed and the share of it the character covers. Both
are proven on 5.8.2 by U07 and U08, each with a negative control that fails on cue.

Examples: [request-game-smoke-test.json](../assets/request-game-smoke-test.json),
[request-game-screenshot.json](../assets/request-game-screenshot.json).

## The bed

Built **in code** at test time, in a blank map that is never saved: a floor, a wall at x = 400 cm,
a prop at x = 200 cm, a PlayerStart behind the camera, and a `Character` carrying the imported mesh.
Nothing is written into the Unreal project: no `.umap`, no `.uasset`.

How the mesh is placed, measured rather than assumed. A `Character` carries its mesh at the
capsule's centre and walks along +X. The mesh is lowered by the capsule's half height, and turned by
the facing measured on the skeleton, from a foot to its toe in the bundle's reference pose (92° on
the reference character, so -90°). Both numbers are in the report under `mesh_offset`.

Optional parameter of `game.smoke_test`: `clip_id`, the clip to play. Without it, the first clip
whose id says walk. A clip that is named and absent is not refused: the bed runs without it and
fails the animation checks by name, which is the negative control.

## The fourteen checks

The bed runs three phases, as a game would: stand, walk until the clip has looped, stand again.

| Check | What is measured |
| --- | --- |
| `map_loaded`, `character_spawned`, `skeleton_bone_count` | the PIE world, the character in it, the bundle's bone count (the importer's proxy root counted apart) |
| `walk_clip_found` | the clip that will be played, by name |
| `stands_on_floor` | the lowest reference bone at its bundle height above the floor, ± 3 cm. The feet, not the capsule |
| `idle_plays_nothing` | no clip assigned and the distance between the feet constant while standing. `is_playing` is reported and not used: on 5.8.2 it is true with no clip at all |
| `walk_plays_looping` | the player's position wraps at least once and it plays throughout |
| `walk_clip_moves_bones` | the distance between the two feet changes by more than 1 cm while walking. No displacement of the whole body can change it |
| `character_moves` | more than 10 cm along the input from where the walk started, and no more than 5 cm sideways |
| `wall_stops_it`, `reaches_pickup` | the character reaches the wall and is stopped there; it comes within 50 cm of the prop |
| `back_to_idle` | without input the character stops, the clip is stopped, the pose holds |
| `holds_prop` | the prop is attached to a grip socket, else the right hand bone (stated as a limit), and is still on it after the hand carried it more than 10 cm |
| `pickup_empty` | nothing is left where the prop was |

The report is written **before** the editor quits: a run that writes no report proves nothing, and
the kit treats it as an unknown state, not a failure.

## What each check got wrong first

Every one of these looked fine, and was measuring something else:

- `walk_clip_moves_bones`, three times. Lot 0 measured the actor walking. The next version read a
  local offset that a bone which only rotates keeps constant: 0.0 cm, a clip that seemed not to
  play. The next read every bone moving the same 10 cm: the reference walk carrying the whole body
  forward, since it is declared in place and travels 0.58 m per loop.
- `stands_on_floor` measured the capsule, which rested on the floor, while the mesh stood 88 cm
  above it. `character_moves` counted 187 cm that PIE's default pawn, spawned inside the capsule,
  threw the character before any input. The bed was built with `new_level`, which saved a map into
  the project and, next time, fell back to whatever map was open. None of this showed in the
  headless checks. The frame showed all of it.

## The frame

`game.screenshot` walks the character into the open, freezes it mid-stride, and shoots it from the
side at 3.2 m. Then it hides the character and shoots again from the same place: that second frame
is the negative control. `rendered_share` is the share of pixels that differ, the character and its
shadow, and must be at least 1 %. The report also gives the box that holds them.

Both frames go through a `SceneCapture2D` placed in the PIE world, with fixed exposure, exported
from its render target. `take_high_res_screenshot` shoots whichever viewport it finds: its second
frame showed the editor's world, and the share read a green, meaningless 27.7 %, as lot 0's 69 %
had. So a difference box wider than 60 % of the frame, or a share above 40 %, is refused rather than
reported: a character is one region, a changed view is everywhere. Without a usable GPU the engine
writes no frame, and the answer is `MISSING_DEPENDENCY`, not a pass.

**Open `ue-frame.png` and say you looked at it** before judging how the character looks. The report
says `looked_at: false` until someone does. Frames looked at while building this, and what each
wrong one showed, are in `docs/reviews/2026-09-21-frames-looked-at.md`.

## What this bed never proves

It is the kit's test bed, not your game. One character, one clip, a black sky and the default
material. Input is injected through `add_movement_input`, not through a keyboard. The smoke test
itself draws nothing; the frame is one pose from one camera. No frame rate and no GPU figure is ever
reported: only `wall_time_ms` and the machine.
