# Klein Reference Evaluation Recipes

Reference-image LoRA evals test whether an adapter can pull a neutral source
image into the learned style while preserving a fixed composition. They are
recipes for comparing adapters, not model-training recipes.

Machine-readable eval recipes live in `eval-recipes/`.

## Times Square Kiss

Use `klein-times-square-kiss` when comparing Klein style LoRAs against the same
source photograph.

Fixed settings:

```bash
mere.run image generate \
  --model image-klein-9b \
  --ref-image ./street-kiss.png \
  --strength 0.55 \
  --width 1024 \
  --height 768 \
  --steps 16 \
  --seed 424243 \
  --lora ./style.safetensors \
  --lora-scale 1.5 \
  --prompt "$PROMPT" \
  --output ./runs/kiss-eval/style-times-square-kiss.png
```

Prompt shape:

```text
STYLE_TRIGGER a sailor in uniform kissing a nurse in a crowded city street,
full body embrace, her right arm around his shoulder, her left arm hidden behind
his back, his arms around her waist, natural human anatomy, no extra limbs, no
extra hands, crisp faces, detailed fabric texture, clear depth separation, high
detail, clean sharp cinematic film still, STYLE_DIRECTION
```

Guidance:

- Use distilled `image-klein-9b` for generation.
- Keep `--strength 0.55` and `--lora-scale 1.5` as the first comparison pass.
- Use seed `424243` for the cleaner anatomy baseline.
- If arms duplicate, keep the same LoRA and try the side-view repair variant
  from `eval-recipes/klein-times-square-kiss.json` before retraining.
- Do not make the prompt so style-specific that the base model can solve it
  without the adapter.
- Store private source images, LoRAs, and generated eval outputs outside the
  public core repo. A project-local path such as
  `data/lora-evals/times-square-kiss/` is appropriate for artifacts.

