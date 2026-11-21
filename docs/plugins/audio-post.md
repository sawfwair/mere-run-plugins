# Audio Post

Prepare audio from a recording or video clip for editing. Export a 48 kHz
floating-point WAV and measure its loudness, or choose a local model to remove
noise or reverb, separate stems, transcribe music to MIDI, or generate Foley.

## Install and check

Install [FFmpeg](https://ffmpeg.org/download.html) and a compatible
[mere.run release](https://mere.run/releases). On Apple Silicon, the plugin
catalog offers a signed Mac bundle. To choose a pipx source install, add
`--source`.

```bash
mere.run plugin install mere-audio-post --yes
mere.run plugin doctor mere-audio-post
```

## Export and measure audio

```bash
mere.run plugin run mere-audio-post -- process \
  --input ./scene.mov --output-dir ./audio-post
```

Audio Post exports the first audio stream to `audio/source.wav`. The
`audio/loudness.json` report lists integrated loudness in LUFS, true peak in
dBTP, and loudness range in LU for each delivered WAV. An unavailable or
nonfinite measurement appears as `null`. The export preserves floating-point
headroom and measures loudness without applying gain.

## Run a model task

Choose a fresh output directory for each task. Use `plan` with the same
arguments to check the required model IDs before running. Pull the required
models separately with `mere.run model pull MODEL_ID`. Review any model
terms before accepting them. Inference availability depends on your Mere
runtime and hardware.

| Task | Required model | Additional outputs |
| --- | --- | --- |
| `--task denoise` | `music-separate-mel-roformer-denoise` | `denoise.wav` |
| `--task dereverb` | `music-separate-mel-roformer-dereverb` | `dereverb.wav` |
| `--task stems --stems four` | `music-separate-bs-roformer-4stem` | Drums, bass, other, and vocals WAVs |
| `--task stems --stems two` | `music-separate-bs-roformer-viperx-1297` | Vocals and instrumental WAVs |
| `--task midi` | `music-muscriptor-medium` | `music.mid` and `musical-context.json` |
| `--task foley --prompt "Footsteps on gravel"` | `sfx-woosh-dvflow-8s` and `sfx-woosh-synchformer` | One eight-second `foley.wav` synchronized to a video clip |

The MuScriptor checkpoint uses noncommercial model terms. Review the terms
before using MIDI transcription in a production. Use a video clip prepared
for an eight-second Foley take, then place the generated WAV in your timeline.

## Save and run a plan

```bash
mere.run plugin run mere-audio-post -- plan \
  --input ./mix.wav --output-dir ./stems --task stems
mere.run plugin run mere-audio-post -- run ./stems/run.json
mere.run plugin run mere-audio-post -- resume ./stems/run.json
```

A plan writes the required model IDs and an input fingerprint. A completed
run records the delivered files and their SHA-256 hashes in `run.json`.
