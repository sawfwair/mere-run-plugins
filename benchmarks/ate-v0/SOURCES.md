# Sources and reuse

This case set derives capability ideas and tool identities from
[Cohere Labs' ATE dataset](https://huggingface.co/datasets/CohereLabs/ATE).
It is not an official Cohere benchmark or an endorsed adaptation.

The source snapshot is revision
`4b567ba98acc6ddf27b2abb9004844581083c5d8`. `sources.json` records the downloaded
Parquet file hashes, selected tool row IDs, upstream repository links, and
canonical source-record hashes. Record hashes use SHA-256 over UTF-8 JSON with
sorted keys, no ASCII escaping, and comma/colon separators without spaces.
The raw Parquet files were inspected during authoring and are not bundled.

The original release describes public listings collected in May 2026. Its
dataset-level license was unset at the inspected revision, and upstream
repositories govern reuse of their description text. This pack retains
identifiers, references, and hashes, and uses newly authored descriptions,
requests, schemas, and fixture data. It does not copy the upstream descriptions,
occupational task text, or judge rationales. Publication and downstream reuse
should retain this provenance and review the source terms for any additional
material being distributed.

## Authored adaptations

Tool names receive family prefixes to avoid collisions. WordPress tool aliases
omit the original `my-mcp-server/` prefix; the full source ID remains recorded.
Parameter names and semantics belong to the benchmark fixtures. They have not
been checked against upstream server implementations. The key-value adapter
accepts JSON values directly, rather than the source description's JSON-parsed
string value. The scheduler adapter deliberately supports only one-time
reminders with explicit offsets. Caption adapters expose a chosen video ID and
optional language. These adaptations make the test contract explicit.

No ATE `good`, `partial`, or `bad` match label is used as an execution oracle.
Expected results and state were authored from the fixture specifications.
All people, messages, records, and operational contexts are synthetic.

## Review status

The authoring assistant checked each request against its catalog, expected
decision, and rationale. The automated suite checks gold decisions, rejected
mutations, JSON typing, fixture state preservation, source references, split
isolation, and the external scorer protocol. These checks establish fixture
consistency, not independent semantic validation or model performance.

Before expanding the set, obtain independent review of ambiguous cases and add
new server families to a separate split. Never move paraphrases or distractor
servers across the development/held-out boundary. Keep public development cases
separate from any future sealed evaluation set.
