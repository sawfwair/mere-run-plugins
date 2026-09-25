# Local validation: 2026-09-25

The first matched run used one attempt per model on one macOS workstation. Both models used seed `cu-v0-20260925`, the same three cases, and suite SHA-256 `d2c123cba7d440547d1955da39e25738fca92e3920f33303b3bc4f60392830d4`. The fixture generated the same codes for both models. The runner used the plugin source at `e5af178d3ea09e58e064ebc5b2ca7b1feceb1209` plus the uncommitted suite shown by that hash.

Runtime: `mere.run` 0.56.0 from core commit `0aed67626322b02c5e1571b6631d106597ac3a96` (binary SHA-256 `d67a1e744baac2e02a1b2f19d4c76930dbf941babfc6736a9c039823664beaa4`), Pi 0.84.3, Cua Driver 0.28.2, macOS 26.5.2. The LFM API log reported DSpark loaded; this run does not establish a DSpark speed benefit. Other checks were active on this workstation, so durations are not a controlled performance comparison.

| Model | Read code `893859` | Record button | Enter and submit `323517` |
| --- | --- | --- | --- |
| Ornith 35B Q4 | Pass: 1 observation, 0 actions, exact code | Pass: 2 observations, 1 action, `recordCount=1`, no distractor clicks | Pass: 3 observations, 2 actions, `submitCount=1`, exact submitted text, no Discard |
| LFM2.5-VL 3B BF16 | Pass: 1 observation, 0 actions, exact code | Fail: 1 observation, 0 actions, `recordCount=0` | Fail: 1 observation, 0 actions, `submitCount=0`, empty submitted text |

| Model | Read wall time | Record wall time | Submit wall time |
| --- | ---: | ---: | ---: |
| Ornith 35B Q4 | 17.427 s, pass | 38.127 s, pass | 100.977 s, pass |
| LFM2.5-VL 3B BF16 | 6.475 s, pass | 5.049 s, fail | 14.122 s, fail |

These existing `durationSeconds` values span fixture launch through window selection, planning, agent execution, and fixture shutdown. They exclude API model startup. LFM's shorter failed action cases are not successful speed results. The original reports did not separate agent time or API startup; the runner now records those fields for future runs. The single-run timing is not a controlled latency comparison.

LFM's button result contained a malformed textual tool-call fragment. Its form result claimed entry and a Submit click, while the independent fixture state remained unchanged. The scoring correctly rejected both. These observations support a local action-path failure for this model and runtime combination. They do not prove LFM can never perform computer use, and this controlled fixture does not prove reliability in arbitrary apps. The earlier TextEdit smoke remains a separate transfer test.

## Timed rerun

A second matched run used seed `cu-v0-wall-20260925` and suite SHA-256 `9cec18b52b45123dad0bc52c7bbd4ed2f0d42d1a002f5f5b229cda142878d078`. The source base was plugin commit `42c866b25244553406fb1447db304463f78fda57` plus the timing changes shown by that suite hash. Both models used the same runtime binary and 150-second per-case agent timeout.

| Model | Read: case / agent | Record: case / agent | Submit: case / agent | API startup | Setup | Full run |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ornith 35B Q4 | 29.290 / 28.123 s, pass | 91.035 / 90.168 s, pass | 153.026 / 150.919 s, timeout | 22.066 s | 42.617 s | 321.016 s |
| LFM2.5-VL 3B BF16 | 4.738 / 3.642 s, fail | 6.684 / 6.054 s, fail | 8.694 / 8.055 s, fail | 2.662 s | 11.956 s | 32.205 s |

“Case” is fixture launch through teardown; “agent” is the plugin `run` call. Setup includes preflight, fixture compilation, and API startup. Full run includes setup, all cases, and server shutdown. LFM made zero actions in both action cases and did not observe the read case, so its shorter times do not represent completed tasks. Ornith submitted the correct form value and made a final observation, but Pi exceeded the 150-second limit before finishing. The strict case score remains a timeout failure.

After adding `outcomeReached` and `outcomeWallTimeSeconds`, a separate Ornith form run with the same seed reached the correct submitted value at **98.123 seconds**, finished the agent run at **131.922 seconds**, and closed the case at **133.497 seconds**. Its API startup was 21.502 seconds, setup 40.453 seconds, and full one-case run 174.423 seconds. This run used suite SHA-256 `07053ec7cf52724c98a803f6c228fc81c6529ba87c0575673f3e0081e4744062`. The difference between 98.123 and 131.922 seconds is time spent after the app reached the goal, including the final observation and agent response.

These runs show material wall-time variation and an outcome/agent-completion gap. They are not a controlled speed comparison or a reliability estimate. The complete local manifests, fixture states, and API logs remain under ignored `runs/computer-use-v0/` on the validating machine; they are not packaged with the plugin.

## Ornith decode throughput probe

The instrumented runner repeated the Record-button case with seed `cu-v0-wall-20260925` on the same machine and **debug** runtime binary. Suite SHA-256 was `56f545d91a5c2d6d95a8ee9cec9b7d2b59dedd0673c734dd42f8d8e10ea3c09a`. Ornith passed with one action and two observations. The API runtime counters reported **400 generated tokens over 54.580 seconds of decode across five completed requests, or 7.33 tokens/second**. The correct app outcome occurred at 61.968 seconds; agent time was 82.201 seconds, case time was 83.003 seconds, API startup was 18.394 seconds, and the full one-case run was 117.442 seconds. The local report is `runs/computer-use-v0/20260925T150659Z-text-agent-ornith-35b-mlx-4bit/report.json`.

The same core commit was then built with `swift build -c release --product mere.run --disable-index-store` (release binary SHA-256 `3ceef66bdf3588d01d3f22a961d0f7553ea678ddf64fab4e5a825e5d220611de`). On the same seed and Record-button case, Ornith again passed with one action and two observations. The release API reported **311 generated tokens over 8.567 seconds of decode across five requests, or 36.30 tokens/second**. The correct click occurred at 22.252 seconds, agent time was 37.286 seconds, case time was 37.921 seconds, API startup was 17.849 seconds, and the one-case run was 68.647 seconds. This run used suite SHA-256 `326fa29ee454a95e1d2fe4259870a5c4e8cae7873e7c488011cf75c90d117199`; its local report is `runs/computer-use-v0/20260925T154214Z-text-agent-ornith-35b-mlx-4bit/report.json`.

The generated text and token counts differed between the two stochastic runs, and other local builds were active. The rate and wall-time differences therefore demonstrate the debug/release mismatch in this local comparison without isolating its exact contribution. The release trace recorded one MTP request and four pipelined target requests. Earlier fixed-token release benchmarks in `mere.run` measured roughly 50–130 decode tokens/second for Ornith Q4 on text-only prompts; those workloads differ from this vision/tool agent loop.

The decode rate excludes prompt processing, screenshot and accessibility capture, desktop actions, and Pi overhead. The five-request total is a single CUA-case sample, not a sustained throughput benchmark.
