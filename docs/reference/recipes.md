# Recipes

Recipes define canonical, reviewable workflows independently of a particular
provider implementation.

## Recipe types

- `recipe.v1`: executable workflow inputs, commands, outputs, provider
  expectations, and safety defaults.
- `eval-recipe.v1`: evaluation inputs, protocol, and expected reporting.

## Bundled recipe documentation

- [Klein style LoRA](/recipes/klein-lora)
- [Klein reference evaluations](/recipes/klein-reference-evals)

Machine-readable recipe JSON lives under `recipes/` in the repository and is
validated by the repository gate.

## Provider relationship

RunPod Runner consumes canonical recipes but owns provider orchestration:
resource creation, upload, remote execution, artifact fetch, resume, and cleanup.
The recipe does not grant a provider permission to weaken cleanup defaults or
print secrets.

## Authoring rule

A recipe should make cost and execution legible before a run. Include explicit
inputs, exact commands, expected artifact locations, and cleanup expectations.
Update docs and tests with every recipe contract change.
