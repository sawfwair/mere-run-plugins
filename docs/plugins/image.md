# Reviewed Image

On Apple Silicon, install the signed `mere-image` plugin with mere.run 0.79.0 or later.
Review NVIDIA’s non-commercial research and evaluation terms before accepting the Q8 download.

```bash
mere.run plugin install mere-image --yes
mere.run model pull image-nemotron-labs-30b-a3b-q8 --accept-model-license
mere.run model pull vision-chat-inkling-2-mini
mere-image "A red enamel kettle on a blue camping stove"
```

The plugin uses the installed native runtime and managed model IDs. It needs no Python setup.
For a custom installation, save overrides in `~/.config/mere-image-compose/defaults.json`
(or under `$XDG_CONFIG_HOME`).
Each field is optional. The runtime field takes an executable path.

```json
{
  "runtime": "/path/to/mere.run",
  "model": "/path/to/nemotron-q8",
  "reviewer": "vision-chat-inkling-2-mini"
}
```

Use `mere-image-compose generate-reviewed --help` to see all options.
Explicit flags and the existing environment overrides take precedence over the saved settings.

Inkling sees the creative brief and the first render. If it accepts the image, generation ends.
If it requests a repair, Nemotron draws one new image from Inkling's standalone prompt.
Two fresh Inkling sessions compare the images in opposite orders. Each sees the original
brief and labeled images. Both must prefer the redraw with self-reported confidence of
at least 0.75 to replace the original. Ties, split votes, and lower confidence keep the original.

The command prints JSON with the path to `selected.png` and the run directory under `runs/`.
The directory contains the renders, prompts, replies, comparison sheets, and `result.json`.
Set `--output-dir` to choose a new directory, `--seed` for the first render, or
`--model` and `--reviewer` to override model IDs or paths. Use `MERE_RUN_EXECUTABLE`
to select a native binary outside your PATH. An incomplete image block gets up to two more
attempts with successive seeds. Other inference errors and invalid reviews exit with a
failed record. A successfully rendered original remains available.
