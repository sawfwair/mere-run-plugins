# Plugin security

Official plugins may use external providers, but the user stays in control.

## Required defaults

- Use user-provided credentials only.
- Do not store secrets in run manifests.
- Do not print secrets in logs.
- Create paid resources only from `run`, never from `manifest`, `doctor`, or
  `plan`.
- Give any provider helper that can create paid resources an explicit dry-run
  or plan mode.
- Default remote compute to termination or cleanup after artifact retrieval.
- Require an explicit keep/debug flag to leave paid resources running.
- Write a run manifest before resource creation.
- Make cleanup idempotent.

## Handle credentials

Provider tokens are read from environment variables, local env files, provider
CLIs, or operating-system keychains. The implementation uses environment
variables because tests can inspect that boundary without storing credentials.

For RunPod:

- `RUNPOD_API_KEY` authorizes the user's account using a bearer token header.
- Hugging Face tokens may be forwarded as `HF_TOKEN` /
  `HUGGING_FACE_HUB_TOKEN` when the recipe needs private or gated models.
- Manifest fields must record only whether a token was configured, never the
  value.

## Record remote resource state

Run manifests can include provider IDs such as pod IDs. Those are operational
identifiers, not secrets. Treat them as user-account metadata, and use
synthetic identifiers in committed examples.

## Prepare build packs

Provider plugins must use prebuilt, user-selected build packs unless their
documented workflow requires a remote build. Record the build pack's hash in
the run manifest.
