# Changelog

Format: one entry per released version. Dates are those of the development machine.
This project follows semantic versioning from 1.0.0 onwards; before that, the interface may change.

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
