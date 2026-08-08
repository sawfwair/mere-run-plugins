# mere-geo-tools

`mere-geo-tools` turns pinned Earth-observation sources into portable `mere.run`
graph inputs and keeps source, preprocessing, model, grid, and output provenance
attached to every result. It exposes four local Apple-silicon nodes:

| Node | Result |
| --- | --- |
| `geo.flood.segment` | TerraMind candidate-only flood mask and probability COGs |
| `geo.fire.segment` | TerraMind candidate-only fire mask and probability COGs |
| `geo.tessera.embed` | Per-pixel TESSERA v2 temporal embeddings |
| `geo.olmoearth.embed` | OlmoEarth v1.2 multisensor spatial embeddings |

The provider acquires exact STAC items, aligns them to a declared UTM grid,
applies the model family's documented radar and cloud-mask preprocessing, and
writes content-addressed bundles. Neural inference remains in core `mere.run`
through `geo flood`, `geo fire`, `geo tessera`, and `geo olmoearth`; the plugin
does not ship PyTorch model execution.

Sentinel sources default to the Microsoft Planetary Computer STAC API. OlmoEarth
Landsat inputs use the official USGS LandsatLook STAC API, collection
`landsat-c2l1`, and the STAC assets' official `s3://usgs-landsat` alternate
links. That bucket is requester-pays: an authenticated AWS account with billing
enabled is required, and vendor storage, processing, or egress charges may
apply. The adapter sets the requester-pays GDAL option, maps the assets into
OlmoEarth's required 11-band Level-1 DN order, and records the endpoint, item,
asset and access URLs, requester-pays status, and source contract in bundle
provenance:

```json
{
  "observed_at": "2025-08-21T18:55:42.454783Z",
  "LANDSAT": {
    "stac_endpoint": "https://landsatlook.usgs.gov/stac-server",
    "collection": "landsat-c2l1",
    "item": "LC08_L1TP_046027_20250821_20250828_02_T1",
    "source_contract": "landsat-oli-tirs-level1-dn-v1"
  }
}
```

Planetary Computer `landsat-c2-l2` is intentionally rejected: surface
reflectance Level-2 assets do not satisfy OlmoEarth's raw OLI/TIRS Level-1 DN
contract. Per-item `stac_endpoint` fields allow Sentinel and Landsat sources to
coexist in one OlmoEarth timeline.

```bash
mere-geo-tools manifest --json
mere-geo-tools doctor --json
mere-geo-tools prepare --recipe sources.json --output prepared-inputs --json
mere-geo-tools inspect prepared-inputs --json
mere-geo-tools graph catalog --json
mere-graph-conformance --provider mere-geo-tools --json
```

TESSERA and OlmoEarth default to core's hardware-aware model selection. A graph
can instead pin any managed tier, including the 2.064B TESSERA Teacher or
OlmoEarth Base. `batch_pixels` lets TESSERA use more unified memory on larger
machines; OlmoEarth exposes `patch_size`, `input_resolution`, and optional full
space-time tokens.

For development builds, set `MERE_RUN_EXECUTABLE`. TerraMind model roots can be
overridden with `MERE_TERRAMIND_FLOOD_MODEL` and
`MERE_TERRAMIND_FIRE_MODEL`; embedding nodes accept a managed model ID in their
graph arguments.

Flood and fire outputs are always `candidate-only`, and embeddings are
`derived-feature` artifacts rather than conclusions. OlmoEarth use also remains
subject to its upstream artifact license, including its restrictions on
military, defense, intelligence, human-surveillance, policing, and listed
extractive uses.
