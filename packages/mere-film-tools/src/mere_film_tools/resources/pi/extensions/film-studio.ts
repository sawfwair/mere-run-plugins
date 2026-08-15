import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const executable = process.env.MERE_FILM_TOOLS_COMMAND || "mere-film-tools";
const runManifest = process.env.MERE_FILM_RUN_MANIFEST;

function requireManifest(): string {
  if (!runManifest) throw new Error("MERE_FILM_RUN_MANIFEST is not set; launch through mere-film-tools agent");
  return runManifest;
}

async function call(args: string[]): Promise<Record<string, unknown>> {
  const { stdout, stderr } = await execFileAsync(executable, args, {
    cwd: process.cwd(),
    maxBuffer: 16 * 1024 * 1024,
  });
  if (stderr.trim()) process.stderr.write(stderr);
  return JSON.parse(stdout) as Record<string, unknown>;
}

function response(payload: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
    details: payload,
  };
}

export default function filmStudio(pi: ExtensionAPI) {
  pi.registerTool({
    name: "film_status",
    label: "Film status",
    description: "Read authoritative film phase, approvals, tasks, artifacts, and proof state.",
    parameters: Type.Object({}),
    execute: async () => response(await call(["status", requireManifest()])),
  });

  pi.registerTool({
    name: "film_update_brief",
    label: "Update film brief",
    description: "Record user-confirmed creative requirements. Never invent answers for unresolved brief questions.",
    parameters: Type.Object({
      audience: Type.Optional(Type.String()),
      genre: Type.Optional(Type.String()),
      tone: Type.Optional(Type.String()),
      rating: Type.Optional(Type.String()),
      language: Type.Optional(Type.String()),
      platform: Type.Optional(Type.String()),
      usage: Type.Optional(Type.Union([
        Type.Literal("personal"), Type.Literal("noncommercial"), Type.Literal("commercial"),
      ])),
      mustHaves: Type.Optional(Type.Array(Type.String())),
      exclusions: Type.Optional(Type.Array(Type.String())),
      references: Type.Optional(Type.Array(Type.String())),
    }),
    execute: async (_id, params) => {
      const args = ["brief", requireManifest()];
      for (const key of ["audience", "genre", "tone", "rating", "language", "platform"] as const) {
        if (params[key]) args.push(`--${key}`, params[key]);
      }
      if (params.usage) args.push("--usage", params.usage);
      for (const [key, flag] of [["mustHaves", "--must-have"], ["exclusions", "--exclude"], ["references", "--reference"]] as const) {
        for (const value of params[key] || []) args.push(flag, value);
      }
      return response(await call(args));
    },
  });

  pi.registerTool({
    name: "film_approve",
    label: "Approve film gate",
    description: "Record an explicit user approval for one pending gate. Do not call without direct confirmation.",
    parameters: Type.Object({
      gate: Type.Union([
        Type.Literal("brief"), Type.Literal("treatment"), Type.Literal("production"),
        Type.Literal("picture-lock"), Type.Literal("delivery"),
      ]),
      note: Type.String(),
      approvedBy: Type.Optional(Type.String()),
    }),
    execute: async (_id, params) => response(await call([
      "approve", requireManifest(), "--gate", params.gate, "--note", params.note,
      "--approved-by", params.approvedBy || "user-via-pi",
    ])),
  });

  pi.registerTool({
    name: "film_configure",
    label: "Configure film production",
    description: "Configure planned, draft, or final media execution. Explain compute impact before selecting draft or final.",
    parameters: Type.Object({
      mode: Type.Union([Type.Literal("plan"), Type.Literal("draft"), Type.Literal("final")]),
      imageMasterModel: Type.Optional(Type.String()),
      imageShotModel: Type.Optional(Type.String()),
      videoModel: Type.Optional(Type.String()),
      visionInspectorModel: Type.Optional(Type.String()),
      speechAsrModel: Type.Optional(Type.String()),
      speechTtsModel: Type.Optional(Type.String()),
      sfxModel: Type.Optional(Type.String()),
      musicModel: Type.Optional(Type.String()),
      takesPerShot: Type.Optional(Type.Integer({ minimum: 1, maximum: 4 })),
      generateScore: Type.Optional(Type.Boolean()),
      inspectGeneratedMedia: Type.Optional(Type.Boolean()),
    }),
    execute: async (_id, params) => {
      const args = ["configure", requireManifest(), "--mode", params.mode];
      if (params.imageMasterModel) args.push("--image-master-model", params.imageMasterModel);
      if (params.imageShotModel) args.push("--image-shot-model", params.imageShotModel);
      if (params.videoModel) args.push("--video-model", params.videoModel);
      if (params.visionInspectorModel) args.push("--vision-inspector-model", params.visionInspectorModel);
      if (params.speechAsrModel) args.push("--speech-asr-model", params.speechAsrModel);
      if (params.speechTtsModel) args.push("--speech-tts-model", params.speechTtsModel);
      if (params.sfxModel) args.push("--sfx-model", params.sfxModel);
      if (params.musicModel) args.push("--music-model", params.musicModel);
      if (params.takesPerShot) args.push("--takes-per-shot", String(params.takesPerShot));
      if (params.generateScore !== undefined) args.push(params.generateScore ? "--generate-score" : "--no-generate-score");
      if (params.inspectGeneratedMedia !== undefined) {
        args.push(params.inspectGeneratedMedia ? "--inspect-generated-media" : "--no-inspect-generated-media");
      }
      return response(await call(args));
    },
  });

  pi.registerTool({
    name: "film_preflight",
    label: "Preflight film models",
    description: "Resolve every installed model required by the accepted production plan without generating media.",
    parameters: Type.Object({
      mediaTimeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 300 })),
    }),
    execute: async (_id, params) => {
      const args = ["preflight", requireManifest()];
      if (params.mediaTimeoutSeconds) args.push("--media-timeout", String(params.mediaTimeoutSeconds));
      return response(await call(args));
    },
  });

  pi.registerTool({
    name: "film_run",
    label: "Advance film production",
    description: "Advance only through currently approved phases. The plugin stops at every unapproved gate.",
    parameters: Type.Object({
      maxParallel: Type.Optional(Type.Integer({ minimum: 1, maximum: 4 })),
      piTimeoutSeconds: Type.Optional(Type.Integer({ minimum: 30, maximum: 3600 })),
      mediaTimeoutSeconds: Type.Optional(Type.Integer({ minimum: 30, maximum: 86400 })),
    }),
    execute: async (_id, params) => {
      const args = ["run", requireManifest()];
      if (params.maxParallel) args.push("--max-parallel", String(params.maxParallel));
      if (params.piTimeoutSeconds) args.push("--pi-timeout", String(params.piTimeoutSeconds));
      if (params.mediaTimeoutSeconds) args.push("--media-timeout", String(params.mediaTimeoutSeconds));
      return response(await call(args));
    },
  });

  pi.registerTool({
    name: "film_recover",
    label: "Recover film run",
    description: "Convert work orphaned by a dead process into retryable failures without advancing a phase.",
    parameters: Type.Object({}),
    execute: async () => response(await call(["recover", requireManifest()])),
  });

  pi.registerTool({
    name: "film_delegate",
    label: "Delegate film department",
    description: "Run one ready specialist task in an isolated read-only Pi process and record its structured proposal.",
    parameters: Type.Object({ taskId: Type.String() }),
    execute: async (_id, params) => response(await call(["delegate", requireManifest(), "--task", params.taskId])),
  });

  pi.registerTool({
    name: "film_review",
    label: "Review film cut",
    description: "Run technical QC and, unless requested otherwise, independent creative review on the assembled cut.",
    parameters: Type.Object({ technicalOnly: Type.Optional(Type.Boolean()) }),
    execute: async (_id, params) => {
      const args = ["review", requireManifest()];
      if (params.technicalOnly) args.push("--technical-only");
      return response(await call(args));
    },
  });

  pi.registerTool({
    name: "film_record_review_decision",
    label: "Record human film review",
    description: "Record the user's explicit, hash-bound approval or revision request after they watch the local review package. Never call without their direct decision.",
    parameters: Type.Object({
      decision: Type.Union([Type.Literal("approve"), Type.Literal("revise")]),
      reviewer: Type.String(),
      notes: Type.Optional(Type.String()),
      rerolls: Type.Optional(Type.Array(Type.Object({ shotId: Type.String(), note: Type.String() }))),
    }),
    execute: async (_id, params) => {
      const args = [
        "review-decision", requireManifest(), "--decision", params.decision,
        "--reviewer", params.reviewer, "--note", params.notes || "",
      ];
      for (const reroll of params.rerolls || []) args.push("--reroll", `${reroll.shotId}:${reroll.note}`);
      return response(await call(args));
    },
  });

  pi.registerTool({
    name: "film_reroll",
    label: "Reroll film shot",
    description: "Archive a prior shot take and reset only affected production and downstream review proof.",
    parameters: Type.Object({
      shotId: Type.String(),
      note: Type.String(),
    }),
    execute: async (_id, params) => response(await call([
      "reroll", requireManifest(), "--shot", params.shotId, "--note", params.note,
    ])),
  });

  pi.registerCommand("film-status", {
    description: "Show the current Mere Studio production state",
    handler: async (_args, ctx) => {
      const payload = await call(["status", requireManifest()]);
      ctx.ui.notify(`${payload.title}: ${payload.phase} / ${payload.status}`, "info");
    },
  });
}
