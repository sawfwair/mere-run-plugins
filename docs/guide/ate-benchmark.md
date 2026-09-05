# Evaluate tool decisions with the ATE benchmark

Use this benchmark to check whether a local model chooses the right tool,
supplies valid arguments, asks for missing information, and recognizes when no
available tool can do the job. It runs through `mere.run eval` and includes
240 authored cases with inspectable expected decisions and a deterministic
Python scorer.

ATE provides tool identities and capability inspiration. This pack adds the
prompts, parameter contracts, expected decisions, and fixtures needed for an
evaluation. It is an independent, ATE-derived benchmark; it is not an official
Cohere benchmark or a set of executable episodes supplied by ATE.

## Understand the coverage

| Coverage | Pack 0.2.0 |
| --- | --- |
| Decisions | 240 cases across 20 server families, 12 per family |
| Tool catalog | 109 ATE tool aliases with authored parameter contracts |
| Split | 120 development cases and 120 held-out cases |
| Executable fixtures | 60 cases checking results and complete resulting state |
| SQL checks | Eight cases also checked against alternate fixture states |
| Earlier results | 20 cases choose a next action from supplied observations |

The families cover files, documents, browser actions, calendars, mail, search,
SQL, tables, storage, publishing, scheduling, issues, Git, notes, metrics, web,
images, audio, captions, and geographic tools. Cases include ambiguous targets,
missing arguments, unavailable capabilities, typed values, narrow writes,
cancellation, and instruction-like text in untrusted data.

Target and distractor servers remain within their assigned split. The held-out
cases are public, and the two splits differ in difficulty. They do not establish
contamination-free evaluation or comparable family difficulty.

