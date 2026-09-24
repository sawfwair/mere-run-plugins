# Computer Use plugin

`mere-computer-use` uses a local mere.run vision model and the separately installed MIT-licensed Cua Driver CLI to act in one selected macOS window. It packages no Cua code or weights.

On a current `mere.run`, `plugin install --yes` installs the plugin and its pinned, signed MIT Cua Driver app. On older CLIs, run `mere-computer-use setup --yes` after installation. Install Pi and grant `CuaDriver.app` macOS Accessibility and Screen Recording permissions. Install and review the Muse Glimmer model before running a task:

```sh
mere.run plugin install mere-computer-use --yes
mere.run model info vision-chat-muse-glimmer-30b
mere.run model pull vision-chat-muse-glimmer-30b --accept-model-license
cua-driver permissions grant
mere-computer-use doctor
mere-computer-use windows
mere-computer-use plan --pid 123 --window-id 456 --task "Read the total" --output ./computer-run
mere-computer-use run ./computer-run/run.json
mere-computer-use resume ./computer-run/run.json
```

The `pid` and `window_id` come from `windows`. `plan` creates a local record and performs no desktop action. `run` starts a loopback `mere.run api serve` process for an installed Muse Glimmer or Ornith Q4 model when needed, reuses a compatible existing server, and stops only the process it started. Choose Ornith with `plan --model text-agent-ornith-35b-mlx-4bit`. It pins all tools to the selected window, requires a fresh observation between actions, and limits action count. The agent prefers accessibility tokens and can use screenshot coordinates with the latest snapshot ID for custom controls. Screenshots are passed to Pi in memory. The result records the model's report and whether a final observation occurred; verify important outcomes in the app yourself.

The local model endpoint must be loopback. Use `MERE_COMPUTER_USE_API_KEY` if the server requires an API key. Automatic start supports Muse Glimmer after its model receipt records acceptance and Ornith Q4; other models require a compatible server started separately. Ornith requires a mere.run build with Qwen-family image data URL support; the 0.50.0 API fails on screenshot requests. The plugin does not download models or accept licenses. Muse Glimmer uses Apache-2.0 and retains Meta's usage policy, which requires separate review. The Ornith target and vision component are MIT, and its optional MTP head is Apache-2.0. The plugin excludes Cua perception/SoM packages, weights, and Ultralytics because the reviewed optional distribution contains AGPL components. See the [package README](https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-computer-use) for details.
