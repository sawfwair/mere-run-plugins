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

The original release describes public listings collected in May 2026. This pack
retains identifiers, references, and hashes, and uses newly authored descriptions,
requests, schemas, and fixture data. It does not copy the upstream descriptions,
occupational task text, or judge rationales.

## Citation

For attribution of the ATE source, we recommend this reference, based on the dataset card's
[suggested citation](https://huggingface.co/datasets/CohereLabs/ATE/blob/4b567ba98acc6ddf27b2abb9004844581083c5d8/README.md#suggested-citation):

Zanele Munyikwa, Campbell Lund, Thomas Euyang, Aidan Peppin, and Marzieh Fadaee.
2026. [Automation's Early Footprint: Where AI Agents Are (and Aren't) Being Built](https://cohere.com/blog/automations-early-footprint).
Cohere Labs. Dataset: [Agentic Task Ecosystem (ATE)](https://huggingface.co/datasets/CohereLabs/ATE),
revision `4b567ba98acc6ddf27b2abb9004844581083c5d8`.

We recommend retaining this source reference, the revision, and the description
of our authored adaptations. Upstream server developers are credited through
the repository references in [sources.json](sources.json). These acknowledgments do not imply
endorsement by Cohere Labs, the cited authors, or the server developers.

## License scope

The repository's [MIT license](../../LICENSE) applies to its original benchmark
code and authored materials. It does not relicense ATE, upstream server
material, or O\*NET content, and it grants no additional rights to those sources.
The citation guidance is a provenance recommendation and does not add conditions
to the MIT license.

At the pinned revision, the
[ATE dataset card](https://huggingface.co/datasets/CohereLabs/ATE/blob/4b567ba98acc6ddf27b2abb9004844581083c5d8/README.md#data-sources-and-attribution)
does not specify a dataset-level license. It states that upstream repository
licenses govern reuse of verbatim tool descriptions. It also identifies O\*NET
29.2 task text as CC BY 4.0, attributed to the U.S. Department of Labor,
Employment and Training Administration. This benchmark does not redistribute
that task text.

Attribution and public availability do not establish permission to reuse
third-party material. The limited identifiers and provenance retained here do
not constitute a claim of unrestricted ATE reuse or confirmed legal clearance.
Before adding or redistributing further ATE or upstream material, verify the
applicable license or obtain permission for the intended use, and preserve any
required notices. Citation alone does not resolve the unspecified ATE license.

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
