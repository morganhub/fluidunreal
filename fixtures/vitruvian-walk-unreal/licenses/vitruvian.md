# Vitruvian body fixture — CC0-1.0

Authors: Sean Buckley and Olaf Delgado-Friedrichs; additional contributors are credited in
the upstream `config.yaml`. Source revision: `c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44`.

License declaration: https://github.com/Upliner/CharMorph-Vitruvian/blob/c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44/config.yaml
The declaration identifies the asset as `Vitruvian (CC0)` and `license: CC0`.
License text: https://creativecommons.org/publicdomain/zero/1.0/legalcode

Only `char.blend`, the `metarig` object from `rigs.blend`, and `weights/rigify.npz` are used.
No Mixamo object, motion or weights are imported. No CharMorph or Rigify source code is vendored.
Rigify is executed from the locked Blender installation to produce the derived rig.
Embedded text blocks, textures and particle hair are removed from the resulting neutral body fixture.
Input and output hashes are recorded in `fixtures/vitruvian/asset.json`.

## Face fixture (`fixtures/vitruvian-face/`)

Same authors, same repository, same revision, same CC0 declaration. Thirteen facial morphs from
`morphs/L3/` are turned into shape keys on the unchanged body fixture: eight visemes
(`p_b_m_21`, `s_z_15`, `ey_eh_uh_04`, `aa_02`, `ao_03`, `w_uw_07`, `f_v_18`, `l_14`) and five
expressions (`Happy`, `Sad`, `Angry`, `Scared`, `Eyes_Closed_Max`). Each `.npz` holds vertex indices
and deltas only; its SHA-256 is pinned in `scripts/generate_vitruvian_face_fixture.py` and recorded
in `fixtures/vitruvian-face/asset.json` together with the hash of the body fixture it derives from.
Download them from
`https://raw.githubusercontent.com/Upliner/CharMorph-Vitruvian/<revision>/morphs/L3/<name>.npz`
into `FLUIDBLEND_FIXTURE_CACHE/morphs-L3/`. The body fixture is read, never modified. The Rigify face
bones still carry no skin weights: the face is driven by these shape keys only.

Reproduce with `scripts/generate_vitruvian_fixture.py` inside Blender 5.2.2. Set
`FLUIDBLEND_FIXTURE_CACHE` to a directory containing the three hash-checked inputs; the weights
file must be named `weights-rigify.npz`. The generator refuses to overwrite an existing fixture.
Deformation review is separate from license verification and automated skin checks.
