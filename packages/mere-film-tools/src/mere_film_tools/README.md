# mere_film_tools Source Map

`mere_film_tools` is the durable short-film studio around Pi and local
`mere.run` media inference.

Modules:

- `cli.py`: public lifecycle, approval, configuration, review, reroll, and Pi
  launch commands.
- `state.py`: typed project construction, atomic manifests, gates, tasks,
  artifact hashes, issues, and summaries.
- `pi_harness.py`: bundled-resource lookup, read-only child Pi invocation,
  structured-result validation, and interactive Pi launch.
- `orchestrator.py`: bounded department fanout and validated director synthesis
  into treatment, production-plan, and review canon.
- `production.py`: deterministic media jobs, `mere.run` preflight and execution,
  FFmpeg normalization/assembly, FFprobe QC, archival rerolls, and delivery.
- `common.py`: strict JSON boundary helpers and atomic file utilities.
- `resources/pi/`: explicit extension, skill, prompt, and specialist roles.

Only the plugin mutates authoritative project state. Department Pi processes
receive a built-in read-only tool allowlist and return versioned JSON proposals.
Every creative and production transition is held at an explicit user gate.
Media generation remains serialized through local `mere.run`; cleanup never
deletes the resumable project.
