# Frontier Handoff

This guide is for developers who want to pass a bounded chat or agent task to their signed-in Claude Code or Codex CLI. `mere-frontier-handoff` records a plan before invocation and stores the response in a private local `result.json` file. It handles no application-specific policy.

## Install and check readiness

Install Claude Code or Codex separately, and sign in with the account you intend to use. Then install the plugin:

```sh
mere.run plugin install mere-frontier-handoff --yes
mere-frontier-handoff doctor
```

`doctor` checks CLI installation and local sign-in status. It does not invoke a model. A handoff can use the signed-in CLI account and might incur charges under that account's terms.

## Plan a chat handoff

Save a request as `request.json`:

```json
{
  "contractVersion": "mere.run/frontier-handoff-request.v1",
  "backend": "codex",
  "mode": "chat",
  "prompt": "Compare three scheduling options. Return a JSON object with an options array.",
  "outputFormat": "json"
}
```

To use Claude Code, set `backend` to `claude`. Plan the request before running it:

```sh
mere-frontier-handoff plan --request ./request.json --output ./frontier-run
mere-frontier-handoff run ./frontier-run/run.json
mere-frontier-handoff resume ./frontier-run/run.json
```

`plan` creates `run.json` without invoking a model. `run` verifies that the request file has not changed, invokes the selected CLI, and writes `result.json`. The response can be text or a JSON object. A downstream application must validate the response against its own schema and policy before acting on it.

## Give an agent workspace access

Set `mode` to `agent` and provide an existing `workspace` directory. Agent access defaults to `read-only`. To allow file edits, set `access` to `workspace-write` explicitly:

```json
{
  "contractVersion": "mere.run/frontier-handoff-request.v1",
  "backend": "codex",
  "mode": "agent",
  "prompt": "Update the README example and explain the change.",
  "outputFormat": "text",
  "workspace": "/absolute/path/to/workspace",
  "access": "workspace-write"
}
```

The plugin uses the CLI's access controls. Codex receives a read-only or workspace-write sandbox. Claude Code receives a restricted tool list; write access allows its file-editing tools but does not enable Bash. Check the CLI's own settings, hooks, and workspace instructions before granting agent access.

## Inspect the records

`run.json` records the backend, request hash, access level, status, and result path. It does not contain the prompt or CLI credentials. `result.json` contains the response and hashes that bind it to the planned request. Both files are local and created with owner-only permissions. Treat the request file, workspace contents, and result as potentially sensitive: the selected frontier CLI sends task context to its provider.

The receipt records the requested model and CLI version. It does not attest to the provider's resolved model weights or deterministic sampling.

`resume` inspects a run and verifies a completed result. It never reissues a model call after an interruption. `cleanup` records that no remote resource was created by this plugin; it retains the local request and result for review. Start a new plan to retry a failed call.

The [request](/reference/contracts), [run](/reference/contracts), and [result](/reference/contracts) schemas define the machine-readable boundary.
