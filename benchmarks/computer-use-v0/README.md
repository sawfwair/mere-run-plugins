# Computer-use v0 local evaluation

This small macOS suite runs the real `mere-computer-use` → Pi → `mere.run` → Cua Driver path against a disposable AppKit window. It has three cases:

| Case | Required outcome |
| --- | --- |
| `read-code` | Observe and report the fresh code exactly, with no action. |
| `button` | Click Record once, without clicking Reset or Cancel. |
| `form` | Read a fresh phrase, type it, and submit once without Discard. |

The fixture writes its own state to disk after each button press. Scoring checks that state, the plugin's recorded action count, and a final observation. Model prose cannot substitute for a state change. The fresh code changes per attempt. These controlled windows measure this interface path; they do not establish general reliability in TextEdit or other third-party apps.

## Run

On Apple Silicon macOS, install and grant Accessibility and Screen Recording to Cua Driver, install Pi, and have the model already installed and its usage terms acknowledged. Run from the repository root:

```bash
python3 benchmarks/computer-use-v0/run.py \
  --model text-agent-ornith-35b-mlx-4bit \
  --mere-run /absolute/path/to/mere.run

python3 benchmarks/computer-use-v0/run.py \
  --model vision-chat-lfm25-3b-bf16 \
  --mere-run /absolute/path/to/mere.run
```

Use `--engine` for a different image/tool model. `--case button` selects one case; `--repeat 3` repeats the selected cases with new codes. Pass the same `--seed` to two model runs for identical codes. `--timeout` limits each Pi run, and `--startup-timeout` limits API startup. The runner compiles the fixture, starts one loopback API for the selected model, runs each case in a fresh window, and stops only processes it started. It uses the plugin source in this checkout and writes the complete `run.json`, fixture state, API log, and aggregate `report.json` to an ignored `runs/computer-use-v0/` directory. Exit codes are 0 for all passes, 2 for scored failures, and 1 for setup failure.

Compare models with identical case selections, repeat counts, runtime binary, and machine conditions. Review individual failure reasons and logs before drawing conclusions. Startup and per-case durations are recorded, but this is not a controlled throughput benchmark.

See [VALIDATION.md](./VALIDATION.md) for the first matched local run.
