# Computer Use

`mere-computer-use` runs a local vision and tool-calling mere.run model against one explicitly selected macOS window. It uses the separately installed, MIT-licensed [Cua Driver](https://github.com/trycua/cua/tree/main/libs/cua-driver) CLI for screenshots, accessibility snapshots, and input. No Cua code, perception package, weights, or AGPL dependency is bundled.

## Setup

On a current `mere.run`, `plugin install --yes` installs the package and runs its setup command to install the pinned, signed Cua Driver 0.28.2 app. `setup` previews the source and SHA-256; `setup --yes` also works directly on older CLIs. Pi is also required. Grant Accessibility and Screen Recording to `CuaDriver.app` through macOS:

```sh
mere.run plugin install mere-computer-use --yes
cua-driver permissions grant
mere-computer-use doctor
mere-computer-use windows
```

The plugin does not download models or accept their licenses. Muse Glimmer uses Apache-2.0 and retains Meta's usage policy; inspect its terms with `mere.run model info vision-chat-muse-glimmer-30b` before accepting them. On a current mere.run, `mere.run model pull vision-chat-muse-glimmer-30b --accept-model-license` records acceptance for an installed model without downloading it again. For Ornith Q4, pass `--model text-agent-ornith-35b-mlx-4bit` to `plan` and `doctor`. Its target and vision component are MIT; its optional MTP head is Apache-2.0. Ornith requires a mere.run build with Qwen-family image data URL support; the 0.50.0 API fails on screenshot requests. `doctor` checks the API preflight and any model receipt when no API is listening. It reports whether a run can start the API without requesting permissions or starting a server.

LFM2.5-VL BF16 with DSpark is an experimental opt-in choice: use `--model vision-chat-lfm25-3b-bf16`. It requires a mere.run build with native LFM2.5 tool-call parsing and history rendering. The model and its DSpark companion use the separate **LFM Open License v1.0**, which excludes commercial use by entities with at least USD 10 million in annual revenue. Review `mere.run model info vision-chat-lfm25-3b-bf16` before accepting its terms. An owned-server TextEdit trial read the document and stopped its API server. Two requested action trials observed the window but took no action; this model has not demonstrated a completed desktop action.

## Run

Choose the `pid` and `window_id` returned by `windows`. Planning is read-only and creates a local `run.json`:

```sh
mere-computer-use plan --pid 123 --window-id 456 --task "Find the total in this window" --output ./computer-run
mere-computer-use run ./computer-run/run.json
mere-computer-use resume ./computer-run/run.json
```

`run` reuses a compatible API already on the selected loopback port. Otherwise it preflights the installed Muse Glimmer, Ornith Q4, or LFM2.5-VL BF16 model, checks any usage-terms receipt, starts `mere.run api serve`, waits for image and tool capability discovery, then stops only the server it started when Pi exits. It never pulls a model or accepts terms. An incompatible or unauthorized server already on the port is left alone. Use `--api-start-timeout` to change the default 300-second startup limit. The run record identifies server ownership and writes server diagnostics to `api-server.log`.

The agent is restricted to that window, a maximum number of actions, and the bundled observe/click/type/key tools. Accessibility tokens are preferred; pixel actions require coordinates and the latest screenshot snapshot ID. Each action needs a fresh observation, and the final action needs a subsequent observation. Actions default to Cua Driver's background delivery. The run records action counts and a model report, but cannot independently certify task success. `verification: observation-only` means the model observed the window and took no action, regardless of its report. Screenshots are passed in memory to Pi and are not written to the run directory.

`--base-url` must be loopback. Set `MERE_COMPUTER_USE_API_KEY` for a protected local server. Automatic start supports Muse Glimmer, Ornith Q4, and LFM2.5-VL BF16; other models require a compatible API started separately. `cleanup` only marks the local run record and does not stop external servers or the Cua daemon.

## License boundary

This package is MIT. Setup installs the external MIT Cua Driver release only. Cua perception and SoM packages, model artifacts, and Ultralytics are excluded because their reviewed distribution has AGPL components. See [Cua's own licenses](https://github.com/trycua/cua) before installing optional components.
