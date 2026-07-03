# Klein LoRA Recipes

The canonical Klein flow has two phases:

1. Train the LoRA on `image-klein-base-9b`.
2. Apply the LoRA on distilled `image-klein-9b` for practical generation.

The recipes are machine-readable JSON files in `recipes/`.

Reference-image eval protocols live separately in `eval-recipes/`. Use
`klein-times-square-kiss` when you need a fixed composition test for comparing
style pull across multiple Klein LoRAs.

## Style LoRA

Use `klein-style-lora` for broad visual style.

Recommended use:

- image sets where the whole visual language matters
- film/frame/card/comic looks
- lighting, color, composition, texture, and medium transfer

Captioning:

- each caption starts with the trigger token
- each caption describes only visible content
- do not name the style in the caption
- do not mention that the image belongs to a dataset

The style recipe delegates to `mere.run image train-lora --recipe
klein-fast-style`, which currently selects the `fal-klein-fast` LoRA target
preset, the Klein base model, low-memory CUDA settings, and 250-step
checkpoints. The plugin recipe adds explicit sample generation against
`image-klein-9b` so remote runs produce preview artifacts without relying on
implicit local defaults.

## Character LoRA

Use `klein-character-lora` for identity portability.

Recommended use:

- a recurring person or character
- a mascot
- a fictional subject that should survive scene changes

Captioning:

- each caption starts with the trigger token
- include a class noun such as `man`, `woman`, `robot`, or `character`
- repeat stable identity anchors in every caption
- describe variables like pose, clothing, expression, crop, background, and
  medium
- never write `same person`, `same character`, `previous image`, or
  `another view`

Character LoRAs should be evaluated by changing the scene, pose, clothing,
medium, and camera distance. If the identity only works in the training outfit
or training background, the adapter is overbound.

The character recipe also uses `klein-fast-style` as its base and only overrides
identity-focused capacity and caption dropout values. Keep additional
experimental training flags in local custom recipe files until they are part of
the core `mere.run` preset surface.
