# mere-geo-tools

`mere-geo-tools` exposes typed, provenance-preserving geospatial nodes to
`mere.run`. Its first node, `geo.flood.segment`, runs the pinned
`ibm-esa-geospatial/TerraMind-base-Flood` checkpoint on an ImpactMesh-compatible
four-timestep bundle and emits candidate-only Cloud Optimized GeoTIFF artifacts.

The provider accepts a Metal-capable host so it can share a local graph with
native Metal nodes, but it does not execute this checkpoint through MPS.
TerraTorch's temporal UNet decoder remains an unsafe macOS MPS path; `auto`
selects CPU on macOS and an explicit `mps` request fails preflight.

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
