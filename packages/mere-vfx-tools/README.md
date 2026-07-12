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
- `depth-normal`: call native `mere.run vision geometry` for metric depth,
  camera-space normals, inferred camera metadata, and a colored point cloud.
  Native MoGe handoff requires a core `schemaVersion: 2` manifest whose resolved
  input path, byte count, and SHA-256 exactly match the requested image, and
  whose model ID, repository, revision, license, native MLX backend, and runtime
  weights digest match the plugin's pins. Any mismatch rejects the run.
  Artist-supplied grayscale depth remains available as an explicitly non-metric,
  camera-free fallback.
- `relight`: apply deterministic diffuse relighting from supplied normal maps,
  or solve missing normals through native geometry, and export separate RGBA
  matte-projected shadow-catcher layers.
- `video-depth`: call native `mere.run vision depth-video` and preserve its
  temporal depth manifest, EXR/preview sequence, semantics, and review MP4. The
  VDA handoff likewise requires `schemaVersion: 2`, exact requested-video path,
  byte count, and SHA-256 identity, pinned model provenance and native backend,
  an accepted runtime weights digest, matching result checkpoint digest, and
  model-appropriate relative or metric semantics. Any mismatch rejects the run.
- `multiview-geometry`: solve user-ordered views through native DA3 geometry and
  hand off relative cameras, colored PLY/GLB points, and transforms for 3DGS
  initialization. The plugin requires the DA3 schema-v2 manifest, verifies each
  source path/byte count/SHA-256 plus the requested processing controls and
  checkpoint provenance, and carries those identities into delivery. It does
  not claim a mesh, metric scale, or Gaussian parameters.
- `image-to-3d`: run native single-image TripoSR and verify its run manifest,
  mesh manifest, and hashed OBJ/PLY/GLB assets. The prior supplied-depth 2.5D
  projection is retained only as the explicit `supplied-depth-2.5d` fallback.
- `multiview-image-to-3d`: send exactly four or six explicitly ordered,
  user-supplied views to native reconstruction-only InstantMesh and verify its
  authoritative run manifest, generic mesh manifest, camera rig, normalized
  units, provenance, and every OBJ/PLY/GLB hash. Every native camera matrix must
  contain exactly 16 finite values, supplied matrices must match the artist's
  camera document exactly, and the upstream empty-field repair disclosure must
  agree between core payload and manifest. It does not generate views or include
  Zero123++, runtime Python/Pickle, or proprietary FlexiCubes; native marching
  tetrahedra does not claim upstream FlexiCubes topology parity.

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
