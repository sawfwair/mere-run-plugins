# Train a LoRA on RunPod

RunPod Runner executes canonical repository recipes on an ephemeral pod owned by
the user's RunPod account. It uploads the dataset, installs the selected
`mere.run` revision, fetches artifacts, and terminates the pod by default.

::: warning Paid resources
Always review the plan. A real run creates resources in your RunPod account.
Cleanup remains the default unless you explicitly request a keep/debug mode.
:::

## Prepare the dataset

The Klein style recipe expects paired image and caption files. You can use
[Dataset Tools](/plugins/dataset-tools) to create captions and a contact sheet.

## Check credentials and tools

```bash
mere.run plugin install mere-runpod
mere-runpod doctor
```

Keep provider credentials out of commands, manifests, logs, and source control.

## Create a plan

```bash
mere-runpod plan \
  --recipe klein-style-lora \
  --data ./dataset \
  --output ./runs/klein-lora \
  --run-id klein-lora-001
```

Confirm the dataset count, pod configuration, exact remote command, artifact
directory, and cleanup policy in `run.json` before execution.

## Execute and recover

Run the planned manifest using the command surface documented by
[`mere-runpod`](/plugins/runpod). If the client process is interrupted, use
`resume` with the existing manifest rather than starting an unrelated pod.

After artifacts are fetched, verify the artifact bundle and cleanup status. If a
run fails, call `cleanup` with the same manifest.

For recipe-specific inputs and outputs, see [Klein LoRA recipe](/recipes/klein-lora)
and [Klein reference evaluations](/recipes/klein-reference-evals).
