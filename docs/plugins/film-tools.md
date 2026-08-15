# Film Studio

`mere-film-tools` is a Pi-powered producer-director for short films. A user can
start with one sentence, resolve only the requirements that materially affect
the result, and then move through story development, preproduction, local media
creation, independent review, rerolls, picture lock, and verified delivery.

Pi is the harness. It owns the interactive conversation, provider selection,
and specialist-agent execution. The plugin is the studio ledger: it owns the
brief, canon, approvals, deterministic jobs, resumability, and proof.

## Install and launch

Install Pi using its current `@earendil-works/pi-coding-agent` package, ensure
`mere.run`, FFmpeg, and FFprobe are available, then install the plugin:

```bash
mere.run plugin install mere-film-tools
mere-film-tools doctor
mere-film-tools plan \
  --idea "A lighthouse keeper receives a signal from a vanished ship" \
  --title "The Last Signal" \
  --duration 45 \
  --output-dir ./the-last-signal
mere-film-tools agent --run-manifest ./the-last-signal/run.json
```

`agent` loads only the bundled Pi extension, film skill, prompt template, and
the project manifest by default. Its tool allowlist excludes shell, edit, and
write. Pass `--with-pi-context` only when you intentionally want normal Pi
resource discovery; the film tool allowlist still applies. Pi credentials stay
in Pi, and the plugin never reads or stores them.

## How the studio works

The workflow has five explicit user gates:

1. **Brief** — idea, audience, genre, tone, rating, intended usage, references,
   must-haves, and exclusions are confirmed.
2. **Treatment** — story, beats, visual language, and sound language are
   synthesized from story, design, and production proposals.
3. **Production** — screenplay, shot plan, cast/location canon, sound intent,
   duration, and compute mode are confirmed before media runs.
4. **Picture lock** — technical QC, dialogue intelligibility, captions, local
   generated-media inspection, and independent story, edit, and continuity
   review have passed. A human has watched the cut and recorded a hash-bound
   approval in the local review package.
5. **Delivery** — the playable master and checksum-backed delivery manifest are
   explicitly accepted.

Pi child departments run with `read`, `grep`, `find`, and `ls` only. Each must
return `film-department-result.v1` JSON. A director synthesis can enter canon
only after the plugin validates its task, role, phase, and deliverable shape.

## Production control

Projects start in `plan` mode. After approving the production plan, opt into
local execution:

```bash
mere-film-tools configure ./the-last-signal/run.json --mode draft
mere-film-tools preflight ./the-last-signal/run.json
mere-film-tools run ./the-last-signal/run.json
```

Draft and final modes derive cast masters, shot keyframes, video clips, timed
dialogue performances, authored sound-effect cues, an optional score,
normalized edit blocks, and an H.264/AAC cut. Set `--takes-per-shot 2` through
`4` to create deterministic
candidate clips for each shot. Local `mere.run vision inspect` scores an
early/mid/late contact sheet from every candidate against cast, location, and
shot canon; the chosen clip enters the edit while every candidate, score, and
hash remains available for review. The default is one take to avoid multiplying
video compute without consent.

Vision responses are bounded to concise visible findings and retried once when
the local model returns malformed, overlong, or truncated JSON. Metadata such
as seeds and voice direction never enters the visual mismatch rubric.

Before any media job starts, the studio resolves every catalog-managed model
required by the accepted plan through `mere.run model info` and writes a hash-bound
`production-readiness.json` receipt. Image and video jobs additionally append
`--preflight --json` before generation and are serialized through local machine admission. Dialogue uses
`mere.run speech synthesize`, then `speech transcribe` checks that the rendered
line remains intelligible. The accepted timeline emits SRT and WebVTT sidecars.
The default vision role is recorded as `auto-qwen3-vl-2b`: `vision inspect`
owns its adapted Qwen3-VL runtime and cached-or-download lifecycle. An explicit
`--vision-inspector-model` must be a compatible local Qwen model root, not an
unrelated managed vision-chat ID.
The final mix sidechain-ducks the score beneath dialogue, applies a -16 LUFS /
-1.5 dBTP loudness target, resamples the master to 48 kHz, and records loudness
and sample-rate evidence in technical QC.
Timed `mere.run sfx generate` cues are mixed at their accepted in-points and
levels; FFprobe verifies every generated sound asset and FFmpeg rejects cues
peaking below -50 dBFS before creative review.
Resume reuses media only when its recorded SHA-256, artifact record, and
complete job-spec digest still match.
Shot transitions are explicit: `cut` joins directly, while `fade` applies a
short picture-and-sound fade to black after the shot.

