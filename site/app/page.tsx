"use client";

import { useMemo, useState } from "react";

type Plugin = {
  id: string;
  name: string;
  number: string;
  description: string;
  capabilities: string[];
  category: "Create" | "Produce" | "Protect" | "Scale";
  color: "coral" | "cyan" | "violet" | "moss" | "amber";
  command: string;
  doc: string;
};

const plugins: Plugin[] = [
  {
    id: "mere-vfx-tools",
    name: "VFX Tools",
    number: "01",
    description:
      "Roto, tracking, clean plates, depth, geometry, relighting, and 3D handoffs built on native mere.run models.",
    capabilities: ["40 capabilities", "shot manifests", "native models"],
    category: "Create",
    color: "coral",
    command: "mere.run plugin install mere-vfx-tools",
    doc: "vfx-tools.md",
  },
  {
    id: "mere-perform",
    name: "Perform",
    number: "02",
    description:
      "Play Magenta Heart as a live instrument with MIDI, prompt blending, a stage view, event logs, and WAV capture.",
    capabilities: ["realtime audio", "MIDI", "stage UI"],
    category: "Create",
    color: "violet",
    command: "mere.run plugin install mere-perform",
    doc: "perform.md",
  },
  {
    id: "mere-animatic-tools",
    name: "Animatic Tools",
    number: "03",
    description:
      "Turn project inputs into shot kits, reference packs, continuity checks, voice kits, and delivery-ready artifacts.",
    capabilities: ["11 workflows", "relay-ready", "local artifacts"],
    category: "Produce",
    color: "cyan",
    command: "mere.run plugin install mere-animatic-tools",
    doc: "animatic-tools.md",
  },
  {
    id: "mere-shotgrid-tools",
    name: "ShotGrid Tools",
    number: "04",
    description:
      "Publish local results to Flow Production Tracking, create review Versions, and pull task-backed production jobs.",
    capabilities: ["review publish", "task sync", "planned writes"],
    category: "Produce",
    color: "amber",
    command: "mere.run plugin install mere-shotgrid-tools",
    doc: "shotgrid-tools.md",
  },
  {
    id: "mere-image-tools",
    name: "Image Tools",
    number: "05",
    description:
      "Create transparent subject knockouts and clean masks with prompted SAM 3.1 segmentation from the core runtime.",
    capabilities: ["SAM 3.1", "alpha masks", "artifact hashes"],
    category: "Create",
    color: "moss",
    command: "mere.run plugin install mere-image-tools",
    doc: "image-tools.md",
  },
  {
    id: "mere-runpod",
    name: "RunPod Runner",
    number: "06",
    description:
      "Run canonical recipes on user-owned ephemeral GPU pods, fetch the artifacts, and terminate the pod by default.",
    capabilities: ["LoRA training", "warm cache", "cleanup-first"],
    category: "Scale",
    color: "coral",
    command: "mere.run plugin install mere-runpod",
    doc: "runpod.md",
  },
  {
    id: "mere-doc-tools",
    name: "Document Tools",
    number: "07",
    description:
      "OCR local documents and remove personally identifiable information without sending source files to a hosted workflow.",
    capabilities: ["OCR", "PII redaction", "private by design"],
    category: "Protect",
    color: "cyan",
    command: "mere.run plugin install mere-doc-tools",
    doc: "workflow-tools.md",
  },
  {
    id: "mere-media-scrub",
    name: "Media Scrub",
    number: "08",
    description:
      "Batch OCR frame directories and redact sensitive extracted text with a resumable, inspectable local run.",
    capabilities: ["frame batches", "redaction", "resumable"],
    category: "Protect",
    color: "violet",
    command: "mere.run plugin install mere-media-scrub",
    doc: "workflow-tools.md",
  },
  {
    id: "mere-dataset-tools",
    name: "Dataset Tools",
    number: "09",
    description:
      "Prepare LoRA datasets with local captions, OCR sidecars, trigger tokens, focus guidance, and contact sheets.",
    capabilities: ["captioning", "LoRA prep", "contact sheets"],
    category: "Produce",
    color: "moss",
    command: "mere.run plugin install mere-dataset-tools",
    doc: "workflow-tools.md",
  },
  {
    id: "mere-transcript-tools",
    name: "Transcript Tools",
    number: "10",
    description:
      "Transcribe local audio and optionally redact sensitive language while preserving the exact run and outputs.",
    capabilities: ["speech", "transcription", "optional redaction"],
    category: "Protect",
    color: "amber",
    command: "mere.run plugin install mere-transcript-tools",
    doc: "workflow-tools.md",
  },
  {
    id: "mere-image-compose",
    name: "Image Compose",
    number: "11",
    description:
      "Record repeatable local image compositions with prompts, reference images, LoRAs, and hashed generated outputs.",
    capabilities: ["image generation", "references", "LoRAs"],
    category: "Create",
    color: "coral",
    command: "mere.run plugin install mere-image-compose",
    doc: "workflow-tools.md",
  },
  {
    id: "mere-batch-runner",
    name: "Batch Runner",
    number: "12",
    description:
      "Run explicit mere.run commands from JSONL with durable state, per-job status, resumability, and output hashing.",
    capabilities: ["JSONL", "automation", "resume"],
    category: "Scale",
    color: "cyan",
    command: "mere.run plugin install mere-batch-runner",
    doc: "workflow-tools.md",
  },
];

