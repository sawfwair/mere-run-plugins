# Provider safety

Provider plugins coordinate resources in the user's own account. That does not
make resource creation harmless: a failed client can leave cost or production
state behind.

## Required lifecycle

Every provider plugin supports `doctor`, `plan`, `run`, `resume`, and `cleanup`.

## Before mutation

The plugin must:

1. validate inputs and provider readiness;
2. expose a dry-run or plan for paid work;
3. show the resource settings and exact work command;
4. write a durable `run.json` before creating a remote resource.

## After creation

Record the provider resource identity in the same manifest immediately. Update
status as upload, execution, artifact fetch, and cleanup progress.

## Cleanup default

Remote resources terminate by default. Keeping a resource requires an explicit
keep/debug choice from the user. Cleanup is idempotent and updates the manifest.

## Interruption recovery

If the client exits unexpectedly:

1. locate the existing run manifest;
2. inspect the recorded provider resource;
3. use `resume` to recover or inspect;
4. use `cleanup` against that manifest;
5. verify provider-side termination.

Do not start a replacement resource until the prior resource's state is known.

## Failure interpretation

A failed workflow and a failed cleanup are different conditions. Preserve both
in the manifest. Exit code `5` means the resource must be treated as potentially
live until provider-side verification proves otherwise.
