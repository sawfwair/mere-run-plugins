# Plugin Security

Official plugins may use external providers, but the user stays in control.

## Required Defaults

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

## Credential Handling

Provider tokens are read from environment variables, local env files, provider
CLIs, or OS keychains. The first implementation uses env variables because they
are easy to audit and CI-friendly.

For RunPod:

- `RUNPOD_API_KEY` authorizes the user's account using a bearer token header.
- Hugging Face tokens may be forwarded as `HF_TOKEN` /
  `HUGGING_FACE_HUB_TOKEN` when the recipe needs private or gated models.
- Manifest fields should record only whether a token was configured, never the
  value.

## Remote Resource State

Run manifests can include provider IDs such as pod IDs. Those are operational
identifiers, not secrets, but they should still be treated as user-account
metadata and not committed in examples unless synthetic.

## Build Packs

Provider plugins should prefer prebuilt, user-selected build packs over building
on paid GPU time. A build pack is an input artifact and should be hashed in the
run manifest.
