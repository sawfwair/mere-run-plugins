# Validation record

Validated pack version: `0.2.0`.

Pack SHA-256:
`8a3576c4a21e76c15afc264cc9c81820b0fede47b83cdfbce2a60605d3880cf0`.
This identity covers the manifest, case file, and scorer executable. Changes to
any of those files require a new validation record.

## Completed checks

- `mere.run eval pack validate benchmarks/ate-v0 --json`: valid; 240 cases,
  120 development and 120 held-out.
- `mere.run eval run benchmarks/ate-v0 --model base=text-chat-gemma4-turbo
  --dry-run --json`: plan created, zero completed model-result rows.
- `python3 -m unittest discover -s benchmarks/ate-v0 -p 'test_*.py'`:
  10 test methods passed. They exercise all 240 expected decisions, declared
  alternatives, incorrect mutations, strict JSON, numeric typing, fixture
  outcomes, alternate SQL states, source references, split separation,
  coverage counts, and the scorer subprocess protocol.
- Ruff and strict mypy passed for the scorer and tests.
- `./scripts/check.sh`: passed, including repository lint, types, unit tests,
  coverage, structural checks, contract validation, and installed-package smoke
  checks. The ATE tests and type checks are included in this gate.
- `git diff --check`: passed.

## Evidence limits

Fixture tests use authored expected decisions, not model predictions. These
checks preceded model inference. A separate [model baseline](BASELINE.md)
records the completed Ornith Q4 run and two Gemma runtime failures.
No real MCP server execution, live browser interaction, external mail, media
generation, or host process changes were performed by the fixtures. The 20
result-followup cases use supplied fixture observations; they do not run an
autonomous tool loop. Independent human review and model comparison remain
pending. Passing this record does not qualify a model for release.
