# Dataset Tools

`mere-dataset-tools` prepares local image datasets for LoRA workflows with
captions, optional OCR sidecars, trigger tokens, focus guidance, and a contact
sheet.

## Install and caption

```bash
mere.run plugin install mere-dataset-tools
mere-dataset-tools doctor
mere-dataset-tools caption \
  --input ./dataset \
  --output-dir ./caption-out \
  --trigger-token STYLE \
  --focus "material and silhouette" \
  --contact-sheet
```

Add `--ocr` when visible text should be extracted into sidecars. Use
`--prompt` to supply caption guidance and repeat `--focus` for multiple
priorities.

## Plan first

```bash
mere-dataset-tools plan \
  --input ./dataset \
  --output-dir ./caption-out \
  --trigger-token STYLE \
  --run-id dataset-001
mere-dataset-tools run ./caption-out/run.json
```

## Next step

Inspect the captions and contact sheet before training. A prepared paired dataset
can feed the [Klein LoRA recipe](/recipes/klein-lora) through
[RunPod Runner](/plugins/runpod).