const categories = ["All", "Create", "Produce", "Protect", "Scale"] as const;
type Category = (typeof categories)[number];

const repo = "https://github.com/sawfwair/mere-run-plugins";

function CopyButton({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <button className="copy-button" type="button" onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function Home() {
  const [category, setCategory] = useState<Category>("All");
  const visiblePlugins = useMemo(
    () =>
      category === "All"
        ? plugins
        : plugins.filter((plugin) => plugin.category === category),
    [category],
  );

  return (
    <main>
      <a className="skip-link" href="#plugins">
        Skip to plugin explorer
      </a>

      <header className="site-header shell">
        <a className="wordmark" href="#top" aria-label="mere.run plugins home">
          <span>mere.run</span>
          <span className="wordmark-slash">/</span>
          <span className="wordmark-sub">plugins</span>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#plugins">Plugins</a>
          <a href="#contract">Contract</a>
          <a href={`${repo}/blob/main/README.md`}>Docs</a>
        </nav>
        <a className="github-link" href={repo}>
          GitHub <span aria-hidden="true">↗</span>
        </a>
      </header>

      <section className="hero shell" id="top">
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="live-dot" aria-hidden="true" />
            Official companion plugins
          </p>
          <h1>
            Local AI,
            <br />
            <em>extended.</em>
          </h1>
          <p className="hero-deck">
            Twelve companion plugins turn <strong>mere.run</strong> into a
            production system—from realtime music and VFX to private documents
            and user-owned GPU training.
          </p>
          <div className="hero-actions">
            <a className="primary-cta" href="#plugins">
              Explore the plugins <span aria-hidden="true">↓</span>
            </a>
            <a className="text-link" href="#contract">
              See the contract <span aria-hidden="true">↘</span>
            </a>
          </div>
          <div className="proof-line" aria-label="Twelve plugins, one local-first runtime">
            <span>12 plugins</span>
            <span className="proof-rule" />
            <span>1 local-first runtime</span>
          </div>
        </div>

        <div className="signal-stage" aria-label="Plugin signal map">
          <div className="beam beam-one" />
          <div className="beam beam-two" />
          <div className="beam beam-three" />
          <div className="beam beam-four" />
          <div className="signal-core">
            <span>local core</span>
            <strong>mere</strong>
            <small>run</small>
          </div>
          <div className="signal-node node-perform">
            <span>02</span>
            Perform
          </div>
          <div className="signal-node node-vfx">
            <span>01</span>
            VFX
          </div>
          <div className="signal-node node-runpod">
            <span>06</span>
            RunPod
          </div>
          <div className="signal-node node-docs">
            <span>07</span>
            Docs
          </div>
          <div className="stage-caption">
            <span>One runtime</span>
            <span>Many production paths</span>
          </div>
        </div>
      </section>

      <section className="ecosystem-strip" aria-label="Plugin capability overview">
        <div className="shell ecosystem-track">
          <span>create</span>
          <i />
          <span>produce</span>
          <i />
          <span>protect</span>
          <i />
          <span>scale</span>
          <b>→</b>
          <strong>ship the artifacts</strong>
        </div>
      </section>

      <section className="plugins-section shell" id="plugins">
        <div className="section-heading">
          <div>
            <p className="eyebrow">The plugin index · 2026</p>
            <h2>Choose a path.<br />Keep the runtime.</h2>
          </div>
          <p>
            Plugins coordinate the work around inference: plans, manifests,
            remote resources, production handoffs, and durable artifacts. The
            canonical model behavior stays in <strong>mere.run</strong>.
          </p>
        </div>

        <div className="filter-row" role="group" aria-label="Filter plugins by purpose">
          {categories.map((item) => (
            <button
              key={item}
              type="button"
              className={category === item ? "is-active" : ""}
              aria-pressed={category === item}
              onClick={() => setCategory(item)}
            >
              {item}
              <span>
                {item === "All"
                  ? plugins.length
                  : plugins.filter((plugin) => plugin.category === item).length}
              </span>
            </button>
          ))}
        </div>

        <div className="plugin-grid" aria-live="polite">
          {visiblePlugins.map((plugin) => (
            <article className={`plugin-card ${plugin.color}`} key={plugin.id}>
              <div className="card-topline">
                <span>{plugin.number}</span>
                <span>{plugin.category}</span>
              </div>
              <h3>{plugin.name}</h3>
              <p>{plugin.description}</p>
              <ul aria-label={`${plugin.name} highlights`}>
                {plugin.capabilities.map((capability) => (
                  <li key={capability}>{capability}</li>
                ))}
              </ul>
              <div className="install-row">
                <code>{plugin.command}</code>
                <CopyButton command={plugin.command} />
              </div>
              <a
                className="card-link"
                href={`${repo}/blob/main/docs/plugins/${plugin.doc}`}
                aria-label={`Read ${plugin.name} documentation`}
              >
                Read the workflow <span aria-hidden="true">↗</span>
              </a>
            </article>
          ))}
        </div>
      </section>

      <section className="contract-section" id="contract">
        <div className="shell contract-grid">
          <div className="contract-intro">
            <p className="eyebrow">A shared production contract</p>
            <h2>Power you can inspect.</h2>
            <p>
              Every official plugin exposes the same lifecycle. Plans are
              reviewable, runs are durable, and cleanup is a first-class command.
            </p>
            <a className="text-link" href={`${repo}/blob/main/docs/plugins/contract.md`}>
              Read the plugin contract <span aria-hidden="true">↗</span>
            </a>
          </div>
          <div className="contract-flow" aria-label="Plugin command lifecycle">
            {[
              ["01", "doctor", "Check readiness. No paid resources."],
              ["02", "plan", "Preview the exact work and write run.json."],
              ["03", "run", "Execute locally or on infrastructure you control."],
              ["04", "resume", "Continue from durable state."],
              ["05", "cleanup", "Terminate remote resources by default."],
            ].map(([step, command, description]) => (
              <div className="contract-step" key={command}>
                <span>{step}</span>
                <code>{command}</code>
                <p>{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="final-cta shell">
        <p className="eyebrow">Start with one command</p>
        <h2>Extend the runtime.<br />Own the workflow.</h2>
        <div className="big-command">
          <span aria-hidden="true">$</span>
          <code>mere.run plugin list</code>
          <CopyButton command="mere.run plugin list" />
        </div>
        <div className="final-links">
          <a className="primary-cta" href={`${repo}/blob/main/README.md`}>
            Get started <span aria-hidden="true">↗</span>
          </a>
          <a className="text-link" href={`${repo}/blob/main/catalog/plugins.v1.json`}>
            Inspect the live catalog <span aria-hidden="true">↗</span>
          </a>
        </div>
      </section>

      <footer className="site-footer shell">
        <a className="wordmark" href="#top">
          <span>mere.run</span>
          <span className="wordmark-slash">/</span>
          <span className="wordmark-sub">plugins</span>
        </a>
        <p>Local-first by design. User-controlled at every boundary.</p>
        <div>
          <a href={`${repo}/blob/main/LICENSE`}>MIT License</a>
          <a href={repo}>GitHub</a>
        </div>
      </footer>
    </main>
  );
}
