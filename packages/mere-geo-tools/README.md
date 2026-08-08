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
