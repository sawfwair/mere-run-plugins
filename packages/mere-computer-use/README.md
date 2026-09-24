# Computer Use

`mere-computer-use` runs a local vision and tool-calling mere.run model against one explicitly selected macOS window. It uses the separately installed, MIT-licensed [Cua Driver](https://github.com/trycua/cua/tree/main/libs/cua-driver) CLI for screenshots, accessibility snapshots, and input. No Cua code, perception package, weights, or AGPL dependency is bundled.

## Setup

Install the package with `mere.run plugin install mere-computer-use --yes`, plus Cua Driver 0.28.2 or later and Pi. Start Cua Driver through `CuaDriver.app` so macOS can grant Accessibility and Screen Recording to the app. Start a loopback mere.run vision-chat API with an installed, licensed model, for example:

```sh
mere.run api serve --engine text-chat-muse-glimmer --model vision-chat-muse-glimmer-30b
mere-computer-use doctor
mere-computer-use windows
```

The model is not downloaded or licensed by this plugin. Muse Glimmer uses Apache-2.0 and retains Meta's usage policy; inspect and accept both through mere.run before running the server.
`doctor` checks the local model endpoint, Driver daemon, and the app-attributed Accessibility and Screen Recording grants without requesting permissions.

## Run

Choose the `pid` and `window_id` returned by `windows`. Planning is read-only and creates a local `run.json`:

```sh
mere-computer-use plan --pid 123 --window-id 456 --task "Find the total in this window" --output ./computer-run
mere-computer-use run ./computer-run/run.json
mere-computer-use resume ./computer-run/run.json
```

The agent is restricted to that window, a maximum number of actions, and the bundled observe/click/type/key tools. Accessibility tokens are preferred; pixel actions require coordinates and the latest screenshot capture ID. Each action needs a fresh observation, and the final action needs a subsequent observation. Actions default to Cua Driver's background delivery. The run records action counts and a model report, but cannot independently certify task success. Screenshots are passed in memory to Pi and are not written to the run directory.

`--base-url` must be loopback. Set `MERE_COMPUTER_USE_API_KEY` for a protected local server. `cleanup` only marks the local run record; the plugin does not own or stop the mere.run server or Cua daemon.

## License boundary

This package is MIT. Cua Driver is an external MIT prerequisite. Cua perception and SoM packages, model artifacts, and Ultralytics are excluded because their reviewed distribution has AGPL components. See [Cua's own licenses](https://github.com/trycua/cua) before installing optional components.