The exact resolved command plan is written before media starts. Model and
binary overrides remain explicit:

```bash
mere-film-tools configure ./the-last-signal/run.json \
  --mode final \
  --takes-per-shot 3 \
  --image-master-model image-zimage-max \
  --image-shot-model image-klein-9b \
  --video-model video-ltx25-distilled-bf16 \
  --vision-inspector-model /path/to/local/vlm \
  --speech-asr-model speech-asr-qwen3 \
  --speech-tts-model speech-tts-qwen3-nano \
  --sfx-model sfx-woosh-dflow \
  --music-model music-acestep
```

The brief records intended usage. Known noncommercial image and SFX models are blocked
for a commercial project; choose a model whose current terms cover that project.
`mere.run` remains authoritative for installed-model metadata, terms, and
preflight diagnostics, so review its output when selecting any override.

## Review, rerolls, and delivery

Technical review verifies file presence, audio/video streams, geometry,
duration tolerance, and SHA-256, and records loudness plus advisory black-frame,
freeze, and silence scans. The studio extracts early, midpoint, and late frames
from each generated clip and asks `mere.run vision inspect` to compare visible
evidence with cast, wardrobe, location, and shot canon. The take-selection,
per-shot visual, caption, and dialogue transcription receipts are hash-bound to
their source media and attached to the independent Pi critics.

Open `reviews/index.html` for the local picture-lock package. It combines the
captioned playable cut, QC summaries, selected-take scores, shot frames, and
findings without uploading media. Its approval/revision controls download a
`film-human-review.v1` decision bound to the exact cut and evidence digest.
Import it, or record the same explicit decision through Pi:

```bash
mere-film-tools review-decision ./the-last-signal/run.json \
  --input ./the-last-signal-review-decision.json
```

Automated checks and AI critics remain evidence; they never approve the human
picture-lock gate. Picture lock records the rough-cut, review-package, technical,
caption, inspection, critic, and human-decision hashes. Delivery stops if any
locked decision surface changes. A revision decision exposes its exact shot
requests in `film_status.reviewRequests`; Pi applies only those pending rerolls
and preserves the rest of the queue across restarts.

Target one shot without losing prior work:

```bash
mere-film-tools reroll ./the-last-signal/run.json \
  --shot beacon-fails \
  --note "Hold on the keeper before the relay clicks."
```

The prior frame, clip, normalized block, review evidence, and delivery output
move under `takes/`; seed and take advance; downstream proof resets. `cleanup`
never deletes a film project.

Every mutating command takes an OS-backed single-writer project lock. If a
process dies, the operating system releases the lock; the next writer converts
orphaned `running` tasks and jobs into retryable failures and resumes from the
last hash-verified artifact. Lock contention reports the active PID, host, and
operation instead of allowing two agents to race the ledger.

Use `mere-film-tools recover ./the-last-signal/run.json` to perform only that
state repair without advancing the next film phase.

## Continue the edit in Animatic

Export a normalized, checksum-backed editorial handoff without duplicating the
film project's source of truth:

```bash
mere-film-tools export-animatic ./the-last-signal/run.json \
  --output ./the-last-signal/exports/animatic/film-animatic-handoff.json
animatic production import-film \
  ./the-last-signal/exports/animatic/film-animatic-handoff.json \
  --output json
```

The exporter rejects missing, modified, or escaping ledger assets. The handoff
preserves shot order, exact timeline spans, selected deterministic seeds, cast,
locations, and the project's proof state. Animatic verifies the manifest and
every media checksum again before creating its normal project, episode, scene,
shot, and asset records.

## Durable artifacts

Every project includes `run.json`, `film-project.json`, `brief.json`, accepted
treatment and production plan, department proposals, candidate takes and their
selection receipt, SRT/WebVTT captions, media logs, generated assets, QC reports,
human decision, cuts, final master, checksums, and provenance. Inspect or
continue safely with `status`, `resume`, and `run`. Delivery also extracts a
checksum-backed poster still and 1280×720 thumbnail from the locked cut.
