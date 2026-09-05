# First model baseline

For benchmark reviewers, this record captures one completed Ornith Q4 run of
pack 0.2.0. Use this configuration as the first comparison baseline.

## Result

**222 of 240 cases passed (92.5%).** No scores were changed after inspecting
responses. Development: 110/120 (91.7%); held-out: 112/120 (93.3%).
All 60 in-memory fixture outcomes passed.

| Expected action | Passed | Total |
| --- | ---: | ---: |
| Call | 163 | 164 |
| Clarify | 38 | 43 |
| Unavailable | 17 | 28 |
| No tool | 4 | 5 |

The scorer accepted 238/240 decision structures. It recorded four hard failures:
two calls when no call was correct, a calendar call missing its required end,
and a zero-argument call missing the required `arguments: {}` object.
These are scorer classifications, not runtime crashes. All 240 generations
completed; the report records `promotionEligible: false`. Diagnostic gates do
not qualify this model for release.

## Interpretation

Unavailable capabilities are the largest failure group: 11 of 28 cases failed.
Examples include selecting task cancellation for file deletion and image editing
for text transcription. The model also requested a task ID after the user
cancelled an issue request and asked for no action.

Three clarification cases need independent review:

- `documents.missing-input`: returned `url or html`, while the scorer accepts
  `html` or `url` as separate alternatives.
- `filesystem.ambiguous-occurrence`: asked which occurrence to replace, while
  the scorer expects the field name `old`.
- `browser.ambiguous-button`: asked which Save button to click, while the scorer
  expects `selector`.

Their intent appears reasonable, although the prompt requests parameter names.
The 92.5% score retains all three failures. Review the clarification contract
before a versioned scorer change; do not silently adjust this baseline.

## Configuration and evidence

- Model: `text-agent-ornith-35b-mlx-4bit` (Ornith 1.5 35B-A3B Q4).
- Runner: mere.run 0.50.0; Apple M4 Max, 128 GiB unified memory.
- One trial per case; temperature 0; thinking display off; JSON object output.
- Context: 8,192 tokens; maximum output: 384 tokens.
- Runtime seed control: unavailable. Temperature 0 does not establish repeatability.
- Pack SHA-256:
  `8a3576c4a21e76c15afc264cc9c81820b0fede47b83cdfbce2a60605d3880cf0`.
- Runtime manifest SHA-256:
  `9c095596624896bcdb9405ced570d2b76696db922aa4bcb47f363f5ae068524f`.
- Runner executable SHA-256:
  `1c1f7eaef69a979c378b920143ea37eb6359c54e4d61abe71ef06f7c3298aa48`.

An eight-case smoke passed 7/8, then the same checkpoint resumed through all
240 cases. The two processes took 33.66 and 622.57 seconds respectively
(about 10.9 minutes of measured process wall time, excluding the pause).
Reported generation time totals 610.24 seconds, including prefill; the median
case took 2.15 seconds. These measurements are not decode-only throughput.

The resumed process reported a peak memory footprint of 110,041,969,576 bytes
(102.5 GiB) through `/usr/bin/time -l`. This is whole-process high-water
accounting across the run, not model weight size or an isolated per-case GPU
measurement. Memory growth across repeated cases needs separate investigation.

The [complete report](results/ornith-q4-baseline.json) retains responses, scores,
per-case timings, model provenance, and file hashes. The
[failure audit](results/ornith-q4-failures.json) pairs all 18 failures with their
expected decisions and identifies review candidates. Local logs and the frozen
pack are under the gitignored directory:

```text
runs/ate-v0/ornith-35b-4bit-20260905T012003Z
```

## Gemma runtime attempts

Gemma 4 12B Q4 was attempted first. Both the default runtime and a separate
attempt with `MERERUN_GEMMA4_MTP=0` exited with code 133 before any case completed.
MLX reported incompatible broadcast shapes `(1,1,337,512)` and `(1,1,256,512)`.
Disabling speculative decoding did not resolve the error. These attempts have
no model-quality score. They used the unmodified runtime.

The [runtime failure records](results/gemma4-runtime-failures.json) retain both
attempt configurations and diagnostic logs.

A subsequent fix, commit `2278ce63` on `codex/gemma4-prefill-shape`, corrects full-attention cache
allocation after spare capacity is trimmed. A debugger backtrace identifies
`Gemma4FullKVCache.append`, and a regression test reproduces the 337-versus-256
mismatch before the fix. With the fix, the
[original eight-case smoke](results/gemma4-prefill-fixed-smoke.json) passes 8/8
using default runtime settings. This smoke is not a complete Gemma baseline;
232 cases remain. Runner hashes in the reports distinguish the patched binary
from the original Ornith and Gemma attempts.

## Results by family

Each family has 12 cases, which is too few for a precise family ranking.

| Family | Passed |
| --- | ---: |
| audio | 12/12 |
| browser | 11/12 |
| calendar | 9/12 |
| captions | 11/12 |
| documents | 11/12 |
| filesystem | 10/12 |
| geo | 12/12 |
| git | 11/12 |
| images | 11/12 |
| issues | 10/12 |
| mail | 11/12 |
| metrics | 10/12 |
| notes | 11/12 |
| publishing | 12/12 |
| scheduling | 11/12 |
| search | 12/12 |
| sql | 12/12 |
| storage | 11/12 |
| tables | 12/12 |
| web | 12/12 |


## Limits

This is one run of an assistant-authored, publicly visible fixture benchmark.
It measures prompted JSON decisions and bounded fixture outcomes. It does not
measure native tool transport, autonomous multi-step work, live MCP servers,
production reliability, or representative performance across the ATE dataset.
Independent case review and comparison against a second model remain pending.
Keep this pack frozen when collecting the next comparison.
