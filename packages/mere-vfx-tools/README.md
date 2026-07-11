# mere-vfx-tools

Local, shot-oriented VFX workflows built on the installed `mere.run` runtime.
The plugin owns plans, durable manifests, matte processing, exports, review
artifacts, hashes, and resumability. Native `mere.run` continues to own model
resolution and inference.

The initial commands are:

- `roto`: track prompted subjects, refine per-frame mattes, and optionally make
  a ProRes 4444 alpha movie.
- `matte-refine`: choke, grow, feather, and normalize an existing mask sequence.
- `track-export`: convert native tracking JSON to generic, After Effects, and
  Blender-friendly JSON plus CSV.
- `key`: chroma-key and despill a still or image sequence.
- `shot-qc`: report size changes, luminance jumps, alpha chatter, and corrupt
  frames.
- `inbetween`: generate motion between explicit start and end keyframes.
- `turntable`: generate an image-anchored orbit and a contact sheet.
- `character-sheet`: render canonical reference views from one character image.
- `pose-sequence`: extract body, hand, and face landmarks per frame and export
  generic JSON/CSV plus After Effects and Blender-friendly motion data.
- `motion-pass`: generate dense native optical flow between adjacent frames and
  export hashed Middlebury `.flo` passes with per-pair metadata.
- `clean-plate`: generate a removal candidate with native image inference, then
  composite it only inside supplied masks so unmasked source pixels stay exact.
- `set-extension`: outpaint a larger environment and composite the original
  source region back into the delivery at an explicit, recorded offset.
- `restore`: use native reference-guided image inference to restore and upscale
  stills or sequences, with requested/output dimensions and hashes recorded.
- `depth-normal`: create an explicitly non-metric depth proxy with native image
  inference (or accept supplied depth) and derive deterministic normal passes.
- `relight`: apply deterministic diffuse relighting from normal maps and export
  separate RGBA matte-projected shadow-catcher layers.
- `image-to-3d`: project image or video-frame depth passes into colored PLY
  point clouds and Blender-friendly OBJ surface meshes.

Every workflow accepts a request JSON document:

```json
{
  "inputs": {"video": "./shot.mov"},
  "options": {"prompts": ["actor", "sword"], "alphaVideo": true}
}
```

```bash
mere-vfx-tools plan --tool roto --request-json request.json --output-dir out
mere-vfx-tools run out/run.json
mere-vfx-tools roto --request-json request.json --output-dir out
mere-vfx-tools resume out/run.json
mere-vfx-tools cleanup out/run.json
```

All stdout is JSON. Diagnostics and child-process logs go to stderr. The plugin
does not create paid or remote resources.
