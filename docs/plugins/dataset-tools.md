# Dataset Tools plugin

`mere-dataset-tools` prepares local image datasets for LoRA workflows with
captions, optional OCR sidecars, trigger tokens, focus guidance, and a contact
sheet. It also prepares plain-text examples, trains a native text LoRA, and
compares the adapter with its base model.

## Install and caption

```bash
mere.run plugin install mere-dataset-tools --yes
mere-dataset-tools doctor
mere-dataset-tools caption \
  --input ./dataset \
  --output-dir ./caption-out \
  --trigger-token STYLE \
  --focus "material and silhouette" \
  --contact-sheet
```

To extract visible text into sidecars, add `--ocr`. Use
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

## Train an image LoRA

Inspect the captions and contact sheet before training. A prepared paired dataset
can feed the [Klein LoRA recipe](/recipes/klein-lora) through
[RunPod Runner](/plugins/runpod).

## Train a text LoRA

Use three reviewed JSONL files.

- `train.jsonl` contains the examples used to update the adapter.
- `held-out.jsonl` contains chat examples used to measure assistant-token
  loss before and after training.
- `behavior.jsonl` contains prompts scored against exact expected responses
  for both the base model and the adapter.

The training and held-out files accept native-style `sources` and `messages`
records with an optional `id`. Start with a system
message, then alternate user and assistant messages. The native trainer
requires at least four characters per message. Behavior rows
contain an `id`, `prompt`, and `expected` string. Matching is case-sensitive
and ignores surrounding whitespace. See the [synthetic example files](https://github.com/sawfwair/mere-run-plugins/tree/main/examples/text-lora).

```bash
mere-dataset-tools text-lora prepare \
  --train-data ./train.jsonl \
  --held-out-data ./held-out.jsonl \
  --behavior-data ./behavior.jsonl \
  --output-dir ./prepared
```

Preparation rejects user prompts that repeat across splits after Unicode,
case, and whitespace normalization. Review the splits for paraphrases and other
forms of overlap. The prepared directory contains private examples and a
`dataset.json` receipt with file hashes.

Choose an installed managed text model supported by native LoRA training, such
as `text-chat-laguna-xs-2-1`. See the
[native training guide](https://github.com/sawfwair/mere-run/blob/v0.73.1/docs/runtime/text.md#train-a-lora-adapter)
for supported models and hardware.

```bash
mere-dataset-tools text-lora train \
  --dataset ./prepared/dataset.json \
  --model text-chat-laguna-xs-2-1 \
  --steps 100 \
  --output-dir ./trained
```

Add `--dry-run` to validate the data with the native runtime before loading a
model. A completed run writes `adapter.safetensors`, the adjacent native
manifest, and a `training.json` receipt with before-and-after held-out loss and
assistant-token counts. To continue a native optimizer-bearing checkpoint, use
`--resume-from` with the same dataset and settings and a fresh output directory.

## Compare behavior against the base model

```bash
mere-dataset-tools text-lora evaluate \
  --dataset ./prepared/dataset.json \
  --training ./trained/training.json \
  --output-dir ./comparison
```

Evaluation checks the trained adapter and files against their recorded hashes,
then runs both arms with the same managed model and greedy sampling. The report
lists pass rates and how many cases improved or regressed. It uses built-in
assertions and omits raw prompts and model responses. Add `--resume` with the
same arguments to resume an interrupted comparison from its checkpoint.

Held-out training loss and exact-response behavior answer different questions.
Use both results when deciding whether the adapter is suitable for your task.