The [case catalog](https://github.com/sawfwair/mere-run-plugins/blob/main/benchmarks/ate-v0/CASES.md)
lists every prompt, expected decision, and rationale. The
[coverage record](https://github.com/sawfwair/mere-run-plugins/blob/main/benchmarks/ate-v0/COVERAGE.md)
contains family and behavior counts. A later expansion to 500–1,000 cases should
add workflows and failure modes found in model runs, with independent review.
Paraphrases alone would add little coverage.

## Prepare the benchmark

You need Git, Python 3, `mere.run` with the `eval` command, and an installed chat
model that supports structured JSON responses. The first complete baseline
used `mere.run` 0.50.0 and Ornith 1.5 35B-A3B Q4. Check the available commands and
models:

```bash
mere.run eval run --help
mere.run model list
```

To download the benchmark, clone the companion repository:

```bash
git clone https://github.com/sawfwair/mere-run-plugins.git
cd mere-run-plugins
```

If you already have a checkout, run the following commands from its root. To
preserve a pack for the smoke test and subsequent full run, copy it into a new
run directory:

```bash
mkdir -p runs/ate-v0/ornith-q4
cp -R benchmarks/ate-v0 runs/ate-v0/ornith-q4/pack
```

Use a fresh directory for each comparison. Keep the copied pack unchanged when
resuming. Pack 0.2.0 has SHA-256
`8a3576c4a21e76c15afc264cc9c81820b0fede47b83cdfbce2a60605d3880cf0`;
compare this identity with the validation output when reproducing the published
baseline.

## Validate and preview a run

To check the fixture expectations and validate the pack without running model
inference, run:

```bash
python3 -m unittest discover -s runs/ate-v0/ornith-q4/pack -p 'test_*.py'
mere.run eval pack validate runs/ate-v0/ornith-q4/pack --json
mere.run eval run runs/ate-v0/ornith-q4/pack \
  --model base=text-agent-ornith-35b-mlx-4bit --dry-run --json
```

For another installed model, replace `text-agent-ornith-35b-mlx-4bit` and use a
separate run directory. Review the dry-run plan before starting inference.

## Run eight cases, then resume

To check model loading, response formatting, scoring, and checkpoint output,
start with eight cases:

```bash
mere.run eval run runs/ate-v0/ornith-q4/pack \
  --model base=text-agent-ornith-35b-mlx-4bit \
  --allow-external-scorer --log-responses \
  --checkpoint runs/ate-v0/ornith-q4/checkpoint.json \
  --output runs/ate-v0/ornith-q4/report.json \
  --case-trial-limit 8
```

`--allow-external-scorer` authorizes execution of the pack's pinned Python
scorer. Review its
[source](https://github.com/sawfwair/mere-run-plugins/blob/main/benchmarks/ate-v0/score.py)
before using it. The fixture operations run in memory: they do not connect to
MCP servers, change host files or processes, or access external accounts.
`--log-responses` retains generated responses for failure review.

To continue through all 240 cases, reuse the same pack, model, and checkpoint.
Add `--resume` and omit the eight-case limit:

```bash
mere.run eval run runs/ate-v0/ornith-q4/pack \
  --model base=text-agent-ornith-35b-mlx-4bit \
  --allow-external-scorer --log-responses \
  --checkpoint runs/ate-v0/ornith-q4/checkpoint.json \
  --output runs/ate-v0/ornith-q4/report.json \
  --resume
```

To run all cases from the start instead, use the smoke command with a fresh
output directory and omit `--case-trial-limit 8`.

## Read the results

The primary score measures correctness of the complete decision. Each response
must choose `call`, `clarify`, `unavailable`, or `no_tool` in the pack's JSON
contract. Additional metrics distinguish response validity, action selection,
tool selection, arguments, and fixture outcomes.

Fixture cases require the correct result and complete resulting state,
including records that should remain unchanged. SQL cases accept equivalent
single statements only when both fixture states produce the expected results
and final state. Clarification cases expect parameter names; plausible prose
can still fail that contract.

The published runs provide different levels of evidence:

| Model and run | Correct decisions | Fixture outcomes |
| --- | ---: | ---: |
| Ornith 1.5 35B-A3B Q4, complete pack | 222/240 (92.5%) | 60/60 |
| Gemma 4 12B Q4, patched-runtime smoke only | 8/8 | Incomplete fixture coverage |

Ornith scored 110/120 on development cases and 112/120 on held-out cases.
Unavailable capabilities accounted for 11 of its 18 failures. Three
clarification failures remain independent-review candidates; the published
score retains them. Start with Ornith when you need to reproduce the existing
complete baseline.

The Ornith run used an Apple M4 Max with 128 GiB unified memory. Measured
process wall time was about 10.9 minutes, excluding the pause between smoke and
resume. Peak whole-process memory was 102.5 GiB; this is not model weight size
or a per-case GPU measurement. Use the smoke run to check your machine's
behavior before committing to a full run.

Gemma's original runtime attempts crashed before completing any cases and have
no quality score. The eight-case result used the patched runtime from
[the Gemma cache-allocation fix](https://github.com/sawfwair/mere-run/pull/440).
It leaves 232 cases unmeasured and is not a full-model comparison. Check the fix's
merge and release status before assuming an installed runtime contains it.

The [baseline record and reports](https://github.com/sawfwair/mere-run-plugins/blob/main/benchmarks/ate-v0/BASELINE.md)
include exact configuration, runtime and pack hashes, responses, timings, and
the failure audit. Keep the pack frozen for the next model comparison. Record
runtime identity and sampling settings alongside scores; a single trial at
temperature zero does not establish repeatability.

## Evaluation limits

This benchmark measures prompted JSON decisions and bounded fixture outcomes.
It does not measure native function-call or tool-result transport, autonomous
multi-step work, live server reliability, or perceptual quality. The supplied
tool contracts are authored adapters, not upstream MCP schemas, and must not be
used to invoke real servers.

The sample is deliberately small and nonrepresentative of ATE or occupations.
Cases received authoring-assistant review and deterministic checks; independent
human review and a second complete model baseline remain pending. Diagnostic
gates do not qualify a model for release.

## Citation and license scope

This benchmark credits Cohere Labs' Agentic Task Ecosystem (ATE) and its
accompanying publication:

Zanele Munyikwa, Campbell Lund, Thomas Euyang, Aidan Peppin, and Marzieh Fadaee.
2026. [Automation's Early Footprint: Where AI Agents Are (and Aren't) Being Built](https://cohere.com/blog/automations-early-footprint).
Cohere Labs. Dataset: [ATE](https://huggingface.co/datasets/CohereLabs/ATE),
revision `4b567ba98acc6ddf27b2abb9004844581083c5d8`.

The repository's [MIT license](https://github.com/sawfwair/mere-run-plugins/blob/main/LICENSE)
applies to its original benchmark code and authored materials. It does not
relicense ATE, upstream server material, or O\*NET content, and grants no
additional rights to those sources.

The [ATE dataset card at this revision](https://huggingface.co/datasets/CohereLabs/ATE/blob/4b567ba98acc6ddf27b2abb9004844581083c5d8/README.md#data-sources-and-attribution)
does not specify a dataset-level license. Upstream repository licenses govern
reuse of verbatim tool descriptions; O\*NET task text remains CC BY 4.0. This
pack excludes raw ATE files, upstream descriptions, O\*NET task text, and judge
rationales. Retained identifiers and provenance are not a claim of unrestricted
ATE reuse or confirmed legal clearance. Attribution alone does not establish
reuse permission.

When publishing or adapting the benchmark, we recommend retaining the citation,
source revision, upstream references, and adaptation notes. This recommendation
does not add conditions to the MIT license. Verify the applicable
license or obtain permission before adding further source material. The
[source and reuse notes](https://github.com/sawfwair/mere-run-plugins/blob/main/benchmarks/ate-v0/SOURCES.md)
describe these boundaries. This benchmark does not claim endorsement by Cohere
Labs, the cited authors, or upstream server developers.

For agent execution in containerized tasks, see
[Terminal-Bench](/plugins/terminal-bench). For repository and docs validation,
see [Testing](/operations/testing).
