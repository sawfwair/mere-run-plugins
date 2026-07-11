# VFX Tools Plugin

`mere-vfx-tools` is the sequence-oriented production layer for native
`mere.run` visual inference. The plugin owns shot plans, manifests, deterministic
matte processing, hashes, exports, review media, and cleanup records. Model
loading and inference remain in core `mere.run`.

## Current workflows

- `roto` calls `mere.run vision track`, combines object masks by frame, applies
  grow/choke/feather operations, and can encode ProRes 4444 alpha media.
- `matte-refine` processes an existing matte sequence without model inference.
- `track-export` writes generic JSON, CSV, After Effects JSON, and Blender JSON.
- `key` performs deterministic chroma keying and despill on stills or sequences.
- `shot-qc` detects corrupt frames, dimension changes, luminance jumps, and
  alpha-coverage chatter.
- `inbetween` calls native start/end-image `mere.run video generate`.
- `turntable` anchors native video generation to a source image and creates a
  canonical-view contact sheet.
- `character-sheet` calls native reference-guided image generation for a set of
  named views and assembles the results.
- `pose-sequence` extracts video frames, calls native `mere.run vision pose`
  for every frame, and exports per-frame artifacts, aggregate JSON/CSV, and
  After Effects/Blender-friendly 2D motion tracks. It does not fabricate 3D
  rotations or claim BVH-quality retargeting from 2D landmarks.
- `motion-pass` calls native `mere.run vision flow` for each adjacent frame
  pair and delivers standard Middlebury `.flo` files plus a hashed shot
  manifest for Nuke, Blender, and custom pipeline ingestion.
- `clean-plate` sends each source frame through native reference-guided image
  generation, then composites the candidate only through the supplied matte.
  This makes outside-mask pixels deterministic even though the current native
  edit models use whole-image conditioning rather than strict inpainting. The
  default padded bounding-region blend avoids silhouette-shaped ghost edges;
  `maskMode: "matte"` keeps a traditional matte blend. An approved candidate
  can be reused through `inputs.candidateImages` without rerunning inference.
  Candidate color is matched to the unselected source region by default before
  blending; set `colorMatch: false` to preserve the raw generated grade.
- `set-extension` generates a larger native reference-guided canvas, then puts
  the exact source plate back at a recorded offset. `edgeFeather: 0` guarantees
  the entire original region is byte-preserved; positive values trade a narrow
  boundary blend for a softer seam. The generated canvas is color-matched to
  the source region before compositing unless `colorMatch` is disabled.
- `restore` performs native reference-guided restoration at a requested scale,
  records source/output dimensions, and hashes each output. This is a
  generative restoration/upscale, not a claim of measurement-preserving detail
  or guaranteed identity retention. Every run also emits a deterministic
  Lanczos upscale baseline so artists can compare inferred detail against the
  source-only resample.
- `depth-normal` generates a clearly labeled non-metric monochrome depth proxy
  with native reference-guided inference, or accepts `inputs.depthImages` from
  a dedicated estimator. It derives deterministic image-space normals from the
  resulting depth gradient and never labels the proxy as camera-calibrated or
  metric geometry.
- `relight` applies a deterministic diffuse-light model to supplied normal maps
  and emits a separate RGBA shadow-catcher proxy projected from supplied
  mattes. Its manifest explicitly identifies both as 2.5D image-space passes,
  not physically reconstructed scene lighting. Shadow delivery is transparent
  RGBA and is accompanied by a light-background review render. The supplied
  subject matte is flattened and widened onto its foot plane; scale, angle,
  offset, blur, and opacity are adjustable.
- `image-to-3d` projects image or extracted video frames through supplied depth
  passes into colored PLY point clouds and OBJ surface meshes. The camera model,
  assumed near/far range, stride, and hashes are recorded. Output is explicitly
  2.5D, non-metric geometry with no invented back side or occluded surfaces.

Generative in-betweening is deliberately labeled as such. It synthesizes
plausible motion between keyframes; the separate motion pass records measured
dense optical flow and does not claim to synthesize missing frames.

## Request and lifecycle

```bash
mere-vfx-tools plan \
  --tool roto \
  --request-json ./request.json \
  --output-dir ./shot010 \
  --run-id shot010-roto-v001
mere-vfx-tools run ./shot010/run.json
mere-vfx-tools resume ./shot010/run.json
mere-vfx-tools cleanup ./shot010/run.json
```

All commands emit JSON on stdout and diagnostics on stderr. Runs are local,
create no paid resources, and record cleanup as a no-op.
