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
- `shot-qc` accepts a supplied video or frame sequence and detects corrupt
  frames, dimension changes, luminance jumps, and alpha-coverage chatter.
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
- `depth-normal` calls native `mere.run vision geometry` for every source image
  by default. Its handoff records the exact core manifest plus metric depth EXR,
  depth preview, camera-space normal EXR/preview, inferred camera metadata, and
  colored PLY path with checksums. Before delivery, the plugin requires the MoGe
  core manifest to use `schemaVersion: 2`, re-hashes the requested image and
  matches its exact resolved path, byte count, and SHA-256, and validates the
  pinned model ID, repository, revision, license, native MLX backend, and runtime
  weights digest. Any schema, input-identity, or model-provenance mismatch fails
  the run instead of producing a handoff. `inputs.depthImages` remains an
  explicit fallback for artist-supplied grayscale depth; that path is labeled
  as normalized display values, non-metric, and camera-free, and only its
  normals are derived from an image-space depth gradient.
- `relight` applies a deterministic diffuse-light model and emits a separate
  RGBA shadow-catcher proxy projected from supplied mattes. Supply
  `inputs.normalMaps` to preserve an existing normal workflow, or omit it to
  have the plugin call `mere.run vision geometry` and consume its native normal
  previews. The relight and shadow catcher remain explicitly identified as
  2.5D image-space passes, not a physically reconstructed lighting solution.
  Shadow delivery includes a light-background review render; scale, angle,
  offset, blur, and opacity are adjustable.
- `video-depth` calls `mere.run vision depth-video` for a supplied video and
  preserves the native depth-sequence manifest, per-frame EXR/preview checksums,
  and source-FPS review MP4. The handoff records the actual checkpoint semantics:
  relative VDA output is not labeled metric, and the current depth-only model
  explicitly reports no confidence, camera intrinsics, or point cloud. The
  plugin accepts only the VDA `schemaVersion: 2` manifest, re-hashes the exact
  requested video bytes, and requires its resolved path, byte count, and SHA-256
  plus the pinned model ID, repository, revision, license, native MLX backend,
  runtime weights digest, result checkpoint digest, and relative/metric semantics
  to agree. A mismatch in any of those fields is a hard failure.
- `multiview-geometry` sends user-ordered `inputs.images` to native
  `mere.run vision geometry-multiview`. It preserves the DA3 scene manifest,
  relative depth/camera semantics, confidence-filtered colored PLY and GLB point
  clouds, camera JSON, and Nerfstudio-style transforms. The handoff is camera
  plus colored-point initialization for 3DGS training; it explicitly records
  `containsGaussianParameters: false` and does not call the GLB a mesh. Optional
  `inputs.cameras` enables the core pose-conditioned path without turning
  relative scene scale into a metric claim. The plugin accepts only the DA3
  schema-v2 scene manifest, re-hashes every requested source and requires its
  ordered path and byte count to match, checks that process resolution, reference
  view strategy, confidence percentile, and point cap equal the request, and
  validates native checkpoint model/revision/configuration/weights provenance.
  Delivery retains the ordered source identities and checkpoint record.
- `image-to-3d` defaults to native single-image TripoSR through
  `mere.run image reconstruct-3d`. The plugin confines the native run to its
  output directory, requires completed status, verifies the TripoSR run and
  mesh-manifest checksums, and rechecks every OBJ, PLY, and GLB byte count and
  SHA-256 before handing assets downstream. The result is an indexed object
  mesh in normalized object space, not metric scene geometry; its inferred
  unseen surfaces and native marching-tetrahedra topology boundary are retained
  in the handoff. The former grayscale-depth projection remains available only
  with `options.reconstructionMode: "supplied-depth-2.5d"`. That fallback is
  labeled non-native, non-metric, camera-local 2.5D geometry and never claims to
  reconstruct an occluded back side.
- `multiview-image-to-3d` is the reconstruction-only InstantMesh path. It
  requires an explicitly ordered array of exactly four or six user-supplied
  object views and calls `mere.run image reconstruct-3d-multiview`; it never
  generates missing views. The plugin confines the native output, verifies the
  authoritative InstantMesh run manifest and generic mesh manifest, then
  independently rechecks every OBJ, PLY, and GLB byte count and SHA-256. The
  handoff preserves ordered inputs, camera-rig semantics, normalized object
  units, checkpoint/conversion provenance, the native marching-tetrahedra
  topology caveat, and whether the pinned upstream empty-field repair was
  applied. Native `input.cameras` is mandatory even for the official rig: there
  must be one ordered matrix per view, each with exactly 16 finite values. When
  `inputs.cameras` is supplied, the native matrices must exactly equal that JSON
  document. The empty-field repair field must be boolean and agree exactly
  between the native extraction manifest and CLI payload. Zero123++, all
  view-generation weights, runtime Python/Pickle loading, and proprietary
  FlexiCubes are explicitly excluded. `options.model` may be the managed
  `image-3d-instantmesh-base` id or a verified converted safetensors package;
  a raw `.ckpt` is not a runtime model.

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

Native geometry request examples:

```json
{"inputs":{"images":"./plates"},"options":{"resolutionLevel":9}}
```

```json
{"inputs":{"video":"./shot010.mov"},"options":{"model":"vision-depth-vda-small"}}
```

```json
{
  "inputs": {
    "images": ["./views/front.png", "./views/left.png", "./views/back.png"],
    "cameras": "./known-cameras.json"
  },
  "options": {"processResolution": 504, "confidencePercentile": 40}
}
```

Native single-image object reconstruction:

```json
{
  "inputs": {"image": "./assets/chair.png"},
  "options": {"resolution": 256, "foregroundRatio": 0.85}
}
```

Native reconstruction-only InstantMesh from four ordered views:

```json
{
  "inputs": {
    "images": [
      "./turntable/front.png",
      "./turntable/left.png",
      "./turntable/back.png",
      "./turntable/right.png"
    ],
    "cameras": "./turntable/cameras.json"
  },
  "options": {
    "model": "./models/instantmesh-base-native",
    "resolution": 128,
    "noVertexColors": false
  }
}
```

Run it with:

```bash
mere-vfx-tools multiview-image-to-3d \
  --request-json ./instantmesh.json \
  --output-dir ./instantmesh-out
```

The optional camera document is `{"schemaVersion":1,"cameras":[...]}` with
one 16-number C2W/intrinsics vector per view. Without it, core uses the audited
official deterministic conditioning rig and records its matrices in the native
manifest. The plugin rejects missing, non-finite, reordered, or altered camera
values. This workflow accepts no prompt or single source image: artists must
supply all four or six licensed views.

Explicit legacy supplied-depth fallback:

```json
{
  "inputs": {"images": "./plates", "depthImages": "./depth"},
  "options": {"reconstructionMode": "supplied-depth-2.5d", "stride": 8}
}
```
