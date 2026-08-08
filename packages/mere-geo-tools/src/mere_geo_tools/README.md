# mere_geo_tools Source Map

`mere_geo_tools` owns the acquisition and provenance side of portable
humanitarian geo workflows. Core `mere.run` owns the neural forwards and
hardware-aware model selection.

Entry points:

- `cli.py`: machine-readable manifest, doctor, prepare, inspect, comparison,
  and graph-provider commands.
- `provider.py`: catalogs, preflights, and executes `geo.flood.segment`,
  `geo.fire.segment`, `geo.tessera.embed`, and `geo.olmoearth.embed`.
- `prepare.py`: shared four-timestep TerraMind Flood/Fire STAC preparation.
- `prepare_embeddings.py`: TESSERA temporal and OlmoEarth multisensor STAC
  preparation, band ordering, cloud masks, timestamps, and radar conversion.
- `runtime.py`: TerraMind normalization, deterministic tiling, native hazard
  handoff, COG writing, and review previews.
- `embedding_runtime.py`: TESSERA cloud-valid pixel batching and OlmoEarth
  spatial handoffs, then georeferenced safetensors manifests.
- `bundle.py`: typed bundle parsing, modality validation, path containment, and
  artifact digest verification.
- `constants.py`: immutable upstream revisions, native weight hashes, band
  orders, and hazard normalization contracts.

Important boundaries:

- Keep stdout JSON-only and diagnostics on stderr.
- Treat STAC responses and prepared bundles as untrusted until validated.
- Preserve canonical source identities and SHA-256 provenance in every output.
- Keep hazard artifacts `candidate-only` and embeddings `derived-feature`.
- Keep neural inference native; preparation and reconstruction live here, but
  model execution belongs to Swift/MLX on Apple Metal.
- Preserve OlmoEarth's upstream license notice in its output manifest.
