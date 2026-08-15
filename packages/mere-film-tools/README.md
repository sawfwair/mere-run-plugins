# mere-film-tools

`mere-film-tools` is the local-first studio layer for creating short films with
Pi and `mere.run`. Pi conducts the creative conversation and isolated specialist
agents. The plugin owns typed briefs, approvals, production state, resumability,
media commands, review evidence, and delivery manifests.

The plugin never creates paid resources. It plans before work, defaults to
`productionMode=plan`, and will not run image, video, music, or assembly commands
until the production gate is approved and the mode is changed to `draft` or
`final`.

The brief also records personal, noncommercial, or commercial intent. Known
noncommercial image and SFX models cannot run for a commercial project.

```bash
mere-film-tools doctor
mere-film-tools plan \
  --idea "A funny 45-second film about local AI surviving a cloud outage" \
  --title "The Outage" \
  --output-dir ./the-outage
mere-film-tools agent --run-manifest ./the-outage/run.json
```

The required plugin lifecycle remains available without Pi:

```bash
mere-film-tools manifest --json
mere-film-tools status ./the-outage/run.json
mere-film-tools approve ./the-outage/run.json --gate brief
mere-film-tools preflight ./the-outage/run.json
mere-film-tools run ./the-outage/run.json
mere-film-tools resume ./the-outage/run.json
mere-film-tools recover ./the-outage/run.json
mere-film-tools export-animatic ./the-outage/run.json
mere-film-tools cleanup ./the-outage/run.json
```

`export-animatic` writes a normalized handoff inside the project only after
rechecking every exported ledger file's exact byte count and SHA-256 digest.
It preserves cast, locations, contiguous shot timing, selected take and seed,
media references, and current proof state for Animatic's normal production
entities. The returned receipt includes the exact manifest file digest.

The bundled Pi extension exposes typed film tools. Department agents are
read-only: they receive the project contract, return structured proposals, and
cannot edit canon. Only the plugin accepts proposals into the durable project.
The interactive producer-director also starts isolated by default with a strict
allowlist that excludes shell, edit, and write tools. `--with-pi-context` is an
explicit opt-in to normal Pi resource discovery.

Production is resumable at cast, keyframe, timed dialogue, candidate clip,
take-selection, assembly, pixel-grounded inspection, review, and delivery
boundaries. Existing files are reused only when their hashes and job-spec
digests match. Before generation, catalog-managed image, video, speech, SFX,
and music roles are resolved through `mere.run model info`; the Qwen3-VL
inspection role is explicitly recorded as runtime-managed. Both enter a
hash-bound `production-readiness.json` receipt. Set `--takes-per-shot 2` through
`4` to generate deterministic
alternatives and let local vision score their early/mid/late contact sheets
against canon; every candidate remains in the artifact ledger. Generated
dialogue is mixed at its planned in-point, transcribed back for QC, and emitted
as SRT and WebVTT. Timed local sound effects receive independent stream,
duration, and audibility QC. The
score ducks beneath dialogue and the master targets -16 LUFS / -1.5 dBTP.
Final AAC audio is pinned to a 48 kHz delivery sample rate.
Delivery includes poster and social-thumbnail stills. `reviews/index.html` is
the offline picture-lock player,
evidence dashboard, and hash-bound human decision form.

Mutating commands hold an OS-backed single-writer lock. After a crash, orphaned
running work is converted into a retryable durable failure before execution
continues. Rerolls archive prior takes instead of deleting them.
