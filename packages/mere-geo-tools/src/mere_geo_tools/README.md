# mere_geo_tools Source Map

`mere_geo_tools` is the provenance-preserving geospatial graph provider for
`mere.run`. Its initial node prepares and executes TerraMind flood segmentation
as a candidate-only analysis lane.

Entry points:

- `cli.py`: operator commands for manifests, diagnostics, bundle preparation,
  direct inspection, comparison, and graph-provider execution.
- `provider.py`: the `mere.graph-provider/v1` catalog, preflight, and execute
  boundary for `geo.flood.segment`.
- `prepare.py`: schema-checked Planetary Computer discovery, reprojection,
  temporal stacking, and content-addressed input bundle creation.
- `runtime.py`: normalization, deterministic tiling, native `mere.run geo flood`
  handoff, COG/preview writing, and candidate comparison metrics.
- `bundle.py`: input-bundle parsing, ordering, path containment, and digest
  verification.
- `constants.py`: pinned model, checkpoint, modality, and normalization
  contracts.

Important boundaries:

- Keep provider stdout JSON-only.
- Treat STAC responses and bundles as untrusted until validated.
- Preserve canonical source identities and SHA-256 provenance in every output.
- Keep flood artifacts classified as `candidate-only`; this provider does not
  author authoritative findings or ranked analyst briefs.
- Keep neural inference native: the provider may prepare and reconstruct arrays,
  but the TerraMind forward pass belongs to Swift/MLX on Apple Metal.
