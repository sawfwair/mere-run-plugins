# Computer Use plugin

`mere-computer-use` uses a local mere.run vision model and the separately installed MIT-licensed Cua Driver CLI to act in one selected macOS window. It packages no Cua code or weights.

Install the plugin with `mere.run plugin install mere-computer-use --yes`, then install Cua Driver 0.28.2 or later and Pi. Run `CuaDriver.app` and grant its macOS Accessibility and Screen Recording permissions. Start a local mere.run vision-chat server with a model you have installed and licensed:

```sh
mere.run api serve --engine text-chat-muse-glimmer --model vision-chat-muse-glimmer-30b
mere-computer-use doctor
mere-computer-use windows
mere-computer-use plan --pid 123 --window-id 456 --task "Read the total" --output ./computer-run
mere-computer-use run ./computer-run/run.json
mere-computer-use resume ./computer-run/run.json
```

The `pid` and `window_id` come from `windows`. `plan` creates a local record and performs no desktop action. `run` pins all tools to that window, requires a fresh observation between actions, and limits action count. The agent prefers accessibility tokens and can use latest-capture coordinates for custom controls. Screenshots are passed to Pi in memory. The result records the model's report and whether a final observation occurred; verify important outcomes in the app yourself.

The local model endpoint must be loopback. Use `MERE_COMPUTER_USE_API_KEY` if the server requires an API key. The plugin does not download models or accept licenses. Muse Glimmer uses Apache-2.0 and retains Meta's usage policy, which requires separate review. The plugin excludes Cua perception/SoM packages, weights, and Ultralytics because the reviewed optional distribution contains AGPL components. See the [package README](https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-computer-use) for details.
