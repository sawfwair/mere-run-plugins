# Graph providers

Graph providers extend portable Mere workflows without putting private tools,
hosted services, or domain-specific dependencies into the public `mere.run`
runtime. They expose a typed catalog and execute one invocation through the
same process contract on local, SSH, and Relay workers.

## Start a provider

```bash
mere-graph-provider-init ./mere-example-tools \
  --provider-id mere-example-tools \
  --node-kind example.write
```

The destination must be new or empty. The starter includes a typed catalog,
structured preflight, confined output resolution, NDJSON events, a final
`node_result`, and a catalog test. Replace the example implementation without
weakening those boundaries.

## Prove the contract

Catalog-only validation is fast and side-effect free:

```bash
mere-graph-conformance --provider mere-example-tools --json
```

Add a deterministic fixture to validate the complete provider lifecycle:

```bash
mere-graph-conformance \
  --provider mere-example-tools \
  --invocation ./fixtures/write.invocation.json \
  --run-dir ./fixture-run \
  --execute \
  --json
```

The harness verifies catalog types, preflight shape, contiguous event
sequences, exactly one final `node_result`, declared output names, confined
relative paths, and the existence of every declared artifact. Keep provider
credentials out of fixtures and use named secret references for live tests.

## Comfy compatibility

Use `graph comfy inspect` before import. The report identifies every source
node, whether it is mapped, replaced by a native graph output, unsupported, or
requires an API-format export. Import remains conservative: unsupported custom
nodes block conversion instead of becoming arbitrary executable commands.
