# mere-geo-tools

`mere-geo-tools` exposes typed, provenance-preserving geospatial nodes to
`mere.run`. Its first node, `geo.flood.segment`, runs the pinned
`ibm-esa-geospatial/TerraMind-base-Flood` checkpoint on an ImpactMesh-compatible
four-timestep bundle and emits candidate-only Cloud Optimized GeoTIFF artifacts.

Raster acquisition, normalization, tiling, reconstruction, and COG export stay
in the provider. The neural forward pass runs natively through
`mere.run geo flood` using Swift, MLX, and Apple Metal; it does not use the old
PyTorch CPU fallback. Set `MERE_RUN_EXECUTABLE` for a development build and
`MERE_TERRAMIND_FLOOD_MODEL` for an explicit converted model root.

```bash
mere-geo-tools manifest --json
mere-geo-tools doctor --json
mere-geo-tools prepare --recipe sources.json --output flood-inputs --json
mere-geo-tools graph catalog --json
mere-graph-conformance --provider mere-geo-tools --json
```

The input bundle records canonical STAC item and asset identities, the exact
four temporal roles, grid metadata, and SHA-256 hashes of every materialized
input. Output manifests pin the Hugging Face repository revision and checkpoint
hash and classify masks as `candidate-only`; downstream applications must not
promote them to evidence without independent validation.
