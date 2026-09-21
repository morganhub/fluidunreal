# Frames looked at — 2026-09-21

Reviewer: the agent building lot 3, before `game.screenshot` was made available. Every frame below
was opened and described before its number was believed. Three of the first four numbers were
wrong, and only looking showed it.

## What was seen, in order

| Run | Share reported | What the frames showed | Verdict |
| --- | --- | --- | --- |
| 1, `take_high_res_screenshot` | 27.7 %, passed | First frame: the bed, the character mid-stride. Second frame ([kept](2026-09-21-wrong-second-frame.png)): another world, warmer light, and a second character standing in reference pose at the origin. The capture had shot the editor's world, not the PIE one. The difference box spanned the whole frame | wrong; the number was green |
| 2, `SceneCapture2D` in the PIE world | 1.19 %, passed | The same scene twice, the character and its shadow on the wall missing from the second. Right, but a hair above the 1 % threshold from 4.5 m | right, fragile |
| 3, camera at 3.2 m, fresh project | 15.5 %, passed | The character huge, cropped, seen from behind, a metre from the camera, under a black sky. The earlier runs had a sky and mountains | wrong; the number was green |
| 4, blank map, a PlayerStart, pawns taken out | 2.1 %, passed | [The character](2026-09-21-u08-ue-frame.png) in profile, facing +X toward the wall and the prop, feet on the floor with their shadow, knees bent mid-stride, arms hanging. [Without it](2026-09-21-u08-ue-frame-empty.png): the same wall, prop, floor and black sky, nothing else changed | right |

## What each wrong frame exposed

- **Run 1.** `take_high_res_screenshot` shoots whichever viewport it finds; on the second call it
  found the editor's. Lot 0 had seen the same 69 % and blamed destroying the default pawn. The
  frame now goes through a `SceneCapture2D` placed in the PIE world, and a difference box wider
  than 60 % of the frame is refused: a character is one region.
- **Run 3.** Two causes, both in the bed, both invisible to the fourteen headless checks.
  `new_level` saved `SmokeBed.umap` into the project and, on the next run, failed on the existing
  path, so the bed was built in whatever map was open: its sky came from the project's history.
  And without a PlayerStart, PIE spawned its default pawn at the origin inside the character's
  capsule, which threw the character from (0, 0) to (187, -191) before any input. The bed now
  builds in a blank map that is never saved, starts the default pawn behind the camera, and
  `character_moves` counts from where the walk starts and refuses more than 5 cm of sideways drift.
- **Before any of these runs**, lot 0's frame showed the character in profile to a camera looking
  along the walk: the mesh faced +Y and walked sideways, and it stood 88 cm above the floor, since
  a `Character` carries its mesh at the capsule's centre. The bed now measures the facing on the
  skeleton (foot to toe: 92°, turned by -90°) and `stands_on_floor` reads the lowest reference bone,
  not the capsule.

## What this does not settle

A frame from the kit's own bed, black sky, default material, one pose. It shows the character draws,
stands and faces the right way. It says nothing about how it will look in the user's game.
