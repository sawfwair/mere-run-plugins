# ATE-derived tool-decision cases

For benchmark authors evaluating local models, this pack supplies 240 authored
single-decision cases grounded in 20 server families from Cohere Labs' ATE.
Read [the case catalog](CASES.md) to review each expected decision and rationale.

## Contents

- 240 cases: 12 per family, with 120 development and 120 held-out cases.
- 60 cases check results and complete state in deterministic, in-memory
  fixtures. Eight SQL cases also run against alternate fixture states.
- 20 cases choose a next action from supplied earlier tool results; three
  involve recovering from an error or unsuitable result.
- No fixture opens a network connection, invokes an MCP server, changes host
  files or processes, or accesses an external account.
- Missing arguments, ambiguous targets, unavailable capabilities, explicit
  cancellation, typed values, narrow writes, and instruction-like data.

`cases.jsonl` contains model messages and scorer-only metadata. Each case has
one expected next action, with reviewed alternatives where appropriate. Tool order varies deterministically by case.
All target and distractor servers stay within their assigned split.

The prompts, descriptions, parameter contracts, expected decisions, and fixtures
are authored for this benchmark. ATE supplies tool identities and capability
inspiration. These contracts are not extracted upstream MCP schemas. In
particular, storage accepts JSON values directly, and scheduling covers one-time
offset-qualified timestamps. Do not use these adapters to invoke real servers.

## Validate and run

From the repository root:

```bash
python3 -m unittest discover -s benchmarks/ate-v0 -p 'test_*.py'
mere.run eval pack validate benchmarks/ate-v0 --json
mere.run eval run benchmarks/ate-v0 --model base=MODEL_ID --dry-run --json
mere.run eval run benchmarks/ate-v0 --model base=MODEL_ID \
  --allow-external-scorer --checkpoint runs/ate-v0/checkpoint.json \
  --output runs/ate-v0/report.json
```

Replace `MODEL_ID` with an installed chat model supporting structured JSON
responses. Create `runs/ate-v0` before running the evaluation. The external
scorer reads this pack's declared case file and executes only in-memory Python
fixture operations. A model run is separate from the fixture tests.

## Interpret results

The primary score is binary correctness of the complete decision. Most argument
comparisons preserve JSON types and ignore object-key order. They accept
equivalent JSON number spellings such as `1500` and `1500.0` where the schema
permits numbers; integer-only fields remain strict. SQL cases accept
equivalent single statements only when results and complete state match on both
fixture variants. Constant answers or updates that happen to work on one state
fail the alternate state. Clarification fields are compared without regard to order. The missing-document-input case
accepts requesting either HTML or a URL. Extra fields fail. Fixture cases
also require the expected result and full resulting state, including retained
records. Metrics separate response validity, action, tool, arguments, and fixture
outcome. Tool and argument metrics apply only to expected-call cases; fixture
metrics apply only to the 60 executable cases. `decision-exact` remains distinct
from semantic `decision-correct` for SQL. [Coverage](COVERAGE.md) explains the
family balance, behavior counts, and path to a larger benchmark.

This evaluates prompted JSON decisions, not native function-call transport,
native tool-result transport, multi-step execution, live server reliability, or
model quality across occupations. Development and held-out families also differ
in difficulty. The published held-out cases are not sealed or contamination-free.
Gates are diagnostic and establish no release qualification.

## Provenance and review

[Source identifiers and hashes](sources.json) pin ATE revision
`4b567ba98acc6ddf27b2abb9004844581083c5d8`. The sample is deliberately small
and nonrepresentative. Upstream description text and O*NET task text are not
redistributed. See [source and reuse notes](SOURCES.md).

Cases received an authoring-assistant review and deterministic checks.
The [first model baseline](BASELINE.md) records Ornith Q4 at 222/240 cases
(92.5%), with all 60 fixture outcomes passing. Independent human review and
comparison against another model remain pending.
See the [validation record](VALIDATION.md) for the checked pack identity and
completed local checks.
