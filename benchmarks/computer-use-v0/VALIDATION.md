# Local validation: 2026-09-25

This is one run per model on one macOS workstation. Both runs used seed `cu-v0-20260925`, the same three cases, and suite SHA-256 `d2c123cba7d440547d1955da39e25738fca92e3920f33303b3bc4f60392830d4`. The fixture generated the same codes for both models. The runner used the plugin source at `e5af178d3ea09e58e064ebc5b2ca7b1feceb1209` plus the uncommitted suite shown by that hash.

Runtime: `mere.run` 0.56.0 from core commit `0aed67626322b02c5e1571b6631d106597ac3a96` (binary SHA-256 `d67a1e744baac2e02a1b2f19d4c76930dbf941babfc6736a9c039823664beaa4`), Pi 0.84.3, Cua Driver 0.28.2, macOS 26.5.2. The LFM API log reported DSpark loaded; this run does not establish a DSpark speed benefit. Other checks were active on this workstation, so durations are not a controlled performance comparison.

| Model | Read code `893859` | Record button | Enter and submit `323517` |
| --- | --- | --- | --- |
| Ornith 35B Q4 | Pass: 1 observation, 0 actions, exact code | Pass: 2 observations, 1 action, `recordCount=1`, no distractor clicks | Pass: 3 observations, 2 actions, `submitCount=1`, exact submitted text, no Discard |
| LFM2.5-VL 3B BF16 | Pass: 1 observation, 0 actions, exact code | Fail: 1 observation, 0 actions, `recordCount=0` | Fail: 1 observation, 0 actions, `submitCount=0`, empty submitted text |

LFM's button result contained a malformed textual tool-call fragment. Its form result claimed entry and a Submit click, while the independent fixture state remained unchanged. The scoring correctly rejected both. These observations support a local action-path failure for this model and runtime combination. They do not prove LFM can never perform computer use, and this controlled fixture does not prove reliability in arbitrary apps. The earlier TextEdit smoke remains a separate transfer test.

The complete local manifests, fixture states, and API logs are under ignored `runs/computer-use-v0/20260925T142513Z-vision-chat-lfm25-3b-bf16/` and `runs/computer-use-v0/20260925T142607Z-text-agent-ornith-35b-mlx-4bit/` on the validating machine. They are not packaged with the plugin.
