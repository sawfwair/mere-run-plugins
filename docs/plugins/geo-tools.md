# Geospatial Tools

`mere-geo-tools` exposes typed, provenance-preserving geospatial nodes to
portable `mere.run` graphs. Its first node, `geo.flood.segment`, runs the pinned
`ibm-esa-geospatial/TerraMind-base-Flood` checkpoint against a canonical
four-timestep Sentinel-1 and Sentinel-2 bundle.

## Install and inspect

```bash
mere.run plugin install mere-geo-tools
mere-geo-tools manifest --json
mere-geo-tools doctor --json
mere-geo-tools graph catalog --json
mere-graph-conformance --provider mere-geo-tools --json
```

## Prepare pinned inputs

Materialize a source recipe before running the graph node:

```bash
mere-geo-tools prepare \
  --recipe ./terramind-flood-sources.json \
  --output ./flood-inputs \
  --json
```

The prepared bundle records canonical STAC item and asset identities, temporal
roles, grid metadata, and SHA-256 hashes for every materialized input. The graph
output manifest pins the Hugging Face repository revision and model checkpoint
hash.

## Execution boundary

The provider can share a local graph with native Metal nodes, but TerraTorch's
temporal UNet decoder does not execute through MPS. `auto` selects CPU on macOS;
an explicit `mps` request fails preflight. Relay GPU execution requires the
target fleet to have the same `mere-geo-tools` provider installed.

## Evidence boundary

Flood masks and probabilities are emitted as Cloud Optimized GeoTIFFs and are
always labeled `candidate-only`. Downstream analyst workflows must compare them
with independent observations before promoting any area to evidence or a final
finding.
