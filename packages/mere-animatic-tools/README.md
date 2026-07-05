# mere-animatic-tools

Local companion tools for Animatic production workflows. The package follows the
`mere.run/plugin.v1` contract and is intended to be discovered by the
`relay-mere-run` node app.

The plugin is deliberately local-first: commands write `run.json` before work
starts, produce machine-readable JSON on stdout, write diagnostics to stderr,
and do not create paid resources.

## Commands

- `character-knockout`
- `reference-pack`
- `continuity-check`
- `shot-kit`
- `storyboard-repair`
- `edit-doctor`
- `actor-voice-kit`
- `location-plates`
- `style-lock`
- `delivery-prep`

Each command accepts:

```bash
mere-animatic-tools <command> \
  --request-json request.json \
  --output-dir out \
  --run-id animatic-001
```

Use `--dry-run` to write and print the planned manifest without executing.
