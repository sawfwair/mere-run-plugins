# Identity Tools plugin

`mere-identity-tools` is the product-neutral graph-provider facade for local
identity work. It advertises curriculum generation, text-LoRA training,
four-arm evaluation, and aggregate report compilation without exposing the
calling application or local artifact paths.

## Install

```bash
mere.run plugin install mere-identity-tools --yes
```

Identity Tools deliberately separates the public Relay contract from the local
implementation. Configure an executable backend before running work:

```bash
export MERE_IDENTITY_BACKEND=/absolute/path/to/identity-tools-backend
mere-identity-tools doctor --json
```

Observed sources can be staged through the same product-neutral facade. The
backend retains the content locally and registers only custody metadata with
the configured identity registry:

```sh
mere-identity-tools stage ./source.jsonl \
  --pairing-code "$IDENTITY_PAIRING_CODE" \
  --registry-url https://identity.example \
  --device-id "$MERE_RUN_DEVICE_ID" \
  --json
```

The backend is executed directly, without a shell. It must implement the
`mere.run/plugin-graph-provider.v1` preflight and event-stream contracts.

## Use public graph nodes

- `identity.curriculum.generate`
- `identity.text-lora.train`
- `identity.evaluate.four-arm`
- `identity.dossier.compile`

The public catalog and Relay fleet contain only provider versions, node kinds,
model capabilities, device identifiers, and content digests. Sources, datasets,
weights, checkpoints, private examples, logs, credentials, and filesystem paths
remain under the configured backend's local custody.
