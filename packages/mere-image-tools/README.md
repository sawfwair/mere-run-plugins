# mere-image-tools

Local image-production companion plugin for `mere.run`.

The first command is `knockout`: remove a subject from its background by calling
the installed `mere.run vision segment` SAM 3.1 runtime, then composing the
selected mask into a transparent PNG.

## Commands

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-image-tools"
mere-image-tools manifest --json
mere-image-tools doctor
mere-image-tools plan \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png
mere-image-tools knockout \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt "subject"
```

By default the plugin calls `mere.run vision segment --model
vision-segment-sam31`. Set `MERE_IMAGE_TOOLS_MERE_RUN` or pass
`--mere-run-command` to use a source-checkout binary such as
`/path/to/mere-run/.build/debug/mere.run`.

The executed segmentation command has this shape:

```bash
mere.run vision segment frame.png \
  --model vision-segment-sam31 \
  --prompt "subject" \
  --output subject.sam31/segmented.png \
  --json-output subject.sam31/segmented.json \
  --mask-output-dir subject.sam31/masks
```

Pass multiple `--prompt` values when a knockout should include a subject plus
props; the plugin combines the best SAM mask for each prompted label.

The plugin writes a `run.json` manifest before execution, records output paths
and SHA-256 hashes after success, and never creates paid resources.
