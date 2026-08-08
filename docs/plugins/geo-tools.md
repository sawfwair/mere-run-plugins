# Geospatial Tools

`mere-geo-tools` is the portable workflow layer around core `mere.run` geo
models. It prepares exact source imagery, preserves raster and preprocessing
provenance, invokes native Swift/MLX inference, and georeferences the result.

| Node | Inputs | Outputs |
| --- | --- | --- |
| `geo.flood.segment` | Four S2 L2A, S1 RTC, and DEM timesteps | Candidate mask, probability COG, preview, manifest |
| `geo.fire.segment` | Four S2 L2A, S1 RTC, and DEM timesteps | Candidate mask, probability COG, preview, manifest |
| `geo.tessera.embed` | Annual S2 plus ascending or descending S1 histories | Per-pixel embedding safetensors and manifest |
| `geo.olmoearth.embed` | One to twelve S2, S1, or Landsat observations | Per-modality spatial embedding safetensors and manifest |

## Install and inspect

```bash
mere.run plugin install mere-geo-tools
mere-geo-tools manifest --json
mere-geo-tools doctor --json
mere-geo-tools graph catalog --json
mere-graph-conformance --provider mere-geo-tools --json
```

## Prepare pinned inputs

All recipes declare WGS84 bounds and the target WGS84 UTM grid. Sources are
exact STAC collection/item pairs; preparation never silently searches for a
different scene.

Hazard recipes use four ordered roles and differ only in their typed kind:

```json
{
  "kind": "mere.geo/terramind-fire-source-recipe",
  "version": 1,
  "sample_id": "fire-review-001",
  "target": {"aoi": [-123.3, 49.1, -123.2, 49.2], "crs": "EPSG:32610"},
  "timesteps": [
    {"role": "pre_month", "S2L2A": {"collection": "sentinel-2-l2a", "item": "..."}, "S1RTC": {"collection": "sentinel-1-rtc", "item": "..."}},
    {"role": "pre_event", "S2L2A": {"collection": "sentinel-2-l2a", "item": "..."}, "S1RTC": {"collection": "sentinel-1-rtc", "item": "..."}},
    {"role": "event", "S2L2A": {"collection": "sentinel-2-l2a", "item": "..."}, "S1RTC": {"collection": "sentinel-1-rtc", "item": "..."}},
    {"role": "post_event", "S2L2A": {"collection": "sentinel-2-l2a", "item": "..."}, "S1RTC": {"collection": "sentinel-1-rtc", "item": "..."}}
  ],
  "DEM": {"collection": "cop-dem-glo-30", "item": "..."}
}
```

TESSERA keeps independent S2, ascending S1, and descending S1 timelines:

```json
{
  "kind": "mere.geo/tessera-v2-source-recipe",
  "version": 1,
  "sample_id": "annual-context-001",
  "target": {"aoi": [-123.3, 49.1, -123.2, 49.2], "crs": "EPSG:32610"},
  "observations": {
    "S2": [{"collection": "sentinel-2-l2a", "item": "..."}],
    "S1_ASC": [{"collection": "sentinel-1-rtc", "item": "..."}],
    "S1_DESC": [{"collection": "sentinel-1-rtc", "item": "..."}]
  }
}
```

OlmoEarth uses a shared timeline; every timestep must contain the same selected
modalities:

```json
{
  "kind": "mere.geo/olmoearth-v1.2-source-recipe",
  "version": 1,
  "sample_id": "multisensor-context-001",
  "target": {"aoi": [-123.3, 49.1, -123.2, 49.2], "crs": "EPSG:32610"},
  "timesteps": [
    {
      "observed_at": "2026-06-15T10:00:00Z",
      "S2L2A": {"collection": "sentinel-2-l2a", "item": "..."},
      "S1RTC": {"collection": "sentinel-1-rtc", "item": "..."}
    }
  ]
}
```

Prepare and inspect any recipe with the same commands:

```bash
mere-geo-tools prepare --recipe ./sources.json --output ./prepared-inputs --json
mere-geo-tools inspect ./prepared-inputs --json
```

Each bundle records source item/asset identities, acquisition times, canonical
band order, cloud-mask or radar conversion policy, grid metadata, and SHA-256
hashes for every materialized input.

## Hardware scaling

Leaving `model` as `auto` delegates tier selection to core `mere.run` based on
unified memory and installed checkpoints. Graphs may explicitly select every
managed tier, including TESSERA Teacher and OlmoEarth Base. TESSERA's
`batch_pixels` can be increased on larger machines. OlmoEarth exposes
`patch_size`, `input_resolution`, and `include_tokens`; smaller patches and full
tokens preserve more detail and consume more memory.

The neural commands are `mere.run geo flood`, `geo fire`, `geo tessera`, and
`geo olmoearth`. There is no PyTorch fallback in this provider.

## Evidence and license boundaries

Flood and fire masks remain `candidate-only` until independently corroborated
and reviewed. TESSERA and OlmoEarth outputs are `derived-feature` artifacts, not
findings. OlmoEarth use remains subject to its upstream artifact license and its
restrictions on military, defense, intelligence, human-surveillance, policing,
and listed extractive uses.
